from eth_account import Account
from web3 import Web3
from web3.contract import Contract

from derive_client.bridge.constants import DEPOSIT_GAS_LIMIT, MSG_GAS_LIMIT, PAYLOAD_SIZE
from derive_client.bridge.enums import TxStatus, ChainID
from derive_client.bridge.models import Address
from derive_client.bridge.utils import sign_and_send_tx, exp_backoff_retry


def ensure_balance(token_contract: Contract, owner: Address, amount: int):
    balance = token_contract.functions.balanceOf(owner).call()
    if amount > balance:
        raise ValueError(f"Not enough funds: {balance}, tried to send: {amount}")


def ensure_allowance(
    w3: Web3,
    token_contract: Contract,
    owner: Address,
    spender: Address,
    amount: int,
    private_key: str,
):
    allowance = token_contract.functions.allowance(owner, spender).call()
    if amount > allowance:
        print(f"Increasing allowance from {allowance} to {amount}")
        increase_allowance(
            w3=w3,
            from_account=Account.from_key(private_key),
            erc20_contract=token_contract,
            spender=spender,
            amount=amount,
            private_key=private_key,
        )


def increase_allowance(
    w3: Web3,
    from_account: Account,
    erc20_contract: Contract,
    spender: Address,
    amount: int,
    private_key: str,
) -> None:
    func = erc20_contract.functions.approve(spender, amount)
    nonce = w3.eth.get_transaction_count(from_account.address)
    tx = func.build_transaction(
        {
            "from": from_account.address,
            "nonce": nonce,
            "gas": MSG_GAS_LIMIT,
            "gasPrice": w3.eth.gas_price,
        }
    )

    try:
        tx_receipt = sign_and_send_tx(w3, tx=tx, private_key=private_key)
        if tx_receipt.status == TxStatus.SUCCESS:
            print("Transaction succeeded!")
        else:
            raise Exception("Transaction reverted.")
    except Exception as error:
        raise error


def get_min_fees(w3: Web3, bridge_contract: Contract, connector: str) -> int:
    """Get min fees"""

    total_fees = bridge_contract.functions.getMinFees(
        connector_=Web3.to_checksum_address(connector),
        msgGasLimit_=MSG_GAS_LIMIT,
        payloadSize_=PAYLOAD_SIZE,
    ).call()
    return total_fees


def prepare_bridge_tx(
    w3: Web3,
    chain_id: int,
    account: Account,
    contract: Contract,
    receiver: str,
    amount: int,
    msg_gas_limit: int,
    connector: str,
) -> dict:
    """Build the function call for 'bridge'"""

    func = contract.functions.bridge(
        receiver_=w3.to_checksum_address(receiver),
        amount_=amount,
        msgGasLimit_=msg_gas_limit,
        connector_=w3.to_checksum_address(connector),
        extraData_=b"",
        options_=b"",
    )

    fees = get_min_fees(w3=w3, bridge_contract=contract, connector=connector)
    func.call({"from": account.address, "value": fees})

    nonce = w3.eth.get_transaction_count(account.address)
    tx = func.build_transaction(
        {
            "chainId": chain_id,
            "from": account.address,
            "nonce": nonce,
            "gas": DEPOSIT_GAS_LIMIT,
            "gasPrice": w3.eth.gas_price,
            "value": fees + 1,
        }
    )

    return tx


def _prepare_mainnet_to_derive_tx(w3: Web3, account: Account, amount: int) -> dict:
    """
    Prepares a bridging transaction to move ETH from Ethereum mainnet to Derive.
    This function uses fee estimation and simulates the tx.
    """

    # This bridges ETH from EOA -> EOA, *not* to the smart contract funding wallet.
    # If the Derive-side recipient must be a smart contract, this must be changed.
    raise NotImplementedError(
        f"Bridging to a smart contract on Derive is not implemented. "
        f"This transaction will send ETH to {account.address} on Derive. "
        f"Implement contract recipient support before proceeding via `bridgeETHTo`."
    )

    if not w3.eth.chain_id == ChainID.ETH:
        raise ValueError(f"Connected to chain ID {w3.eth.chain_id}, but expected Ethereum mainnet ({ChainID.ETH}).")

    proxy_address = "0x61e44dc0dae6888b5a301887732217d5725b0bff"
    bridge_abi = json.loads(L1_STANDARD_BRIDGE_ABI_PATH.read_text())
    proxy_contract = get_contract(w3=w3, address=proxy_address, abi=bridge_abi)

    balance = w3.eth.get_balance(account.address)
    nonce = w3.eth.get_transaction_count(account.address)

    @exp_backoff_retry
    def simulate_tx():
        fee_estimations = estimate_fees(w3, blocks=10, percentiles=[99])
        max_fee = fee_estimations[0]['maxFeePerGas']
        priority_fee = fee_estimations[0]['maxPriorityFeePerGas']

        tx = proxy_contract.functions.bridgeETH(
            MSG_GAS_LIMIT,  # _minGasLimit # Optimism
            b"",  # _extraData
        ).build_transaction(
            {
                "from": account.address,
                "value": amount,
                "nonce": nonce,
                "maxFeePerGas": max_fee,
                "maxPriorityFeePerGas": priority_fee,
                "chainId": ChainID.ETH,
            }
        )
        estimated_gas = w3.eth.estimate_gas(tx)
        tx["gas"] = estimated_gas
        required = estimated_gas * max_fee + amount
        if balance < required:
            raise RuntimeError(f"Insufficient funds: have {balance}, need {required} ({(balance/required*100):.2f}%")
        w3.eth.call(tx)
        return tx

    return simulate_tx()
