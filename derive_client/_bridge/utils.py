import functools
import json
import time

from web3 import Web3
from web3.contract import Contract
from web3.datastructures import AttributeDict

from derive_client._bridge.enums import ChainID, RPCEndPoints
from derive_client._bridge.models import LyraAddresses
from derive_client.constants import REPO_ROOT


def get_prod_lyra_addresses() -> LyraAddresses:
    """Fetch the socket superbridge JSON data."""
    prod_lyra_addresses = REPO_ROOT / "data" / "prod_lyra_addresses.json"
    return LyraAddresses(chains=json.loads(prod_lyra_addresses.read_text()))


def get_w3_connection(chain_id: ChainID) -> Web3:
    rpc_url = RPCEndPoints[chain_id.name]
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")
    return w3


def get_contract(w3: Web3, address: str, abi: list) -> Contract:
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


def get_erc20_contract(w3: Web3, token_address: str) -> Contract:
    erc20_abi_path = REPO_ROOT / "data" / "erc20.json"
    abi = json.loads(erc20_abi_path.read_text())
    return get_contract(w3=w3, address=token_address, abi=abi)


def wait_for_tx_receipt(w3: Web3, tx_hash: str, timeout=120, poll_interval=1) -> AttributeDict:
    start_time = time.time()
    while True:
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            receipt = None
        if receipt is not None:
            return receipt
        if time.time() - start_time > timeout:
            raise TimeoutError("Timed out waiting for transaction receipt.")
        time.sleep(poll_interval)


def sign_and_send_tx(w3: Web3, tx: dict, private_key: str) -> AttributeDict:
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
    print(f"signed_tx: {signed_tx}")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"tx_hash: 0x{tx_hash.hex()}")
    receipt = wait_for_tx_receipt(w3, tx_hash)
    print(f"tx_receipt: {receipt}")
    return receipt


def estimate_fees(w3, percentiles: list[int], blocks=20, default_tip=10_000):
    fee_history = w3.eth.fee_history(blocks, 'pending', percentiles)
    base_fees = fee_history['baseFeePerGas']
    rewards = fee_history['reward']

    # Calculate average priority fees for each percentile
    avg_priority_fees = []
    for i in range(len(percentiles)):
        nonzero_rewards = [r[i] for r in rewards if len(r) > i and r[i] > 0]
        if nonzero_rewards:
            estimated_tip = sum(nonzero_rewards) // len(nonzero_rewards)
        else:
            estimated_tip = default_tip
        avg_priority_fees.append(estimated_tip)

    # Use the latest base fee
    latest_base_fee = base_fees[-1]

    # Calculate max fees
    fee_estimations = []
    for priority_fee in avg_priority_fees:
        max_fee = latest_base_fee + priority_fee
        fee_estimations.append({'maxFeePerGas': max_fee, 'maxPriorityFeePerGas': priority_fee})

    return fee_estimations


def exp_backoff_retry(func=None, *, attempts=3, initial_delay=1, exceptions=(Exception,)):
    if func is None:
        return lambda f: exp_backoff_retry(f, attempts=attempts, initial_delay=initial_delay, exceptions=exceptions)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        delay = initial_delay
        for attempt in range(attempts):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                if attempt == attempts - 1:
                    raise
                print(f"Failed execution:\n{e}\nTrying again in {delay} seconds")
                time.sleep(delay)
                delay *= 2

    return wrapper
