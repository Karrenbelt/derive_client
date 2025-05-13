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


class BridgeClient:
    def __init__(self, env: Environment, w3: Web3, account: Account, chain_id: ChainID):
        if not env == Environment.PROD:
            raise RuntimeError(f"Bridging is not supported in the {env.name} environment.")
        self.config = CONFIGS[env]
        self.w3 = w3
        self.account = account
        self.chain_id = chain_id
        self.bridge_contract: Contract | None = None
        self.withdraw_wrapper_contract: Contract | None = None
        self.controller: Contract | None = None

    def load_bridge_contract(self, vault_address: str, is_new_bridge: bool) -> None:
        """Instantiate the bridge contract."""

        path = NEW_VAULT_ABI_PATH if is_new_bridge else OLD_VAULT_ABI_PATH
        abi = json.loads(path.read_text())
        address = self.w3.to_checksum_address(vault_address)
        self.bridge_contract = get_contract(w3=self.w3, address=address, abi=abi)

    def load_withdraw_wrapper(self):
        address = self.config.contracts.WITHDRAW_WRAPPER_V2
        abi = json.loads(WITHDRAW_WRAPPER_V2_ABI_PATH.read_text())
        self.withdraw_wrapper_contract = get_contract(w3=self.w3, address=address, abi=abi)

    def load_deposit_helper(self):
        address = self.config.contracts.DEPOSIT_WRAPPER
        abi = json.loads(DEPOSIT_HELPER_ABI_PATH.read_text())
        self.deposit_helper = get_contract(w3=self.w3, address=address, abi=abi)

    def load_controller(self, token_data: NonMintableTokenData | MintableTokenData) -> Contract:
        """Instantiate the controller contract."""

        if token_data.isNewBridge:
            path = CONTROLLER_ABI_PATH
        else:
            path = CONTROLLER_V0_ABI_PATH

        abi = json.loads(path.read_text())
        address = self.w3.to_checksum_address(token_data.Controller)
        self.controller = get_contract(w3=self.w3, address=address, abi=abi)

    def deposit(
        self, amount: int, receiver: Address, connector: Address, token_data: NonMintableTokenData | MintableTokenData
    ) -> TxResult:
        """
        Deposit funds by preparing, signing, and sending a bridging transaction.
        """

        if token_data.isNewBridge:
            spender = token_data.Vault
            prepare_bridge_tx = prepare_new_bridge_tx
        else:
            spender = self.bridge_contract.address
            prepare_bridge_tx = prepare_old_bridge_tx

        token_contract = get_erc20_contract(self.w3, token_data.NonMintableToken)
        ensure_balance(token_contract, self.account.address, amount)
        ensure_allowance(self.w3, token_contract, self.account.address, spender, amount, self.account._private_key)

        tx = prepare_bridge_tx(
            w3=self.w3,
            chain_id=self.chain_id,
            account=self.account,
            contract=self.bridge_contract,
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

        connector = token_data.connectors[self.chain_id][TARGET_SPEED]

        # Get the token contract and Light Account contract instances.
        token_contract = get_erc20_contract(w3=self.w3, token_address=token_data.MintableToken)
        abi = json.loads(LIGHT_ACCOUNT_ABI_PATH.read_text())
        light_account = get_contract(w3=self.w3, address=wallet, abi=abi)

        self.load_controller(token_data=token_data)

        if token_data.isNewBridge:
            deposit_hook = self.controller.functions.hook__().call()
            if not deposit_hook == token_data.LyraTSAShareHandlerDepositHook:
                raise ValueError("Controller deposit hook does not match expected address")

            abi = json.loads(DEPOSIT_HOOK_ABI_PATH.read_text())
            deposit_contract = get_contract(w3=self.w3, address=deposit_hook, abi=abi)
            pool_id = deposit_contract.functions.connectorPoolIds(connector).call()
            locked = deposit_contract.functions.poolLockedAmounts(pool_id).call()

            if amount > locked:
                raise RuntimeError(
                    f"Insufficient funds locked in pool: has {locked}, want {amount} ({(locked/amount*100):.2f}%)"
                )

            owner = light_account.functions.owner().call()
            if not receiver == owner:
                raise NotImplementedError("Withdraw to receiver other than wallet owner")
        else:
            # figure out how to check balances on the old bridge.
            print("Old bridge not checking balances")
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
            controller_contract=self.controller,
            light_account=light_account,
        )

        tx_result = send_and_confirm_tx(w3=self.w3, tx=tx, private_key=private_key, action="executeBatch()")
        return tx_result
