"""
Example of bridging funds from a Derive smart contract funding account to BASE
"""

import os
import json
import contextvars

import click
from web3 import Web3
from dotenv import load_dotenv
from eth_account import Account
from web3.contract import Contract
from web3.gas_strategies.time_based import construct_time_based_gas_price_strategy

from derive_client.bridge.constants import TARGET_SPEED, MSG_GAS_LIMIT, DEPOSIT_GAS_LIMIT, PAYLOAD_SIZE
from derive_client.bridge.enums import ChainID, Currency, DRPCEndPoints, TxStatus
from derive_client.bridge.models import Address
from derive_client.derive import DeriveClient
from tests.conftest import Environment

from derive_client.bridge.utils import get_prod_lyra_addresses, get_w3_connection, get_contract, get_erc20_contract, get_repo_root, sign_and_send_tx, exp_backoff_retry, estimate_fees
from derive_client.bridge.transaction import get_min_fees, sign_and_send_tx, increase_allowance


CONTROLLER_ABI_PATH = get_repo_root() / "data" / "controller.json"
DEPOSIT_HOOK_ABI_PATH = get_repo_root() / "data" / "deposit_hook.json"
LIGHT_ACCOUNT_ABI_PATH = get_repo_root() / "data" / "light_account.json"
L1_CHUG_SPLASH_PROXY_ABI_PATH = get_repo_root() / "data" / "l1_chug_splash_proxy.json"
L1_STANDARD_BRIDGE_ABI_PATH = get_repo_root() / "data" / "l1_standard_bridge.json"
WITHDRAW_WRAPPER_V2 = get_repo_root() / "data" / "withdraw_wrapper_v2.json"


def check_allowance(
    token_contract: Contract,
    owner: Address,
    spender: Address,
):
    allowance = token_contract.functions.allowance(owner, spender).call()
    return allowance


def bridge_mainnet_eth_to_derive(
    account: Account,
    amount: int,
):
    w3_mainnet = Web3(Web3.HTTPProvider(DRPCEndPoints.ETH))
    if not w3_mainnet.is_connected():
        raise ConnectionError("Failed to connect to Ethereum mainnet RPC.")

    proxy_address = "0x61e44dc0dae6888b5a301887732217d5725b0bff"
    abi = json.loads(L1_CHUG_SPLASH_PROXY_ABI_PATH.read_text())
    proxy_contract = get_contract(w3=w3_mainnet, address=proxy_address, abi=abi)

    impl_address = proxy_contract.functions.getImplementation().call()
    bridge_abi = json.loads(L1_STANDARD_BRIDGE_ABI_PATH.read_text())
    bridge_contract = w3_mainnet.eth.contract(address=impl_address, abi=bridge_abi)

    eth_balance = w3_mainnet.eth.get_balance(account.address)
    nonce = w3_mainnet.eth.get_transaction_count(account.address)

    proxy_contract = get_contract(w3=w3_mainnet, address=proxy_address, abi=bridge_abi)

    @exp_backoff_retry
    def simulate_tx():
        fee_estimations = estimate_fees(w3_mainnet, blocks=10, percentiles=[99])
        max_fee = fee_estimations[0]['maxFeePerGas']
        priority_fee = fee_estimations[0]['maxPriorityFeePerGas']

        tx = proxy_contract.functions.bridgeETH(
            MSG_GAS_LIMIT,  # _minGasLimit # Optimism
            b"",            # _extraData
        ).build_transaction({
            "from": account.address,
            "value": amount,
            "nonce": nonce,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
            "chainId": ChainID.ETH,
        })
        estimated_gas = w3_mainnet.eth.estimate_gas(tx)
        tx["gas"] = estimated_gas
        required_cost = estimated_gas * max_fee + amount
        if eth_balance < required_cost:
            raise RuntimeError(f"Insufficient funds: need {required_cost}, have {eth_balance}")
        w3_mainnet.eth.call(tx)
        return tx

    tx = simulate_tx()
    tx_receipt = sign_and_send_tx(w3=w3_mainnet, tx=tx, private_key=account._private_key)

    if tx_receipt.status == TxStatus.SUCCESS:
        print("Deposit successful!")
    else:
        raise Exception("Deposit transaction reverted.")


