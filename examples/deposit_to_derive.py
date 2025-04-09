
# Rollup RPC Node
# Contract	Mainnet Address	Testnet Address
# RPC Endpoint	https://rpc.lyra.finance	<https://rpc-prod-testnet-0eakp60405.t.conduit.xyz>
# Block Explorer	https://explorer.lyra.finance	<https://explorer-prod-testnet-0eakp60405.t.conduit.xyz>

import os
import json
import time
import subprocess
from enum import IntEnum
from pathlib import Path
from typing import Callable
from dataclasses import dataclass

import requests
from web3 import Web3
from eth_account import Account
from tests.conftest import TEST_PRIVATE_KEY


Address = str
MAINNET = "ethereum"
BASE = "base"
MSG_GAS_LIMIT = 100_000


class ChainID(IntEnum):
    ETH = 1
    OPTIMISM = 10
    LYRA = 957
    BASE = 8453
    MODE = 34443
    ARBITRUM = 42161
    BLAST = 81457


@dataclass
class TokenData:
    isAppChain: bool
    NonMintableToken: Address
    Vault: Address
    LyraTSAShareHandlerDepositHook: Address
    connectors: dict[str, dict[str, str]]


# socket bridge on mainnet
SOCKET_BRIDGE_ADDRESS = Web3.to_checksum_address("0x6D303CEE7959f814042d31e0624fb88ec6fbcc1d")  


def get_repo_root() -> Path:
    return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip())


def fetch_json(url: str, cache_path: Path, post_processer: Callable = None):

    if cache_path.exists():
        return json.loads(cache_path.read_text())

    cache_path.parent.mkdir(exist_ok=True)
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    if post_processer:
        data = post_processer(data)
    cache_path.write_text(json.dumps(data, indent=4))

    return data


def fetch_prod_lyra_addresses(url: str = "https://raw.githubusercontent.com/0xdomrom/socket-plugs/refs/heads/main/deployments/superbridge/prod_lyra_addresses.json") -> list[dict]:
    """Fetch the chain data JSON from chainid.network."""

    cache_path = get_repo_root() / "data" / "prod_lyra_addresses.json"
    return fetch_json(url=url, cache_path=cache_path)


def fetch_abi(contract_address: str, etherscan_api_key: str):

    cache_path = get_repo_root() / "data" / "socket_bridge_abi.json"
    url = f"https://api.etherscan.io/api?module=contract&action=getabi&address={contract_address}&apikey={etherscan_api_key}"
    
    def response_processer(data):
        return json.loads(data["result"])

    return fetch_json(url, cache_path, post_processer=response_processer)



def wait_for_receipt(tx_hash, timeout=120, poll_interval=1):
    start_time = time.time()
    while True:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is not None:
            return receipt
        if time.time() - start_time > timeout:
            raise TimeoutError("Timed out waiting for transaction receipt.")
        time.sleep(poll_interval)


