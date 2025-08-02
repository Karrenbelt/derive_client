from logging import Logger

from eth_account import Account
from web3 import Web3
from web3.contract import Contract

from derive_client.constants import DEFAULT_GAS_FUNDING_AMOUNT, DEPOSIT_GAS_LIMIT, MSG_GAS_LIMIT
from derive_client.data_types import Address, ChainID, TxStatus
from derive_client.exceptions import InsufficientGas
from derive_client.utils import build_standard_transaction, estimate_fees, exp_backoff_retry, send_and_confirm_tx


def _check_gas_balance(w3: Web3, account: Address, gas_limit=DEPOSIT_GAS_LIMIT):
    """Check whether the account has sufficient gas balance."""
    balance = w3.eth.get_balance(account)
    if balance < gas_limit:
        raise InsufficientGas(
            f"Insufficient balance for gas: {gas_limit} < {balance} ({(balance / gas_limit * 100):.2f}%)"
        )


def ensure_balance(token_contract: Contract, owner: Address, amount: int):
    balance = token_contract.functions.balanceOf(owner).call()
    if amount > balance:
        raise ValueError(f"Not enough tokens to withdraw: {amount} < {balance} ({(balance / amount * 100):.2f}%)")


def ensure_allowance(
    w3: Web3,
    token_contract: Contract,
    owner: Address,
    spender: Address,
    amount: int,
    private_key: str,
    logger: Logger,
):
    allowance = token_contract.functions.allowance(owner, spender).call()
    if amount > allowance:
        logger.info(f"Increasing allowance from {allowance} to {amount}")
        increase_allowance(
            w3=w3,
            from_account=Account.from_key(private_key),
            erc20_contract=token_contract,
            spender=spender,
            amount=amount,
            private_key=private_key,
            logger=logger,
        )


def increase_allowance(
    w3: Web3,
    from_account: Account,
    erc20_contract: Contract,
    spender: Address,
    amount: int,
    private_key: str,
    logger: Logger,
) -> None:
    func = erc20_contract.functions.approve(spender, amount)
    tx = build_standard_transaction(func=func, account=from_account, w3=w3)
    tx_result = send_and_confirm_tx(w3=w3, tx=tx, private_key=private_key, action="approve()", logger=logger)
    if tx_result.status != TxStatus.SUCCESS:
        raise RuntimeError("approve() failed")


def prepare_mainnet_to_derive_gas_tx(
    w3: Web3,
    account: Account,
    proxy_contract: Contract,
    amount: int = DEFAULT_GAS_FUNDING_AMOUNT,
) -> dict:
    """
    Prepares a bridging transaction to move ETH from Ethereum mainnet to Derive.
    This function uses fee estimation and simulates the tx.
    """

    # This bridges ETH from EOA -> EOA, *not* to the smart contract funding wallet.
    # If the Derive-side recipient must be a smart contract, this must be changed.

    if not w3.eth.chain_id == ChainID.ETH:
        raise ValueError(f"Connected to chain ID {w3.eth.chain_id}, but expected Ethereum mainnet ({ChainID.ETH}).")

    balance = w3.eth.get_balance(account.address)
    nonce = w3.eth.get_transaction_count(account.address)

    @exp_backoff_retry
    def simulate_tx():
        fee_estimations = estimate_fees(w3, blocks=10, percentiles=[99])
        max_fee = fee_estimations[0]["maxFeePerGas"]
        priority_fee = fee_estimations[0]["maxPriorityFeePerGas"]

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
            raise RuntimeError(
                f"Insufficient funds: have {balance}, need {required} ({(balance / required * 100):.2f}%"
            )
        w3.eth.call(tx)
        return tx

    return simulate_tx()
