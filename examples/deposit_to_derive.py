
# Rollup RPC Node
# Contract	Mainnet Address	Testnet Address
# RPC Endpoint	https://rpc.lyra.finance	<https://rpc-prod-testnet-0eakp60405.t.conduit.xyz>
# Block Explorer	https://explorer.lyra.finance	<https://explorer-prod-testnet-0eakp60405.t.conduit.xyz>
from __future__ import annotations

import os
import json
import time
import subprocess
from enum import IntEnum, StrEnum, auto
from pathlib import Path
from typing import Callable
from pydantic import BaseModel, ConfigDict, Field

import requests
from web3 import Web3
from web3.contract import Contract
from hexbytes import HexBytes
from eth_account import Account
from tests.conftest import TEST_PRIVATE_KEY


Address = str
MAINNET = "ethereum"
BASE = "base"
MSG_GAS_LIMIT = 100_000
TARGET_SPEED = "FAST"
DEPOSIT_GAS_LIMIT = 420_000
PAYLOAD_SIZE = 161


class TxStatus(IntEnum):
    FAILED = auto()
    SUCCESS = auto()


class ChainID(IntEnum):
    ETH = 1
    OPTIMISM = 10
    LYRA = 957
    BASE = 8453
    MODE = 34443
    ARBITRUM = 42161
    BLAST = 81457

    @classmethod
    def _missing_(cls, value):
        try:
            int_value = int(value)
            return next(member for member in cls if member == int_value)
        except (ValueError, TypeError, StopIteration):
            return super()._missing_(value)


class Currency(StrEnum):

    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]):
        return name

    weETH = auto()
    rswETH = auto()
    rsETH = auto()
    USDe = auto()
    deUSD = auto()
    PYUSD = auto()
    sUSDe = auto()
    SolvBTC = auto()
    SolvBTCBBN = auto()
    LBTC = auto()
    OP = auto()
    DAI = auto()
    sDAI = auto()
    cbBTC = auto()
    eBTC = auto()


class ExplorerBaseUrl(StrEnum):
    ETH = "https://api.etherscan.io/"
    BASE = "https://api.basescan.org/"


class TokenData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isAppChain: bool
    connectors: dict[ChainID, dict[str, str]]
    LyraTSAShareHandlerDepositHook: Address | None = None
    LyraTSADepositHook: Address | None = None


class MintableTokenData(TokenData):
    Controller: Address
    MintableToken: Address


class NonMintableTokenData(TokenData):
    Vault: Address
    NonMintableToken: Address


class LyraAddresses(BaseModel):
    chains: dict[ChainID, dict[Currency, MintableTokenData | NonMintableTokenData]]


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


def fetch_prod_lyra_addresses(url: str = "https://raw.githubusercontent.com/0xdomrom/socket-plugs/refs/heads/main/deployments/superbridge/prod_lyra_addresses.json") -> LyraAddresses:
    """Fetch the chain data JSON from chainid.network."""

    cache_path = get_repo_root() / "data" / "prod_lyra_addresses.json"

    return LyraAddresses(chains=fetch_json(url=url, cache_path=cache_path))


def fetch_abi(chain_id: ChainID, contract_address: str, apikey: str):

    cache_path = get_repo_root() / "data" / chain_id.name.lower() / f"{contract_address}.json"
    base_url = ExplorerBaseUrl[chain_id.name]
    url = f"{base_url}/api?module=contract&action=getabi&address={contract_address}&apikey={apikey}"

    def response_processer(data):
        return json.loads(data["result"])

    return fetch_json(url, cache_path, post_processer=response_processer)


def wait_for_receipt(tx_hash: str, timeout=120, poll_interval=1):
    start_time = time.time()
    while True:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception as error:
            receipt = None
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
        print("Transaction hash:", HexBytes(tx_hash))
        tx_receipt = wait_for_receipt(tx_hash=tx_hash)
        print("Transaction receipt:", tx_receipt)
    except Exception as error:
        raise error


def get_min_fees(bridge_contract, connector: Address) -> int:
    total_fees = bridge_contract.functions.getMinFees(
        connector_=Web3.to_checksum_address(connector),
        msgGasLimit_=MSG_GAS_LIMIT,
        payloadSize_=PAYLOAD_SIZE,
    ).call()
    return total_fees