def increase_allowance(
    from_account: Account,
    erc20_contract,
    spender,
    amount_eth,
    private_key,
):
    value = w3.to_wei(amount_eth, "ether")
    func = erc20_contract.functions.approve(spender, value)
    nonce = w3.eth.get_transaction_count(from_account.address)
    tx = func.build_transaction(
        {
            "from": from_account.address,
            "nonce": nonce,
            "gas": MSG_GAS_LIMIT,
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=ethereum_private_key)

    try:
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print("Transaction hash:", tx_hash)
        tx_receipt = wait_for_receipt(tx_hash=tx_hash)
        print("Transaction receipt:", tx_receipt)
    except Exception as error:
        breakpoint()


def prepare_bridge_tx(
    from_account: Account,
    contract,           # The bridge contract instance (with depositToAppChain ABI)
    receiver: Address,  # The destination address on the App Chain (e.g. Lyra)
    amount_eth: float,  # Amount in ETH (human-readable)
    msg_gas_limit: int,
    connector: Address, # The connector address as per Derive's configuration
    w3: Web3
) -> dict:
    """
    Prepare a depositToAppChain transaction.

    Args:
        from_account: The account derived from the private key.
        contract: The Web3 contract instance for the socket bridge.
        receiver: Address on the app chain that will receive the deposit.
        amount_eth: The deposit amount expressed in ETH.
        msg_gas_limit: Gas limit to be used for the L2 message execution.
        connector: The connector address as required by the bridge function.
        web3: An instance of Web3 connected to the Base network RPC.

    Returns:
        A transaction dictionary ready to be signed and sent.
    """
    # Convert the deposit amount in ETH to Wei.
    deposit_value = w3.to_wei(amount_eth, "ether")
    
    # Retrieve the current transaction count (nonce) from the sender's account
    nonce = w3.eth.get_transaction_count(from_account.address)
    
    # Build the transaction
    func = contract.functions.depositToAppChain(
        w3.to_checksum_address(receiver),
        deposit_value,
        msg_gas_limit,
        w3.to_checksum_address(connector)
    )
    
    tx = func.build_transaction({
        "chainId": ChainID.BASE,
        "from": from_account.address,
        "nonce": nonce,
        "gas": msg_gas_limit,
        "gasPrice": w3.eth.gas_price,
        "value": deposit_value,
    })
    
    return tx


if (etherscan_api_key := os.environ.get("ETHERSCAN_API_KEY")) is None:
    raise ValueError("ETHERSCAN_API_KEY not found in env.")
if (dprc_api_key := os.environ.get("DRPC_API_KEY")) is None:
    raise ValueError("DRPC_API_KEY not found in environment variables.")
if (ethereum_private_key := os.environ.get("ETHEREUM_PRIVATE_KEY")) is None:
    raise ValueError("ETHEREUM_PRIVATE_KEY not found in environment variables.")


# get some data from mainnet
rpc_url = f"https://lb.drpc.org/ogrpc?network={MAINNET}&dkey={dprc_api_key}"
w3 = Web3(Web3.HTTPProvider(rpc_url))
if not w3.is_connected():
    raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")


account = Account.from_key(ethereum_private_key)
socket_bridge_abi = fetch_abi(SOCKET_BRIDGE_ADDRESS, etherscan_api_key)
bridge_contract = w3.eth.contract(address=SOCKET_BRIDGE_ADDRESS, abi=socket_bridge_abi)


# Example transaction of the bridging
tx_hash = "0x69272bbed41fd09f4b50bba6e0e451cc57a19fe81db41ac7819e003cb3088a00"
tx_data = w3.eth.get_transaction(tx_hash)
func_obj, func_params = bridge_contract.decode_function_input(tx_data['input'])

# Now bridge from BASE
rpc_url = f"https://lb.drpc.org/ogrpc?network={BASE}&dkey={dprc_api_key}"
w3 = Web3(Web3.HTTPProvider(rpc_url))
if not w3.is_connected():
    raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")


lyra_addresses = fetch_prod_lyra_addresses()
base_weETH = TokenData(**lyra_addresses[str(ChainID.BASE)]["weETH"])
connector = base_weETH.connectors[str(ChainID.LYRA)]["FAST"]


amount_eth = 0.001
receiver = base_weETH.Vault

# sanity checks
erc20_abi_path = get_repo_root() / "data" / "erc20.json"
erc20_abi = json.loads(erc20_abi_path.read_text())
weeth_contract = w3.eth.contract(address=Web3.to_checksum_address(base_weETH.NonMintableToken), abi=erc20_abi)
balance = weeth_contract.functions.balanceOf(account.address).call()
allowance = weeth_contract.functions.allowance(account.address, receiver).call()


if amount_eth > balance:
    raise ValueError(f"Not enough funds: {balance}, tried to send: {amount_eth}")

if amount_eth > allowance:
    print(f"Increasing allowance from {allowance} to {amount_eth}")
    increase_allowance(
        from_account=account, 
        erc20_contract=weeth_contract,
        spender=receiver,
        amount_eth=amount_eth,
        private_key=ethereum_private_key,
    )


tx = prepare_bridge_tx(
    from_account=account,
    contract=bridge_contract,
    receiver=receiver,
    amount_eth=amount_eth,
    msg_gas_limit=MSG_GAS_LIMIT,
    connector=connector,
    w3=w3,
)


try: 
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=ethereum_private_key)
    print(f"signed_tx: {signed_tx}")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"tx_hash: {tx_hash}")
    tx_receipt = wait_for_receipt(tx_hash=tx_hash)
    print(f"tx_receipt: {tx_receipt}")
except Exception as error:
    breakpoint()

