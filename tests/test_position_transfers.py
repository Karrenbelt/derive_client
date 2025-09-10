"""
Tests for position transfer functionality (transfer_position and transfer_positions methods).
"""

from decimal import Decimal

import pytest

from derive_client.data_types import (
    DeriveTxResult,
    DeriveTxStatus,
    InstrumentType,
    OrderSide,
    OrderType,
    TimeInForce,
    UnderlyingCurrency,
)
from derive_client.utils import wait_until


def is_settled(res: DeriveTxResult) -> bool:
    return res.status is DeriveTxStatus.SETTLED


def get_all_positions(derive_client):

    _subaccount_id = derive_client.subaccount_id

    def is_zero(position):
        return position["amount"] == "0"

    positions = {}
    for subaccount_id in derive_client.subaccount_ids:
        derive_client.subaccount_id = subaccount_id
        positions[subaccount_id] = list(filter(lambda p: not is_zero(p), derive_client.get_positions()))

    derive_client.subaccount_id = _subaccount_id
    return positions


def close_all_positions(derive_client):

    _subaccount_id = derive_client.subaccount_id
    all_positions = get_all_positions(derive_client)
    for subaccount_id, positions in all_positions.items():
        derive_client.subaccount_id = subaccount_id  # this is nasty
        for position in positions:
            amount = float(position["amount"])

            side = OrderSide.SELL if amount > 0 else OrderSide.BUY
            ticker = derive_client.fetch_ticker(instrument_name=position["instrument_name"])
            price = ticker["best_ask_price"] if amount < 0 else ticker["best_bid_price"]
            price = float(Decimal(price).quantize(Decimal(ticker["tick_size"])))
            amount = abs(amount)

            derive_client.create_order(
                price=price,
                amount=amount,
                instrument_name=position["instrument_name"],
                reduce_only=True,
                instrument_type=InstrumentType(position["instrument_type"]),
                side=side,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.FOK,
            )

    derive_client.subaccount_id = _subaccount_id


@pytest.fixture
def client_with_position(request, derive_client):
    """Setup position for transfer"""

    currency, instrument_type, side = request.param

    assert len(derive_client.subaccount_ids) >= 2, "Need at least 2 subaccounts for position transfer tests"

    close_all_positions(derive_client)

    positions = get_all_positions(derive_client)
    if any(positions.values()):
        raise ValueError(f"Pre-existing positions found: {positions}")

    instrument_name = f"{currency.name}-{instrument_type.name}"

    ticker = derive_client.fetch_ticker(instrument_name)
    if not ticker["is_active"]:
        raise RuntimeError(f"Instrument ticker status inactive: {instrument_name}: {ticker}")

    min_amount = float(ticker["minimum_amount"])
    best_price = ticker["best_ask_price"] if side == OrderSide.BUY else ticker["best_bid_price"]

    # Derive RPC 11013: Limit price X must not have more than Y decimal places
    price = float(Decimal(best_price).quantize(Decimal(ticker["tick_size"])))

    collaterals = derive_client.get_collaterals()
    assert len(collaterals) == 1, "Account collaterals assumption violated"

    collateral = collaterals.pop()
    if float(collateral["mark_value"]) < min_amount * price:
        msg = (
            f"Cannot afford minimum position size.\n"
            f"Minimum: {min_amount}, Price: {price}, Total cost: {min_amount * price}\n"
            f"Collateral market value: {collateral['mark_value']}"
        )
        raise ValueError(msg)

    derive_client.create_order(
        price=price,
        amount=min_amount,
        instrument_name=instrument_name,
        side=side,
        order_type=OrderType.MARKET,
        instrument_type=instrument_type,
    )

    yield derive_client

    close_all_positions(derive_client)
    remaining_positions = get_all_positions(derive_client)
    if any(remaining_positions.values()):
        raise ValueError(f"Post-existing positions found: {remaining_positions}")


@pytest.mark.parametrize(
    "client_with_position",
    [
        (UnderlyingCurrency.ETH, InstrumentType.PERP, OrderSide.BUY),
        (UnderlyingCurrency.ETH, InstrumentType.PERP, OrderSide.SELL),
    ],
    indirect=True,
    ids=["eth-perp-buy", "eth-perp-sell"],
)
def test_single_position_transfer(client_with_position):
    """Test single position transfer using transfer_position method"""

    derive_client = client_with_position
    source_subaccount_id = derive_client.subaccount_ids[0]
    target_subaccount_id = derive_client.subaccount_ids[1]
    assert derive_client.subaccount_id == source_subaccount_id

    initial_positions = get_all_positions(derive_client)

    if len(source_positions := initial_positions[source_subaccount_id]) != 1:
        raise ValueError(f"Expected one open position on source, found: {source_positions}")
    if target_positions := initial_positions[target_subaccount_id]:
        raise ValueError(f"Expected zero open position on target, found: {target_positions}")

    initial_position = source_positions[0]
    amount = float(initial_position["amount"])
    instrument_name = initial_position["instrument_name"]
    position_transfer = derive_client.transfer_position(
        instrument_name=instrument_name,
        amount=amount,
        to_subaccount_id=target_subaccount_id,
    )

    assert position_transfer.maker_trade.transaction_id == position_transfer.taker_trade.transaction_id

    derive_tx_result = wait_until(
        derive_client.get_transaction,
        condition=is_settled,
        transaction_id=position_transfer.maker_trade.transaction_id,
    )

    assert derive_tx_result.status == DeriveTxStatus.SETTLED

    action_data = derive_tx_result.data["action_data"]
    assert position_transfer.taker_trade.subaccount_id == action_data["taker_account"]
    assert position_transfer.maker_trade.subaccount_id == action_data["fill_details"][0]["filled_account"]

    final_positions = get_all_positions(derive_client)
    assert len(final_positions[source_subaccount_id]) == 0
    assert len(final_positions[target_subaccount_id]) == 1

    final_position = final_positions[target_subaccount_id][0]
    assert final_position["instrument_name"] == initial_position["instrument_name"]
    assert final_position["amount"] == initial_position["amount"]
