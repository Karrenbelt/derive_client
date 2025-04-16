"""
Bridge client to deposit funds to the Derive smart contract funding account
"""

from __future__ import annotations

import json

from eth_account import Account
from web3 import Web3
from web3.contract import Contract

from derive_client._bridge.transaction import (
    _prepare_mainnet_to_derive_tx,
    ensure_allowance,
    ensure_balance,
    prepare_bridge_tx,
    prepare_withdraw_wrapper_tx,
)
from derive_client.constants import ABI_DATA_DIR, MSG_GAS_LIMIT, TARGET_SPEED
from derive_client.custom_types import Address, ChainID, MintableTokenData, NonMintableTokenData, RPCEndPoints, TxStatus
from derive_client.utils import get_contract, get_erc20_contract, sign_and_send_tx

VAULT_ABI_PATH = ABI_DATA_DIR / "socket_superbridge_vault.json"
CONTROLLER_ABI_PATH = ABI_DATA_DIR / "controller.json"
DEPOSIT_HOOK_ABI_PATH = ABI_DATA_DIR / "deposit_hook.json"
LIGHT_ACCOUNT_ABI_PATH = ABI_DATA_DIR / "light_account.json"
L1_CHUG_SPLASH_PROXY_ABI_PATH = ABI_DATA_DIR / "l1_chug_splash_proxy.json"
L1_STANDARD_BRIDGE_ABI_PATH = ABI_DATA_DIR / "l1_standard_bridge.json"
WITHDRAW_WRAPPER_V2_ABI_PATH = ABI_DATA_DIR / "withdraw_wrapper_v2.json"


class BridgeClient:
    def __init__(self, w3: Web3, account: Account, chain_id: ChainID):
        self.w3 = w3
        self.account = account
        self.chain_id = chain_id
        self.bridge_contract: Contract | None = None
        self.withdraw_wrapper_contract: Contract | None = None

    def load_bridge_contract(self, vault_address: str) -> None:
        """Instantiate the bridge contract."""

        abi = json.loads(VAULT_ABI_PATH.read_text())
        address = self.w3.to_checksum_address(vault_address)
        self.bridge_contract = get_contract(w3=self.w3, address=address, abi=abi)

    def load_withdraw_wrapper(self):
        address = "0xea8E683D8C46ff05B871822a00461995F93df800"
        abi = json.loads(WITHDRAW_WRAPPER_V2_ABI_PATH.read_text())
        self.withdraw_wrapper_contract = get_contract(w3=self.w3, address=address, abi=abi)

    def deposit(
        self, amount: int, receiver: Address, connector: Address, token_data: NonMintableTokenData, private_key: str
    ):
        """
        Deposit funds by preparing, signing, and sending a bridging transaction.
        """

        token_contract = get_erc20_contract(self.w3, token_data.NonMintableToken)

        ensure_balance(token_contract, self.account.address, amount)
        ensure_allowance(self.w3, token_contract, self.account.address, token_data.Vault, amount, private_key)

        tx = prepare_bridge_tx(
            w3=self.w3,
            chain_id=self.chain_id,
            account=self.account,
            contract=self.bridge_contract,
            receiver=receiver,
            amount=amount,
            msg_gas_limit=MSG_GAS_LIMIT,
            connector=connector,
        )

        tx_receipt = sign_and_send_tx(self.w3, tx, private_key)
        if tx_receipt.status == TxStatus.SUCCESS:
            print("Deposit successful!")
            return tx_receipt
        else:
            raise Exception("Deposit transaction reverted.")

    def _bridge_mainnet_eth_to_derive(self, amount: int) -> dict:
        """
        Prepares, signs, and sends a transaction to bridge ETH from mainnet to Derive.
        This is the "socket superbridge" method; not required when using the withdraw wrapper.
        """

        w3 = Web3(Web3.HTTPProvider(RPCEndPoints.ETH))

        proxy_address = "0x61e44dc0dae6888b5a301887732217d5725b0bff"
        bridge_abi = json.loads(L1_STANDARD_BRIDGE_ABI_PATH.read_text())
        proxy_contract = get_contract(w3=w3, address=proxy_address, abi=bridge_abi)

        tx = _prepare_mainnet_to_derive_tx(w3=w3, account=self.account, amount=amount, proxy_contract=proxy_contract)
        tx_receipt = sign_and_send_tx(w3=w3, tx=tx, private_key=self.account._private_key)

        if tx_receipt.status == TxStatus.SUCCESS:
            print("Bridge deposit successful!")
            return tx_receipt
        else:
            raise Exception("Deposit transaction reverted.")

    def withdraw_with_wrapper(
        self,
        amount: int,
        receiver: Address,
        token_data: MintableTokenData,
        wallet: Address,
        private_key: str,
    ):
        """
        Prepares, signs, and sends a withdrawal transaction using the withdraw wrapper.
        """

        if not self.w3.eth.chain_id == ChainID.LYRA:
            raise ValueError(
                f"Connected to chain ID {self.w3.eth.chain_id}, but expected Derive chain ({ChainID.LYRA})."
            )

        connector = token_data.connectors[self.chain_id][TARGET_SPEED]

        # Get the token contract and Light Account contract instances.
        token_contract = get_erc20_contract(w3=self.w3, token_address=token_data.MintableToken)
        abi = json.loads(LIGHT_ACCOUNT_ABI_PATH.read_text())
        light_account = get_contract(w3=self.w3, address=wallet, abi=abi)

        abi = json.loads(CONTROLLER_ABI_PATH.read_text())
        controller_contract = get_contract(w3=self.w3, address=token_data.Controller, abi=abi)
        deposit_hook = controller_contract.functions.hook__().call()
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

        tx = prepare_withdraw_wrapper_tx(
            w3=self.w3,
            account=self.account,
            wallet=wallet,
            receiver=receiver,
            token_contract=token_contract,
            light_account=light_account,
            withdraw_wrapper=self.withdraw_wrapper_contract,
            controller_contract=controller_contract,
            amount=amount,
            connector=connector,
            msg_gas_limit=MSG_GAS_LIMIT,
        )

        tx_receipt = sign_and_send_tx(w3=self.w3, tx=tx, private_key=private_key)
        if tx_receipt.status == TxStatus.SUCCESS:
            print(f"Bridge from Derive to {self.chain_id.name} successful!")
            return tx_receipt
        else:
            raise Exception("Bridge transaction reverted.")
