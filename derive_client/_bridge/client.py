"""
Bridge client to deposit funds to the Derive smart contract funding account
"""

from __future__ import annotations

import functools
import json
from typing import Literal

from eth_account import Account
from web3 import Web3
from web3.contract import Contract
from web3.datastructures import AttributeDict

from derive_client._bridge.transaction import ensure_allowance, ensure_balance, prepare_mainnet_to_derive_gas_tx
from derive_client.constants import (
    CONFIGS,
    CONTROLLER_ABI_PATH,
    CONTROLLER_V0_ABI_PATH,
    DEFAULT_GAS_FUNDING_AMOUNT,
    DEPOSIT_GAS_LIMIT,
    DEPOSIT_HELPER_ABI_PATH,
    DEPOSIT_HOOK_ABI_PATH,
    DERIVE_ABI_PATH,
    DERIVE_L2_ABI_PATH,
    L1_STANDARD_BRIDGE_ABI_PATH,
    LIGHT_ACCOUNT_ABI_PATH,
    LYRA_OFT_WITHDRAW_WRAPPER_ABI_PATH,
    LYRA_OFT_WITHDRAW_WRAPPER_ADDRESS,
    MSG_GAS_LIMIT,
    NEW_VAULT_ABI_PATH,
    OLD_VAULT_ABI_PATH,
    PAYLOAD_SIZE,
    SOCKET_ABI_PATH,
    TARGET_SPEED,
    WITHDRAW_WRAPPER_V2_ABI_PATH,
)
from derive_client.data_types import (
    Address,
    BridgePair,
    BridgeTxResult,
    ChainID,
    Currency,
    DeriveTokenAddresses,
    Environment,
    LayerZeroChainIDv2,
    MintableTokenData,
    NonMintableTokenData,
    RPCEndPoints,
    SocketAddress,
    TxResult,
    TxStatus,
)
from derive_client.utils import (
    build_standard_transaction,
    get_contract,
    get_erc20_contract,
    get_prod_derive_addresses,
    get_w3_connection,
    make_filter_params,
    send_and_confirm_tx,
    wait_for_event,
    wait_for_tx_receipt,
)


def _load_vault_contract(w3: Web3, token_data: NonMintableTokenData) -> Contract:
    path = NEW_VAULT_ABI_PATH if token_data.isNewBridge else OLD_VAULT_ABI_PATH
    abi = json.loads(path.read_text())
    return get_contract(w3=w3, address=token_data.Vault, abi=abi)


def _load_controller_contract(w3: Web3, token_data: MintableTokenData) -> Contract:
    path = CONTROLLER_ABI_PATH if token_data.isNewBridge else CONTROLLER_V0_ABI_PATH
    abi = json.loads(path.read_text())
    return get_contract(w3=w3, address=token_data.Controller, abi=abi)


def _load_deposit_contract(w3: Web3, token_data: MintableTokenData) -> Contract:
    address = token_data.LyraTSAShareHandlerDepositHook
    abi = json.loads(DEPOSIT_HOOK_ABI_PATH.read_text())
    return get_contract(w3=w3, address=address, abi=abi)


def _load_light_account(w3: Web3, wallet: Address) -> Contract:
    abi = json.loads(LIGHT_ACCOUNT_ABI_PATH.read_text())
    return get_contract(w3=w3, address=wallet, abi=abi)


def _get_min_fees(
    bridge_contract: Contract,
    connector: Address,
    token_data: NonMintableTokenData | MintableTokenData,
) -> int:
    params = {
        "connector_": connector,
        "msgGasLimit_": MSG_GAS_LIMIT,
    }
    if token_data.isNewBridge:
        params["payloadSize_"] = PAYLOAD_SIZE

    return bridge_contract.functions.getMinFees(**params).call()