def main():
    load_dotenv()

    if (private_key := os.environ.get("ETH_PRIVATE_KEY")) is None:
        raise ValueError("`ETH_PRIVATE_KEY` not found in env.")
    if (wallet := os.environ.get("WALLET")) is None:
        raise ValueError("`WALLET` not found in env.")

    client = DeriveClient(
        private_key=private_key,
        wallet=wallet,
        env=Environment.PROD,
    )

    account = Account.from_key(private_key)

    rpc_url = "https://rpc.lyra.finance"
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")

    currency = Currency.weETH
    chain_id = ChainID.BASE
    lyra_addresses = get_prod_lyra_addresses()

    token_data = lyra_addresses.chains[ChainID.LYRA][currency]
    connector = token_data.connectors[chain_id][TARGET_SPEED]

    controller = token_data.Controller
    deposit_hook = token_data.LyraTSAShareHandlerDepositHook
    mintable_token = token_data.MintableToken

    abi = json.loads(CONTROLLER_ABI_PATH.read_text())
    controller_contract = get_contract(w3=w3, address=controller, abi=abi)
    assert controller_contract.functions.hook__().call() == deposit_hook

    abi = json.loads(DEPOSIT_HOOK_ABI_PATH.read_text())
    deposit_contract = get_contract(w3=w3, address=deposit_hook, abi=abi)
    pool_id = deposit_contract.functions.connectorPoolIds(connector).call()
    locked_amount = deposit_contract.functions.poolLockedAmounts(pool_id).call()

    token_contract = get_erc20_contract(w3, mintable_token)
    eth_amount = 0.001
    amount = client.web3_client.to_wei(eth_amount, "ether")

    # check there are enough funds in the pool so the amount can be withdrawn
    if not locked_amount >= amount:
        raise RuntimeError(f"Insufficient funds locked in pool: has {locked_amount}, want {amount} ({(locked_amount/amount*100):.2f}%)")

    # check gas token reserve
    gas_eth_amount = 0.00005
    gas_amount = client.web3_client.to_wei(gas_eth_amount, "ether")
    eth_balance = w3.eth.get_balance(account.address)
    if eth_balance < gas_amount:
        print(f"Not enough native ETH to pay for gas, bridging from mainnet.")
        bridge_mainnet_eth_to_derive(account, amount=gas_amount)

    abi = json.loads(LIGHT_ACCOUNT_ABI_PATH.read_text())
    light_account = get_contract(w3=w3, address=wallet, abi=abi)

    ### WITHDRAW_WRAPPER
    fee = controller_contract.functions.getMinFees(connector_=connector, msgGasLimit_=MSG_GAS_LIMIT, payloadSize_=PAYLOAD_SIZE).call()
    if amount < fee:
        raise RuntimeError(f"Amount {amount} less than fee {fee} ({(amount/fee*100):.2f}%)")

    abi = json.loads(WITHDRAW_WRAPPER_V2.read_text())
    address = "0xea8E683D8C46ff05B871822a00461995F93df800"
    withdraw_wrapper = get_contract(w3=w3, address=address, abi=abi)

    kwargs = dict(
        token=token_contract.address,
        amount=amount,
        recipient=account.address,
        socketController=controller,
        connector=connector,
        gasLimit=MSG_GAS_LIMIT,
    )

    approve_data = token_contract.encodeABI(fn_name="approve", args=[withdraw_wrapper.address, amount])
    bridge_data = withdraw_wrapper.encodeABI(fn_name="withdrawToChain", args=list(kwargs.values()))
    func = light_account.functions.executeBatch(dest=[token_contract.address, withdraw_wrapper.address], func=[approve_data, bridge_data])

    token_balance = token_contract.functions.balanceOf(wallet).call()
    owner = light_account.functions.owner().call()
    nonce = w3.eth.get_transaction_count(owner)

    @exp_backoff_retry
    def simulate_tx():
        fee_estimations = estimate_fees(w3, blocks=100, percentiles=[99])
        max_fee = fee_estimations[0]['maxFeePerGas']
        priority_fee = fee_estimations[0]['maxPriorityFeePerGas']

        tx = func.build_transaction({
            "from": owner,
            "nonce": nonce,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
        })
        estimated_gas = w3.eth.estimate_gas(tx)
        tx["gas"] = estimated_gas
        required_cost = estimated_gas * max_fee + amount
        if token_balance < required_cost:
            raise RuntimeError(f"Insufficient token balance: have {token_balance}, need {required_cost} ({(token_balance/required_cost*100):.2f}%)")
        w3.eth.call(tx)
        return tx

    tx = simulate_tx()
    tx_receipt = sign_and_send_tx(w3=w3, tx=tx, private_key=private_key)
    if tx_receipt.status == TxStatus.SUCCESS:
        print(f"Bridge from Derive to {chain_id.name} successful!")
    else:
        raise Exception("Bridge transaction reverted.")


if __name__ == "__main__":
    main()
