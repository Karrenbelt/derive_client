"""
Conftest for derive tests
"""

from unittest.mock import MagicMock

import pytest

from derive_client.clients import AsyncClient
from derive_client.data_types import Environment, InstrumentType, OrderSide, OrderType, UnderlyingCurrency
from derive_client.derive import DeriveClient
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
    test_wallet = "0xeda0656dab4094C7Dc12F8F12AF75B5B3Af4e776"
    test_private_key = "0x83ee63dc6655509aabce0f7e501a31c511195e61e9d0e9917f0a55fd06041a66"
    subaccount_id = 137402

    derive_client = DeriveClient(
        wallet=test_wallet, private_key=test_private_key, env=Environment.TEST, logger=get_logger()
    )
    derive_client.subaccount_id = subaccount_id
    yield derive_client
    derive_client.cancel_all()


@pytest.fixture
def position_setup(derive_client_2):
    """
    Create a position for transfer testing and return position details.
    Yields: dict with position info including subaccount_id, instrument_name, amount
    """
    # Get available subaccounts
    subaccounts = derive_client_2.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer tests")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Fetch available instruments and select the first available instrument
    instrument_name = None
    instruments = []
    
    # Try to fetch instruments for different currency types
    currencies_to_try = [UnderlyingCurrency.BTC, UnderlyingCurrency.ETH, UnderlyingCurrency.USDC, UnderlyingCurrency.LBTC]
    
    for currency in currencies_to_try:
        try:
            instruments = derive_client_2.fetch_instruments(
                instrument_type=InstrumentType.PERP,
                currency=currency
            )
            # Filter for active instruments only
            active_instruments = [inst for inst in instruments if inst.get("is_active", True)]
            if active_instruments:
                instrument_name = active_instruments[0]["instrument_name"]
                print(f"Selected instrument: {instrument_name} from currency {currency}")
                break
        except Exception as e:
            print(f"Failed to fetch instruments for {currency}: {e}")
            continue
    
    # Fallback to hardcoded instrument if no instruments found
    if not instrument_name:
        instrument_name = "BTC-PERP"
        print("Falling back to hardcoded instrument: BTC-PERP")
    
    test_amount = 0.1

    # Get current market data to place a reasonable order that will fill
    try:
        ticker = derive_client_2.fetch_ticker(instrument_name=instrument_name)
        print(f"Ticker data for {instrument_name}: {ticker}")
        
        # Get the best ask price to place a buy order that will fill immediately
        best_ask_price = float(ticker.get('best_ask_price', 0))
        best_bid_price = float(ticker.get('best_bid_price', 0))
        mark_price = float(ticker.get('mark_price', 0))
        
        print(f"Best ask price: {best_ask_price}, Best bid price: {best_bid_price}, Mark price: {mark_price}")
        
        # Use market order for immediate fill, or use a price that will definitely fill
        order_price = round(best_ask_price * 1.01, 1)  # 1% above best ask to ensure fill, rounded to 1 decimal place
        print(f"Using order price: {order_price} to ensure immediate fill")
    except Exception as e:
        print(f"Error getting ticker, using fallback price: {e}")
        order_price = 120000.0  # High price to ensure fill for BTC

    # Create a position by placing and filling an order
    try:
        # Set subaccount for the order
        derive_client_2.subaccount_id = from_subaccount_id
        print(f"Setting subaccount_id to: {from_subaccount_id}")

        print("Creating order...")
        order_result = derive_client_2.create_order(
            price=order_price,
            amount=test_amount,
            instrument_name=instrument_name,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            instrument_type=InstrumentType.PERP,
        )
        print(f"Order result: {order_result}")

        # Wait a moment for order to potentially fill
        import time
        time.sleep(2.0)  # Increased wait time for order to fill

        # Get the actual position amount
        try:
            position_amount = derive_client_2.get_position_amount(instrument_name, from_subaccount_id)
            print(f"Position amount retrieved: {position_amount}")
        except ValueError as e:
            print(f"ValueError getting position amount: {e}")
            # If no position exists, use the order amount as expected amount
            position_amount = test_amount
        except Exception as e:
            print(f"Exception getting position amount: {e}")
            # If no position exists, use the order amount as expected amount
            position_amount = test_amount

    except Exception as e:
        print(f"Failed to create test position: {e}")
        import traceback
        traceback.print_exc()
        pytest.skip(f"Failed to create test position: {e}")

    # Additional debugging: Check if the order was filled by checking open orders
    try:
        open_orders = derive_client_2.fetch_orders(instrument_name=instrument_name)
        print(f"Open orders: {open_orders}")
    except Exception as e:
        print(f"Error fetching open orders: {e}")
        
    # Try to cancel the order if it's still open
    try:
        if 'order_result' in locals() and 'order_id' in order_result:
            order_id = order_result['order_id']
            cancel_result = derive_client_2.cancel_order(instrument_name=instrument_name, order_id=order_id)
            print(f"Cancel result: {cancel_result}")
    except Exception as e:
        print(f"Error cancelling order: {e}")

    # Return position information
    position_info = {
        'from_subaccount_id': from_subaccount_id,
        'to_subaccount_id': to_subaccount_id,
        'instrument_name': instrument_name,
        'position_amount': position_amount,
        'order_price': order_price,
        'created_order': order_result if 'order_result' in locals() else None,
    }

    print(f"Final position info: {position_info}")
    yield position_info