class BridgeClient:
    def __init__(self, env: Environment, chain_id: ChainID, account: Account, wallet: Address):
        if not env == Environment.PROD:
            raise RuntimeError(f"Bridging is not supported in the {env.name} environment.")
        self.config = CONFIGS[env]
        self.derive_w3 = get_w3_connection(chain_id=ChainID.DERIVE)
        self.remote_w3 = get_w3_connection(chain_id=chain_id)
        self.account = account
        self.withdraw_wrapper = self._load_withdraw_wrapper()
        self.deposit_helper = self._load_deposit_helper()
        self.derive_addresses = get_prod_derive_addresses()
        self.light_account = _load_light_account(w3=self.derive_w3, wallet=wallet)
        if self.owner != self.account.address:
            raise ValueError(
                "Bridging disabled for secondary session-key signers: old-style assets "
                "(USDC, USDT) on Derive cannot specify a custom receiver. Using a "
                "secondary signer routes funds to the session key's contract instead of "
                "the primary owner's. Please run all bridge operations with the "
                "primary wallet owner."
            )

    @property
    def remote_chain_id(self) -> ChainID:
        return ChainID(self.remote_w3.eth.chain_id)

    @property
    def wallet(self) -> Address:
        """Smart contract funding wallet."""
        return self.light_account.address

    @functools.cached_property
    def owner(self) -> Address:
        """Owner of smart contract funding wallet, must be the same as self.account.address."""
        return self.light_account.functions.owner().call()

    @property
    def private_key(self):
        """Private key of the owner (EOA) of the smart contract funding account."""
        return self.account._private_key

    def _load_deposit_helper(self) -> Contract:
        address = (
            self.config.contracts.DEPOSIT_WRAPPER
            if self.remote_chain_id
            not in [
                ChainID.ARBITRUM,
                ChainID.OPTIMISM,
            ]
            else getattr(
                self.config.contracts,
                f"{self.remote_chain_id.name}_DEPOSIT_WRAPPER",
            )
        )
        abi = json.loads(DEPOSIT_HELPER_ABI_PATH.read_text())
        return get_contract(w3=self.remote_w3, address=address, abi=abi)

    def _load_withdraw_wrapper(self) -> Contract:
        address = self.config.contracts.WITHDRAW_WRAPPER_V2
        abi = json.loads(WITHDRAW_WRAPPER_V2_ABI_PATH.read_text())
        return get_contract(w3=self.derive_w3, address=address, abi=abi)

    def _make_bridge_pair(self, direction: Literal["deposit", "withdraw"]) -> BridgePair:
        derive_addr = DeriveTokenAddresses.DERIVE.value
        remote_addr = DeriveTokenAddresses[self.remote_chain_id.name].value
        derive_abi = json.loads(DERIVE_L2_ABI_PATH.read_text())
        remote_abi = json.loads(
            DERIVE_ABI_PATH.read_text() if self.remote_chain_id == ChainID.ETH else DERIVE_L2_ABI_PATH.read_text()
        )

        if direction == "deposit":
            src_w3, tgt_w3 = self.remote_w3, self.derive_w3
            src_addr, tgt_addr = remote_addr, derive_addr
            src_abi, tgt_abi = remote_abi, derive_abi
        else:
            src_w3, tgt_w3 = self.derive_w3, self.remote_w3
            src_addr, tgt_addr = derive_addr, remote_addr
            src_abi, tgt_abi = derive_abi, remote_abi

        src = get_contract(src_w3, src_addr, abi=src_abi)
        tgt = get_contract(tgt_w3, tgt_addr, abi=tgt_abi)
        return BridgePair(src_w3, tgt_w3, src, tgt)

    def deposit_drv(self, amount: int) -> BridgeTxResult:
        """
        Deposit funds by preparing, signing, and sending a bridging transaction.
        """

        # record on target chain when we start polling
        pair = self._make_bridge_pair("deposit")
        from_block = pair.target_w3.eth.block_number

        # check allowance, if needed approve
        ensure_balance(pair.source_token, self.owner, amount)
        ensure_allowance(
            w3=pair.source_w3,
            token_contract=pair.source_token,
            owner=self.owner,
            spender=pair.source_token.address,
            amount=amount,
            private_key=self.private_key,
        )

        # build the send tx
        receiver_bytes32 = Web3.to_bytes(hexstr=self.wallet).rjust(32, b"\x00")

        kwargs = {
            "dstEid": LayerZeroChainIDv2.DERIVE.value,
            "receiver": receiver_bytes32,
            "amountLD": amount,
            "minAmountLD": 0,
            "extraOptions": b"",
            "composeMsg": b"",
            "oftCmd": b"",
        }

        pay_in_lz_token = False
        send_params = tuple(kwargs.values())
        fees = pair.source_token.functions.quoteSend(send_params, pay_in_lz_token).call()
        native_fee, lz_token_fee = fees
        refund_address = self.owner

        func = pair.source_token.functions.send(send_params, fees, refund_address)
        tx = build_standard_transaction(func=func, account=self.account, w3=pair.source_w3, value=native_fee)

        # Setup the BridgeTxResult and send the tx on the source chain
        target_tx = TxResult(tx_hash="", tx_receipt=None, exception=None)
        source_tx = send_and_confirm_tx(w3=pair.source_w3, tx=tx, private_key=self.private_key, action="executeBatch()")
        tx_result = BridgeTxResult(
            source_chain=self.remote_chain_id,
            target_chain=ChainID.DERIVE,
            source_tx=source_tx,
            target_tx=target_tx,
        )
        if not source_tx.status == TxStatus.SUCCESS:
            return tx_result

        # Get the LayerZero GUID out of the OFTSent event on from the source chain
        try:
            event = pair.source_token.events.OFTSent().process_log(source_tx.tx_receipt.logs[-1])
            guid = event["args"]["guid"]
        except Exception as e:
            msg = f"Could not decode OFTSent guid: {e}"
            source_tx.exception = ValueError(msg)
            return tx_result

        print(f"🔖 Source [{tx_result.source_chain.name}] OFTSent GUID: {guid.hex()}")
        filter_params = make_filter_params(
            event=pair.target_token.events.OFTReceived(),
            from_block=from_block,
            argument_filters={"guid": guid},
        )

        print(f"🔍 Listening for OFTReceived on [{tx_result.target_chain.name}] at {pair.target_token.address}")
        try:
            event_log = wait_for_event(pair.target_w3, filter_params)
            target_tx.tx_hash = event_log["transactionHash"].to_0x_hex()
            target_tx.tx_receipt = wait_for_tx_receipt(w3=pair.target_w3, tx_hash=target_tx.tx_hash)
        except Exception as e:
            target_tx.exception = e

        return tx_result

    def deposit(self, amount: int, currency: Currency) -> BridgeTxResult:
        """
        Deposit funds by preparing, signing, and sending a bridging transaction.
        """

        if (token_data := self.derive_addresses.chains[self.remote_chain_id].get(currency)) is None:
            msg = f"Currency {currency} not found in Derive addresses for chain {self.remote_chain_id}."
            raise ValueError(msg)

        chain_id = self.remote_chain_id
        from_block = self.derive_w3.eth.block_number

        spender = token_data.Vault if token_data.isNewBridge else self.deposit_helper.address

        # Get the token contract and socket contract instances.
        abi = json.loads(SOCKET_ABI_PATH.read_text())
        source_socket = get_contract(self.remote_w3, address=SocketAddress[chain_id.name].value, abi=abi)
        target_socket = get_contract(self.derive_w3, address=SocketAddress.DERIVE.value, abi=abi)
        token_contract = get_erc20_contract(self.remote_w3, token_data.NonMintableToken)

        ensure_balance(token_contract, self.owner, amount)
        ensure_allowance(
            w3=self.remote_w3,
            token_contract=token_contract,
            owner=self.owner,
            spender=spender,
            amount=amount,
            private_key=self.private_key,
        )

        if token_data.isNewBridge:
            tx = self._prepare_new_style_deposit(token_data, amount)
        else:
            tx = self._prepare_old_style_deposit(token_data, amount)

        target_tx = TxResult(tx_hash="", tx_receipt=None, exception=None)
        source_tx = send_and_confirm_tx(w3=self.remote_w3, tx=tx, private_key=self.private_key, action="bridge()")
        tx_result = BridgeTxResult(
            source_chain=self.remote_chain_id,
            target_chain=ChainID.DERIVE,
            source_tx=source_tx,
            target_tx=target_tx,
        )
        if not source_tx.status == TxStatus.SUCCESS:
            return tx_result

        return self._wait_for_socket_settlement(self.derive_w3, from_block, tx_result, source_socket, target_socket)

    def withdraw_with_wrapper(self, amount: int, currency: Currency) -> BridgeTxResult:
        """
        Checks if sufficent gas is available in derive, if not funds the wallet.
        Prepares, signs, and sends a withdrawal transaction using the withdraw wrapper.
        """
        # TODO: if token balance is insufficient one gets web3.exceptions.ContractCustomError

        token_data: MintableTokenData = self.derive_addresses.chains[ChainID.DERIVE][currency]
        chain_id = self.remote_chain_id
        from_block = self.remote_w3.eth.block_number  # record on target chain before tx submission on source chain

        if chain_id not in token_data.connectors:
            msg = f"Target chain {chain_id} not found in token data connectors. Please check input configuration."
            raise ValueError(msg)

        self._ensure_derive_eth_balance()
        connector = token_data.connectors[chain_id][TARGET_SPEED]

        # Get the token contract and socket contract instances.
        abi = json.loads(SOCKET_ABI_PATH.read_text())
        source_socket = get_contract(self.derive_w3, address=SocketAddress.DERIVE.value, abi=abi)
        target_socket = get_contract(self.remote_w3, address=SocketAddress[chain_id.name].value, abi=abi)
        token_contract = get_erc20_contract(self.derive_w3, token_data.MintableToken)

        self._check_bridge_funds(token_data, connector, amount)

        kwargs = {
            "token": token_contract.address,
            "amount": amount,
            "recipient": self.owner,
            "socketController": token_data.Controller,
            "connector": connector,
            "gasLimit": MSG_GAS_LIMIT,
        }

        # Encode the token approval and withdrawToChain for the withdraw wrapper.
        approve_data = token_contract.encodeABI(fn_name="approve", args=[self.withdraw_wrapper.address, amount])
        bridge_data = self.withdraw_wrapper.encodeABI(fn_name="withdrawToChain", args=list(kwargs.values()))

        # Build the batch execution call via the Light Account.
        func = self.light_account.functions.executeBatch(
            dest=[token_contract.address, self.withdraw_wrapper.address],
            func=[approve_data, bridge_data],
        )

        tx = build_standard_transaction(func=func, account=self.account, w3=self.derive_w3, value=0)

        target_tx = TxResult(tx_hash="", tx_receipt=None, exception=None)
        source_tx = send_and_confirm_tx(w3=self.derive_w3, tx=tx, private_key=self.private_key, action="executeBatch()")
        tx_result = BridgeTxResult(
            source_chain=ChainID.DERIVE,
            target_chain=self.remote_chain_id,
            source_tx=source_tx,
            target_tx=target_tx,
        )
        if not source_tx.status == TxStatus.SUCCESS:
            return tx_result

        return self._wait_for_socket_settlement(self.remote_w3, from_block, tx_result, source_socket, target_socket)

    def _wait_for_socket_settlement(self, target_w3, from_block, tx_result, source_socket, target_socket):

        source_tx = tx_result.source_tx
        target_tx = tx_result.target_tx

        try:
            source_event = source_socket.events.MessageOutbound().process_log(source_tx.tx_receipt.logs[-2])
            message_id = source_event["args"]["msgId"]
        except Exception as e:
            msg = f"Failed to retrieve `msgId` from the Socket MessageOutbound event log from source tx_receipt: {e}"
            source_tx.exception = ValueError(msg)
            return tx_result

        print(f"🔖 Source [{tx_result.source_chain.name}] MessageOutbound msgId: {message_id.hex()}")
        target_event = target_socket.events.ExecutionSuccess()
        filter_params = target_event._get_event_filter_params(fromBlock=from_block, abi=target_event.abi)

        def matching_message_id(log: AttributeDict) -> bool:
            try:
                decoded = target_event.process_log(log)
                return decoded["args"].get("msgId") == message_id
            except Exception:
                return False

        print(f"🔍 Listening for ExecutionSuccess on [{tx_result.target_chain.name}] at {target_socket.address}")
        try:
            event_log = wait_for_event(target_w3, filter_params, condition=matching_message_id)
            target_tx.tx_hash = event_log["transactionHash"].to_0x_hex()
            target_tx.tx_receipt = wait_for_tx_receipt(w3=target_w3, tx_hash=target_tx.tx_hash)
        except Exception as e:
            target_tx.exception = e

        return tx_result

    def withdraw_drv(self, amount: int) -> BridgeTxResult:
        self._ensure_derive_eth_balance()

        # record on target chain when we start polling
        pair = self._make_bridge_pair("withdraw")
        from_block = pair.target_w3.eth.block_number

        abi = json.loads(LYRA_OFT_WITHDRAW_WRAPPER_ABI_PATH.read_text())
        withdraw_wrapper = get_contract(pair.source_w3, LYRA_OFT_WITHDRAW_WRAPPER_ADDRESS, abi=abi)

        balance = pair.source_token.functions.balanceOf(self.wallet).call()
        if balance < amount:
            raise ValueError(f"Not enough tokens to withdraw: {amount} < {balance} ({(balance / amount * 100):.2f}%) ")

        destEID = LayerZeroChainIDv2[self.remote_chain_id.name]
        fee = withdraw_wrapper.functions.getFeeInToken(pair.source_token.address, amount, destEID).call()
        if amount < fee:
            raise ValueError(f"Withdraw amount < fee: {amount} < {fee} ({(fee / amount * 100):.2f}%)")

        kwargs = {
            "token": pair.source_token.address,
            "amount": amount,
            "toAddress": self.owner,
            "destEID": destEID,
        }

        approve_data = pair.source_token.encodeABI(fn_name="approve", args=[withdraw_wrapper.address, amount])
        bridge_data = withdraw_wrapper.encodeABI(fn_name="withdrawToChain", args=list(kwargs.values()))

        func = self.light_account.functions.executeBatch(
            dest=[pair.source_token.address, withdraw_wrapper.address],
            func=[approve_data, bridge_data],
        )

        tx = build_standard_transaction(func=func, account=self.account, w3=pair.source_w3, value=0)

        target_tx = TxResult(tx_hash="", tx_receipt=None, exception=None)
        source_tx = send_and_confirm_tx(w3=pair.source_w3, tx=tx, private_key=self.private_key, action="executeBatch()")
        tx_result = BridgeTxResult(
            source_chain=ChainID.DERIVE,
            target_chain=self.remote_chain_id,
            source_tx=source_tx,
            target_tx=target_tx,
        )
        if not source_tx.status == TxStatus.SUCCESS:
            return tx_result

        try:
            event = pair.source_token.events.OFTSent().process_log(source_tx.tx_receipt.logs[-1])
            guid = event["args"]["guid"]
        except Exception as e:
            msg = f"Failed to retrieve OFTSent log guid from source transaction receipt: {e}"
            source_tx.exception = ValueError(msg)
            return tx_result

        filter_params = make_filter_params(
            event=pair.target_token.events.OFTReceived(),
            from_block=from_block,
            argument_filters={"guid": guid},
        )

        try:
            event_log = wait_for_event(pair.target_w3, filter_params)
            target_tx.tx_hash = event_log["transactionHash"].to_0x_hex()
            target_tx.tx_receipt = wait_for_tx_receipt(w3=pair.target_w3, tx_hash=target_tx.tx_hash)
        except Exception as e:
            target_tx.exception = e

        return tx_result

    def _ensure_derive_eth_balance(self):
        """Ensure that the Derive EOA wallet has sufficient ETH balance for gas."""
        balance_of_owner = self.derive_w3.eth.get_balance(self.owner)
        if balance_of_owner < DEPOSIT_GAS_LIMIT:
            print(f"Funding Derive EOA wallet with {DEFAULT_GAS_FUNDING_AMOUNT} ETH")
            self.bridge_mainnet_eth_to_derive(DEFAULT_GAS_FUNDING_AMOUNT)

    def bridge_mainnet_eth_to_derive(self, amount: int) -> TxResult:
        """
        Prepares, signs, and sends a transaction to bridge ETH from mainnet to Derive.
        This is the "socket superbridge" method; not required when using the withdraw wrapper.
        """

        w3 = Web3(Web3.HTTPProvider(RPCEndPoints.ETH.value))

        address = self.config.contracts.L1_CHUG_SPLASH_PROXY
        bridge_abi = json.loads(L1_STANDARD_BRIDGE_ABI_PATH.read_text())
        proxy_contract = get_contract(w3=w3, address=address, abi=bridge_abi)

        tx = prepare_mainnet_to_derive_gas_tx(w3=w3, account=self.account, amount=amount, proxy_contract=proxy_contract)
        tx_result = send_and_confirm_tx(w3=w3, tx=tx, private_key=self.private_key, action="bridgeETH()")
        return tx_result

    def _prepare_new_style_deposit(self, token_data: NonMintableTokenData, amount: int) -> dict:
        vault_contract = _load_vault_contract(w3=self.remote_w3, token_data=token_data)
        connector = token_data.connectors[ChainID.DERIVE][TARGET_SPEED]
        fees = _get_min_fees(bridge_contract=vault_contract, connector=connector, token_data=token_data)
        func = vault_contract.functions.bridge(
            receiver_=self.wallet,
            amount_=amount,
            msgGasLimit_=MSG_GAS_LIMIT,
            connector_=connector,
            extraData_=b"",
            options_=b"",
        )
        return build_standard_transaction(func=func, account=self.account, w3=self.remote_w3, value=fees + 1)

    def _prepare_old_style_deposit(self, token_data: NonMintableTokenData, amount: int) -> dict:
        vault_contract = _load_vault_contract(w3=self.remote_w3, token_data=token_data)
        connector = token_data.connectors[ChainID.DERIVE][TARGET_SPEED]
        fees = _get_min_fees(bridge_contract=vault_contract, connector=connector, token_data=token_data)
        func = self.deposit_helper.functions.depositToLyra(
            token=token_data.NonMintableToken,
            socketVault=token_data.Vault,
            isSCW=True,
            amount=amount,
            gasLimit=MSG_GAS_LIMIT,
            connector=connector,
        )
        return build_standard_transaction(func=func, account=self.account, w3=self.remote_w3, value=fees + 1)

    def _check_bridge_funds(self, token_data, connector: Address, amount: int):
        controller = _load_controller_contract(w3=self.derive_w3, token_data=token_data)
        if token_data.isNewBridge:
            deposit_hook = controller.functions.hook__().call()
            expected_hook = token_data.LyraTSAShareHandlerDepositHook
            if not deposit_hook == token_data.LyraTSAShareHandlerDepositHook:
                msg = f"Controller deposit hook {deposit_hook} does not match expected address {expected_hook}"
                raise ValueError(msg)
            deposit_contract = _load_deposit_contract(w3=self.derive_w3, token_data=token_data)
            pool_id = deposit_contract.functions.connectorPoolIds(connector).call()
            locked = deposit_contract.functions.poolLockedAmounts(pool_id).call()
        else:
            pool_id = controller.functions.connectorPoolIds(connector).call()
            locked = controller.functions.poolLockedAmounts(pool_id).call()

        if amount > locked:
            raise RuntimeError(
                f"Insufficient funds locked in pool: has {locked}, want {amount} ({(locked / amount * 100):.2f}%)"
            )
