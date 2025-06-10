from eth_account import Account
from web3 import Web3
from web3.contract import Contract

from derive_client.constants import DEFAULT_GAS_FUNDING_AMOUNT, MSG_GAS_LIMIT
from derive_client.data_types import Address, ChainID, MintableTokenData, NonMintableTokenData, TxStatus
from derive_client.utils import build_standard_transaction, estimate_fees, exp_backoff_retry, send_and_confirm_tx


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
    tx = build_standard_transaction(func=func, account=from_account, w3=w3)
    tx_result = send_and_confirm_tx(w3=w3, tx=tx, private_key=private_key, action="approve()")
    if tx_result.status != TxStatus.SUCCESS:
        raise RuntimeError("approve() failed")


def prepare_new_bridge_tx(
    w3: Web3,
    account: Account,
    vault_contract: Contract,
    receiver: str,
    amount: int,
    msg_gas_limit: int,
    connector: str,
    fees: int,
    **kwargs,
) -> dict:
    """Build the function call for 'bridge'"""

    func = vault_contract.functions.bridge(
        receiver_=w3.to_checksum_address(receiver),
        amount_=amount,
        msgGasLimit_=msg_gas_limit,
        connector_=w3.to_checksum_address(connector),
        extraData_=b"",
        options_=b"",
    )

    return build_standard_transaction(func=func, account=account, w3=w3, value=fees + 1)


def prepare_old_bridge_tx(
    w3: Web3,
    account: Account,
    vault_contract: Contract,
    amount: int,
    msg_gas_limit: int,
    token_data: NonMintableTokenData | MintableTokenData,
    connector: str,
    deposit_helper: Contract,
    fees: int,
    **kwargs,
) -> dict:
    """Build the function call for 'bridge'"""

    func = deposit_helper.functions.depositToLyra(
        token=w3.to_checksum_address(token_data.NonMintableToken),
        socketVault=w3.to_checksum_address(token_data.Vault),
        isSCW=True,
        amount=amount,
        gasLimit=msg_gas_limit,
        connector=w3.to_checksum_address(connector),
    )

    return build_standard_transaction(func=func, account=account, w3=w3, value=fees + 1)


def prepare_withdraw_wrapper_tx(
    w3: Web3,
    account: Account,
    wallet: Address,
    receiver: str,
    token_contract: Contract,
    light_account: Contract,
    withdraw_wrapper: Contract,
    controller_contract: Contract,
    amount: int,
    connector: str,
    msg_gas_limit: int = MSG_GAS_LIMIT,
    is_new_bridge: bool = True,
) -> dict:
    """
    Prepares a withdrawal transaction using the withdraw wrapper on Derive.
    This function builds and simulates a transaction that calls `withdrawToChain`
    via a batch execution on the provided Light Account.
    """

    kwargs = {
        "token": token_contract.address,
        "amount": amount,
        "recipient": receiver,
        "socketController": controller_contract.address,
        "connector": connector,
        "gasLimit": msg_gas_limit,
    }

    # Encode the token approval and withdrawToChain for the withdraw wrapper.
    approve_data = token_contract.encodeABI(fn_name="approve", args=[withdraw_wrapper.address, amount])
    bridge_data = withdraw_wrapper.encodeABI(fn_name="withdrawToChain", args=list(kwargs.values()))

    # Build the batch execution call via the Light Account.
    func = light_account.functions.executeBatch(
        dest=[token_contract.address, withdraw_wrapper.address],
        func=[approve_data, bridge_data],
    )

    return build_standard_transaction(func=func, account=account, w3=w3, value=0)


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
