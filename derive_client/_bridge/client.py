"""
Bridge client to deposit funds to the Derive smart contract funding account
"""

from __future__ import annotations

import json

from eth_account import Account
from web3 import Web3
from web3.contract import Contract

from derive_client._bridge.transaction import (
    ensure_allowance,
    ensure_balance,
    prepare_mainnet_to_derive_gas_tx,
    prepare_new_bridge_tx,
    prepare_old_bridge_tx,
    prepare_withdraw_wrapper_tx,
)
from derive_client.constants import (
    CONFIGS,
    CONTROLLER_ABI_PATH,
    CONTROLLER_V0_ABI_PATH,
    DEFAULT_GAS_FUNDING_AMOUNT,
    DEPOSIT_GAS_LIMIT,
    DEPOSIT_HELPER_ABI_PATH,
    DEPOSIT_HOOK_ABI_PATH,
    L1_STANDARD_BRIDGE_ABI_PATH,
    LIGHT_ACCOUNT_ABI_PATH,
    MSG_GAS_LIMIT,
    NEW_VAULT_ABI_PATH,
    OLD_VAULT_ABI_PATH,
    TARGET_SPEED,
    WITHDRAW_WRAPPER_V2_ABI_PATH,
)
from derive_client.data_types import (
    Address,
    ChainID,
    Environment,
    MintableTokenData,
    NonMintableTokenData,
    RPCEndPoints,
    TxResult,
)
from derive_client.utils import get_contract, get_erc20_contract, send_and_confirm_tx


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


class BridgeClient:
    def __init__(self, env: Environment, w3: Web3, account: Account):
        if not env == Environment.PROD:
            raise RuntimeError(f"Bridging is not supported in the {env.name} environment.")
        self.config = CONFIGS[env]
        self.w3 = w3
        self.account = account
        self.withdraw_wrapper_contract = self._load_withdraw_wrapper()
        self.deposit_helper = self._load_deposit_helper()

    def _load_deposit_helper(self) -> Contract:
        address = self.config.contracts.DEPOSIT_WRAPPER
        abi = json.loads(DEPOSIT_HELPER_ABI_PATH.read_text())
        return get_contract(w3=self.w3, address=address, abi=abi)

    def _load_withdraw_wrapper(self) -> Contract:
        address = self.config.contracts.WITHDRAW_WRAPPER_V2
        abi = json.loads(WITHDRAW_WRAPPER_V2_ABI_PATH.read_text())
        return get_contract(w3=self.w3, address=address, abi=abi)

    def deposit(
        self,
        amount: int,
        receiver: Address,
        token_data: NonMintableTokenData | MintableTokenData,
    ) -> TxResult:
        """
        Deposit funds by preparing, signing, and sending a bridging transaction.
        """

        connector = token_data.connectors[ChainID.DERIVE][TARGET_SPEED]
        vault_contract = _load_vault_contract(w3=self.w3, token_data=token_data)

        if token_data.isNewBridge:
            prepare_bridge_tx = prepare_new_bridge_tx
            spender = vault_contract.address
        else:
            prepare_bridge_tx = prepare_old_bridge_tx
            spender = self.deposit_helper.address

        token_contract = get_erc20_contract(self.w3, token_data.NonMintableToken)
        ensure_balance(token_contract, self.account.address, amount)
        ensure_allowance(
            w3=self.w3,
            token_contract=token_contract,
            owner=self.account.address,
            spender=spender,
            amount=amount,
            private_key=self.account._private_key,
        )

        tx = prepare_bridge_tx(
            w3=self.w3,
            account=self.account,
            vault_contract=vault_contract,
            receiver=receiver,
            amount=amount,
            msg_gas_limit=MSG_GAS_LIMIT,
            connector=connector,
            token_data=token_data,
            deposit_helper=self.deposit_helper,
        )

        tx_result = send_and_confirm_tx(w3=self.w3, tx=tx, private_key=self.account._private_key, action="bridge()")
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
        tx_result = send_and_confirm_tx(w3=w3, tx=tx, private_key=self.account._private_key, action="bridgeETH()")
        return tx_result

    def withdraw_with_wrapper(
        self,
        amount: int,
        receiver: Address,
        token_data: MintableTokenData,
        wallet: Address,
        private_key: str,
        target_chain: str,
    ) -> TxResult:
        """
        Checks if sufficent gas is available in derive, if not funds the wallet.
        Prepares, signs, and sends a withdrawal transaction using the withdraw wrapper.
        """

        derive_w3 = Web3(Web3.HTTPProvider(RPCEndPoints.DERIVE.value))
        balance_of_owner = derive_w3.eth.get_balance(self.account.address)
        if balance_of_owner < DEPOSIT_GAS_LIMIT:
            print(f"Funding Derive wallet with {DEFAULT_GAS_FUNDING_AMOUNT} ETH")
            self.bridge_mainnet_eth_to_derive(DEFAULT_GAS_FUNDING_AMOUNT)

        if not self.w3.eth.chain_id == ChainID.DERIVE:
            raise ValueError(
                f"Connected to chain ID {self.w3.eth.chain_id}, but expected Derive chain ({ChainID.DERIVE})."
            )

        connector = token_data.connectors[target_chain][TARGET_SPEED]

        # Get the token contract and Light Account contract instances.
        token_contract = get_erc20_contract(self.w3, token_data.MintableToken)
        controller = _load_controller_contract(w3=self.w3, token_data=token_data)
        light_account = _load_light_account(w3=self.w3, wallet=wallet)

        owner = light_account.functions.owner().call()
        if not receiver == owner:
            raise NotImplementedError(f"Withdraw to receiver {receiver} other than wallet owner {owner}")

        if token_data.isNewBridge:
            deposit_hook = controller.functions.hook__().call()
            if not deposit_hook == token_data.LyraTSAShareHandlerDepositHook:
                raise ValueError("Controller deposit hook does not match expected address")

            deposit_contract = _load_deposit_contract(w3=self.w3, token_data=token_data)
            pool_id = deposit_contract.functions.connectorPoolIds(connector).call()
            locked = deposit_contract.functions.poolLockedAmounts(pool_id).call()
        else:
            pool_id = controller.functions.connectorPoolIds(connector).call()
            locked = controller.functions.poolLockedAmounts(pool_id).call()

        if amount > locked:
            raise RuntimeError(
                f"Insufficient funds locked in pool: has {locked}, want {amount} ({(locked / amount * 100):.2f}%)"
            )

        tx = prepare_withdraw_wrapper_tx(
            w3=self.w3,
            account=self.account,
            wallet=wallet,
            receiver=receiver,
            token_contract=token_contract,
            withdraw_wrapper=self.withdraw_wrapper_contract,
            amount=amount,
            connector=connector,
            msg_gas_limit=MSG_GAS_LIMIT,
            is_new_bridge=token_data.isNewBridge,
            controller_contract=controller,
            light_account=light_account,
        )

        tx_result = send_and_confirm_tx(w3=self.w3, tx=tx, private_key=private_key, action="executeBatch()")
        return tx_result
