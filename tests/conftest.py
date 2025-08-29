"""
Conftest for derive tests
"""

import time
from unittest.mock import MagicMock

import pytest

from derive_client.clients import AsyncClient
from derive_client.data_types import Environment, InstrumentType, OrderSide, OrderType, UnderlyingCurrency
from derive_client.derive import DeriveClient
from derive_client.exceptions import DeriveJSONRPCException
from derive_client.utils import get_logger

TEST_WALLET = "0x8772185a1516f0d61fC1c2524926BfC69F95d698"
TEST_PRIVATE_KEY = "0x2ae8be44db8a590d20bffbe3b6872df9b569147d3bf6801a35a28281a4816bbd"
SUBACCOUNT_ID = 30769


def freeze_time(derive_client):
    ts = 1705439697008
    nonce = 17054396970088651
    expiration = 1705439703008
    derive_client.get_nonce_and_signature_expiry = MagicMock(return_value=(ts, nonce, expiration))
    return derive_client


@pytest.fixture
def derive_client():
    derive_client = DeriveClient(
        wallet=TEST_WALLET, private_key=TEST_PRIVATE_KEY, env=Environment.TEST, logger=get_logger()
    )
    derive_client.subaccount_id = SUBACCOUNT_ID
    yield derive_client
    derive_client.cancel_all()


@pytest.fixture
async def derive_async_client():
    derive_client = AsyncClient(
        wallet=TEST_WALLET, private_key=TEST_PRIVATE_KEY, env=Environment.TEST, logger=get_logger()
    )
    derive_client.subaccount_id = SUBACCOUNT_ID
    yield derive_client
    await derive_client.cancel_all()


@pytest.fixture
def derive_client_2():
    # Exacted derive wallet address from the derive dashboard
    # NOTE: Because of importing the account through metamask mostlikely derive created a new wallet with the fowllowing address
    test_wallet = "0xA419f70C696a4b449a4A24F92e955D91482d44e9"
    test_private_key = TEST_PRIVATE_KEY

    derive_client = DeriveClient(
        wallet=test_wallet,
        private_key=test_private_key,
        env=Environment.TEST,
    )
    # Don't set subaccount_id here - let position_setup handle it dynamically
    yield derive_client
    derive_client.cancel_all()


@pytest.fixture
def position_setup(derive_client_2):
    """
    Create a position for transfer testing and return position details.
    Returns: dict with position info including subaccount_ids, instrument_name, position_amount, etc.
    """
    # Get available subaccounts
    subaccounts = derive_client_2.fetch_subaccounts()
    subaccount_ids = subaccounts.get("subaccount_ids", [])

    assert len(subaccount_ids) >= 2, "Need at least 2 subaccounts for position transfer tests"

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Find active instrument
    instrument_name = None
    instrument_type = None
    currency = None

    instrument_combinations = [
        (InstrumentType.PERP, UnderlyingCurrency.ETH),
        (InstrumentType.PERP, UnderlyingCurrency.BTC),
    ]

    for inst_type, curr in instrument_combinations:
        try:
            instruments = derive_client_2.fetch_instruments(instrument_type=inst_type, currency=curr, expired=False)
            active_instruments = [inst for inst in instruments if inst.get("is_active", True)]
            if active_instruments:
                instrument_name = active_instruments[0]["instrument_name"]
                instrument_type = inst_type
                currency = curr
                break
        except Exception:
            continue

    assert instrument_name is not None, "No active instruments found"

    test_amount = 10

    # Get market data for pricing
    ticker = derive_client_2.fetch_ticker(instrument_name)
    mark_price = float(ticker["mark_price"])
    trade_price = round(mark_price, 2)

    # Create matching buy/sell pair for guaranteed fill
    # Step 1: Create BUY order on target subaccount
    derive_client_2.subaccount_id = to_subaccount_id
    buy_order = derive_client_2.create_order(
        price=trade_price,
        amount=test_amount,
        instrument_name=instrument_name,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        instrument_type=instrument_type,
    )

    assert buy_order is not None, "Buy order should be created"
    assert "order_id" in buy_order, "Buy order should have order_id"

    time.sleep(1.0)  # Small delay

    # Step 2: Create matching SELL order on source subaccount
    derive_client_2.subaccount_id = from_subaccount_id
    sell_order = derive_client_2.create_order(
        price=trade_price,
        amount=test_amount,
        instrument_name=instrument_name,
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        instrument_type=instrument_type,
    )

    assert sell_order is not None, "Sell order should be created"
    assert "order_id" in sell_order, "Sell order should have order_id"

    time.sleep(2.0)  # Wait for trade execution

    # Verify position was created
    position_amount = derive_client_2.get_position_amount(instrument_name, from_subaccount_id)
    assert abs(position_amount) > 0, f"Position should be created, got {position_amount}"

    return {
        "from_subaccount_id": from_subaccount_id,
        "to_subaccount_id": to_subaccount_id,
        "instrument_name": instrument_name,
        "instrument_type": instrument_type,
        "currency": currency,
        "position_amount": position_amount,
        "trade_price": trade_price,
        "test_amount": test_amount,
        "buy_order": buy_order,
        "sell_order": sell_order,
    }
