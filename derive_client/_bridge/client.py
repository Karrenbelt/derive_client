"""
Bridge client to deposit funds to the Derive smart contract funding account
"""

from __future__ import annotations

import functools
import json

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
    TARGET_SPEED,
    WITHDRAW_WRAPPER_V2_ABI_PATH,
)
from derive_client.data_types import (
    Address,
    BridgeTxResult,
    ChainID,
    Currency,
    DeriveTokenAddresses,
    Environment,
    LayerZeroChainIDv2,
    MintableTokenData,
    NonMintableTokenData,
    RPCEndPoints,
    TxResult,
    TxStatus,
)
from derive_client.utils import (
    build_standard_transaction,
    get_contract,
    get_erc20_contract,
    get_prod_derive_addresses,
    get_w3_connection,
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

    def deposit_drv(self, amount: int) -> TxResult:
        """
        Deposit funds by preparing, signing, and sending a bridging transaction.
        """

        chain_id = self.remote_chain_id
        spender = Web3.to_checksum_address(DeriveTokenAddresses[chain_id.name].value)
        if chain_id == ChainID.ETH:
            abi_path = DERIVE_ABI_PATH
        else:
            abi_path = DERIVE_L2_ABI_PATH

        abi = json.loads(abi_path.read_text())
        token_contract = get_contract(self.remote_w3, spender, abi=abi)

        ensure_balance(token_contract, self.owner, amount)
        ensure_allowance(
            w3=self.remote_w3,
            token_contract=token_contract,
            owner=self.owner,
            spender=spender,
            amount=amount,
            private_key=self.private_key,
        )

        receiver_bytes32 = Web3.to_bytes(hexstr=self.wallet).rjust(32, b"\x00")

        extra_options = b""  # extraOptions

        params = (
            LayerZeroChainIDv2.DERIVE.value,  # dstEid
            receiver_bytes32,  # receiver
            amount,  # amountLD
            0,  # minAmountLD
            extra_options,
            b"",  # composeMsg
            b"",  # oftCmd
        )
        extra_options = b"0x00030100110100000000000000000000000000000000"  # extraOptions
        send_params = (
            params[0],  # dstEid
            params[1],  # receiver
            params[2],  # amountLD
            params[3],  # minAmountLD
            params[4],  # extraOptions
            b"",  # composeMsg
            b"",  # oftCmd
        )
        fees = token_contract.functions.quoteSend(
            send_params,  # params, feeParams
            False,  # payInLzToken
        ).call()

        native_fee, lz_token_fee = fees
        _refundAddress = self.owner

        # fees = token_contract.functions.quoteOFT(
        #     send_params,  # params, feeParams
        #     # False,  # payInLzToken
        # ).call()
        # breakpoint()

        func = token_contract.functions.send(send_params, fees, _refundAddress)  # lzTokenFee

        tx = build_standard_transaction(func=func, account=self.account, w3=self.remote_w3, value=native_fee)

        tx_result = send_and_confirm_tx(w3=self.remote_w3, tx=tx, private_key=self.private_key, action="bridge()")
        return tx_result

    def deposit(
        self,
        amount: int,
        token_data: NonMintableTokenData | MintableTokenData,
    ) -> TxResult:
        """
        Deposit funds by preparing, signing, and sending a bridging transaction.
        """

        spender = token_data.Vault if token_data.isNewBridge else self.deposit_helper.address
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
            tx = self._prepare_new_style_deposit(token_data, amount, self.wallet)
        else:
            tx = self._prepare_old_style_deposit(token_data, amount)

        tx_result = send_and_confirm_tx(w3=self.remote_w3, tx=tx, private_key=self.private_key, action="bridge()")
        return tx_result

    def withdraw_drv(self, amount: int) -> BridgeTxResult:
        self._ensure_derive_eth_balance()

        from_block = self.remote_w3.eth.block_number  # record on target chain before tx submission on source chain

        abi = json.loads(DERIVE_L2_ABI_PATH.read_text())
        token_contract = get_contract(self.derive_w3, DeriveTokenAddresses.DERIVE.value, abi=abi)

        abi = json.loads(LYRA_OFT_WITHDRAW_WRAPPER_ABI_PATH.read_text())
        withdraw_wrapper = get_contract(self.derive_w3, LYRA_OFT_WITHDRAW_WRAPPER_ADDRESS, abi=abi)

        balance = token_contract.functions.balanceOf(self.wallet).call()
        if balance < amount:
            raise ValueError(f"Not enough tokens to withdraw: {amount} < {balance} ({(balance / amount * 100):.2f}%) ")

        destEID = LayerZeroChainIDv2[self.remote_chain_id.name]
        fee = withdraw_wrapper.functions.getFeeInToken(token_contract.address, amount, destEID).call()
        if amount < fee:
            raise ValueError(f"Withdraw amount < fee: {amount} < {fee} ({(fee / amount * 100):.2f}%)")

        kwargs = {
            "token": token_contract.address,
            "amount": amount,
            "toAddress": self.owner,
            "destEID": destEID,
        }

        approve_data = token_contract.encodeABI(fn_name="approve", args=[withdraw_wrapper.address, amount])
        bridge_data = withdraw_wrapper.encodeABI(fn_name="withdrawToChain", args=list(kwargs.values()))

        func = self.light_account.functions.executeBatch(
            dest=[token_contract.address, withdraw_wrapper.address],
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

        try:
            event = token_contract.events.OFTSent().process_log(source_tx.tx_receipt.logs[-1])
            guid = event["args"]["guid"]
        except Exception as e:
            msg = f"Failed to retrieve OFTSent log guid from source transaction receipt: {e}"
            source_tx.exception = ValueError(msg)
            return tx_result

        log_filter = token_contract.events.OFTReceived.create_filter(
            fromBlock=from_block, argument_filters={"guid": guid}
        )
        # This is hacky, we should instantiate and use target chain token_contract
        target_address = DeriveTokenAddresses[self.remote_chain_id.name].value
        log_filter.filter_params["address"] = Web3.to_checksum_address(target_address)

        try:
            event_log = wait_for_event(self.remote_w3, log_filter.filter_params)
            target_tx.tx_hash = event_log["transactionHash"].to_0x_hex()
            target_tx.tx_receipt = wait_for_tx_receipt(w3=self.remote_w3, tx_hash=target_tx.tx_hash)
        except Exception as e:
            target_tx.exception = e

        return tx_result

    def _ensure_derive_eth_balance(self):
        """Ensure that the Derive EOA wallet has sufficient ETH balance for gas."""
        balance_of_owner = self.derive_w3.eth.get_balance(self.owner)
        if balance_of_owner < DEPOSIT_GAS_LIMIT:
            print(f"Funding Derive EOA wallet with {DEFAULT_GAS_FUNDING_AMOUNT} ETH")
            self.bridge_mainnet_eth_to_derive(DEFAULT_GAS_FUNDING_AMOUNT)

    def withdraw_with_wrapper(self, amount: int, currency: Currency) -> TxResult:
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

        # Get the token contract and controller contract instances.
        controller = _load_controller_contract(w3=self.remote_w3, token_data=token_data)
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

        try:
            event = controller.events.BridgingTokens().process_log(source_tx.tx_receipt.logs[-1])
            message_id = event["args"]["messageId"]
        except Exception as e:
            msg = f"Failed to retrieve BridgeTokens log messageId from source transaction receipt: {e}"
            source_tx.exception = ValueError(msg)
            return tx_result

        token_data: NonMintableTokenData = self.derive_addresses.chains[self.remote_chain_id][currency]
        vault_contract = _load_vault_contract(self.remote_w3, token_data)
        event = vault_contract.events.TokensBridged()
        filter_params = event._get_event_filter_params(fromBlock=from_block, abi=event.abi)

        def matching_message_id(log: AttributeDict) -> bool:
            try:
                decoded = event.process_log(log)
                return decoded["args"].get("messageId") == message_id
            except Exception:
                return False

        try:
            event_log = wait_for_event(self.remote_w3, filter_params, condition=matching_message_id)
            target_tx.tx_hash = event_log["transactionHash"].to_0x_hex()
            target_tx.tx_receipt = wait_for_tx_receipt(w3=self.remote_w3, tx_hash=target_tx.tx_hash)
        except Exception as e:
            target_tx.exception = e

        return tx_result

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

    def _prepare_new_style_deposit(
        self,
        token_data: NonMintableTokenData,
        amount: int,
        receiver: Address,
    ) -> dict:
        vault_contract = _load_vault_contract(w3=self.remote_w3, token_data=token_data)
        connector = token_data.connectors[ChainID.DERIVE][TARGET_SPEED]
        fees = _get_min_fees(bridge_contract=vault_contract, connector=connector, token_data=token_data)
        func = vault_contract.functions.bridge(
            receiver_=receiver,
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