def prepare_bridge_tx(
    w3: Web3,
    chain_id: ChainID,
    from_account: Account,
    contract: Contract,
    receiver: Address,
    amount_eth: float,
    msg_gas_limit: int,
    connector: Address,
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
    func = contract.functions.bridge(
        receiver_=w3.to_checksum_address(receiver),
        amount_=deposit_value,
        msgGasLimit_=msg_gas_limit,
        connector_=w3.to_checksum_address(connector),
        extraData_=b"",
        options_=b"",
    )
    fees = get_min_fees(contract, connector=connector)
    func.call({"from": from_account.address, "value": fees})

    tx = func.build_transaction({
        "chainId": chain_id,
        "from": from_account.address,
        "nonce": nonce,
        "gas": DEPOSIT_GAS_LIMIT,
        "gasPrice": w3.eth.gas_price,
        "value": fees + 1,
    })
    
    return tx


if (etherscan_api_key := os.environ.get("ETHERSCAN_API_KEY")) is None:
    raise ValueError("ETHERSCAN_API_KEY not found in env.")
if (basescan_api_key := os.environ.get("BASESCAN_API_KEY")) is None:
    raise ValueError("BASESCAN_API_KEY not found in env.")
if (dprc_api_key := os.environ.get("DRPC_API_KEY")) is None:
    raise ValueError("DRPC_API_KEY not found in environment variables.")
if (ethereum_private_key := os.environ.get("ETHEREUM_PRIVATE_KEY")) is None:
    raise ValueError("ETHEREUM_PRIVATE_KEY not found in environment variables.")
if (smart_contract_wallet_address := os.environ.get("DERIVE_SMART_CONTRACT_WALLET_ADDRESS")) is None:
    raise ValueError("DERIVE_SMART_CONTRACT_WALLET_ADDRESS not found in env.")


rpc_url = f"https://lb.drpc.org/ogrpc?network={BASE}&dkey={dprc_api_key}"
w3 = Web3(Web3.HTTPProvider(rpc_url))
if not w3.is_connected():
    raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")

chain_id = ChainID.BASE
account = Account.from_key(ethereum_private_key)

lyra_addresses = fetch_prod_lyra_addresses()
base_weETH = lyra_addresses.chains[chain_id][Currency.weETH]
connector = base_weETH.connectors[ChainID.LYRA][TARGET_SPEED]

socket_bridge_abi = fetch_abi(chain_id=chain_id, contract_address=base_weETH.Vault, apikey=basescan_api_key)
bridge_contract = w3.eth.contract(address=base_weETH.Vault, abi=socket_bridge_abi)

amount_eth = 0.001
spender = base_weETH.Vault
receiver = smart_contract_wallet_address

# sanity checks
erc20_abi_path = get_repo_root() / "data" / "erc20.json"
erc20_abi = json.loads(erc20_abi_path.read_text())
weeth_contract = w3.eth.contract(address=Web3.to_checksum_address(base_weETH.NonMintableToken), abi=erc20_abi)
balance = weeth_contract.functions.balanceOf(account.address).call()
allowance = weeth_contract.functions.allowance(account.address, spender).call()

if amount_eth > balance:
    raise ValueError(f"Not enough funds: {balance}, tried to send: {amount_eth}")

if amount_eth > allowance:
    print(f"Increasing allowance from {allowance} to {amount_eth}")
    increase_allowance(
        from_account=account, 
        erc20_contract=weeth_contract,
        spender=spender,
        amount_eth=amount_eth,
        private_key=ethereum_private_key,
    )


tx = prepare_bridge_tx(
    w3=w3,
    chain_id=chain_id,
    from_account=account,
    contract=bridge_contract,
    receiver=receiver,
    amount_eth=amount_eth,
    msg_gas_limit=MSG_GAS_LIMIT,
    connector=connector,
)

try:
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=ethereum_private_key)
    print(f"signed_tx: {signed_tx}")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"tx_hash: {HexBytes(tx_hash)}")
    tx_receipt = wait_for_receipt(tx_hash=tx_hash)
    print(f"tx_receipt: {tx_receipt}")
    if tx_receipt.status == TxStatus.SUCCESS:
        print(f"Successfully deposit to {smart_contract_wallet_address}")
        return
    raise Exception(f"Failed to deposit to {smart_contract_wallet_address}")
except Exception as error:
    raise error
