import json
import time

from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract
from web3.datastructures import AttributeDict

from derive_client.constants import ABI_DATA_DIR
from derive_client.data_types import ChainID, RPCEndPoints, TxResult, TxStatus


def get_w3_connection(chain_id: ChainID) -> Web3:
    rpc_url = RPCEndPoints[chain_id.name].value
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to RPC at {rpc_url}")
    return w3


def get_contract(w3: Web3, address: str, abi: list) -> Contract:
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)


def get_erc20_contract(w3: Web3, token_address: str) -> Contract:
    erc20_abi_path = ABI_DATA_DIR / "erc20.json"
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


def sign_and_send_tx(w3: Web3, tx: dict, private_key: str) -> HexBytes:
    signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
    print(f"signed_tx: {signed_tx}")
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"tx_hash: 0x{tx_hash.hex()}")
    return tx_hash


def send_and_confirm_tx(
    w3: Web3,
    tx: dict,
    private_key: str,
    *,
    action: str,  # e.g. "approve()", "deposit()", "withdraw()"
) -> TxResult:
    tx_result = TxResult(tx_hash="", tx_receipt=None, exception=None)

    try:
        tx_hash = sign_and_send_tx(w3=w3, tx=tx, private_key=private_key)
        tx_result.tx_hash = tx_hash.hex()
    except Exception as send_err:
        print(f"❌ Failed to send tx for {action}, error: {send_err!r}")
        tx_result.exception = send_err
        return tx_result

    try:
        tx_receipt = wait_for_tx_receipt(w3=w3, tx_hash=tx_hash)
        tx_result.tx_receipt = tx_receipt
    except TimeoutError as timeout_err:
        print(f"⏱️  Timeout waiting for tx receipt of {tx_hash.hex()}")
        tx_result.exception = timeout_err
        return tx_result
    except Exception as wait_err:
        print(f"⚠️  Error while waiting for tx receipt of {tx_hash.hex()}: {wait_err!r}")
        tx_result.exception = wait_err
        return tx_result

    if tx_receipt.status == TxStatus.SUCCESS:
        print(f"✅ {action} succeeded for tx {tx_hash.hex()}")
    else:
        print(f"❌ {action} reverted for tx {tx_hash.hex()}")

    return tx_result


def estimate_fees(w3, percentiles: list[int], blocks=20, default_tip=10_000):
    fee_history = w3.eth.fee_history(blocks, "pending", percentiles)
    base_fees = fee_history["baseFeePerGas"]
    rewards = fee_history["reward"]

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
        fee_estimations.append({"maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority_fee})

    return fee_estimations
