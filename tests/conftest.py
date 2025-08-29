"""
Conftest for derive tests
"""

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
    Yields: dict with position info including subaccount_id, instrument_name, amount
    """
    # Get available subaccounts
    subaccounts = derive_client_2.fetch_subaccounts()
    print(f"Subaccounts: {subaccounts}")
    subaccount_ids = subaccounts['subaccount_ids']
    print(f"Subaccount IDs: {subaccount_ids}")

    if len(subaccount_ids) < 2:
        print("ERROR: Need at least 2 subaccounts for position transfer tests")
        return None

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]
    print(f"From subaccount: {from_subaccount_id}")
    print(f"To subaccount: {to_subaccount_id}")

    # Fetch available instruments dynamically instead of hardcoding
    instrument_name = None
    instruments = []

    # Try to fetch instruments for different currency types
    # currencies_to_try = [UnderlyingCurrency.BTC, UnderlyingCurrency.ETH, UnderlyingCurrency.USDC, UnderlyingCurrency.LBTC]
    currencies_to_try = [UnderlyingCurrency.ETH]

    for currency in currencies_to_try:
        try:
            instruments = derive_client_2.fetch_instruments(instrument_type=InstrumentType.PERP, currency=currency)
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

    test_amount = 100

    # Get current market data to place a reasonable order that will fill
    try:
        ticker = derive_client_2.fetch_ticker(instrument_name=instrument_name)
        print(f"Ticker data for {instrument_name}: {ticker}")

        # Get the best ask price to place a buy order that will fill immediately
        best_ask_price = float(ticker.get('best_ask_price', 0))
        best_bid_price = float(ticker.get('best_bid_price', 0))
        mark_price = float(ticker.get('mark_price', 0))

        if best_ask_price == 0:
            best_ask_price = 1

        print(f"Best ask price: {best_ask_price}, Best bid price: {best_bid_price}, Mark price: {mark_price}")

        # Use market order for immediate fill, or use a price that will definitely fill
        order_price = round(best_ask_price * 1.01, 1)  # 1% above best ask to ensure fill, rounded to 1 decimal place
        print(f"Using order price: {order_price} to ensure immediate fill")
    except Exception as e:
        print(f"Error getting ticker, using fallback price: {e}")
        order_price = 120000.0  # High price to ensure fill for BTC

    # Check existing positions first
    position_amount = 0
    try:
        position_amount = derive_client_2.get_position_amount(instrument_name, from_subaccount_id)
        print(f"Existing position amount: {position_amount}")
    except ValueError as e:
        print(f"No existing position found: {e}")
    except Exception as e:
        print(f"Error checking existing positions: {e}")

    # Create a position by placing and filling an order (only if no existing position)
    order_result = None
    if position_amount == 0:
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

        except DeriveJSONRPCException as e:
            if e.code == 11000:  # Insufficient funds error
                print(f"Expected error due to insufficient funds: {e}")
                print("This is normal for test accounts. Continuing with debug info...")
                position_amount = 0  # No position created
            else:
                print(f"Unexpected Derive RPC error: {e}")
                import traceback

                traceback.print_exc()
                return None
        except Exception as e:
            print(f"ERROR: Failed to create test position: {e}")
            import traceback

            traceback.print_exc()
            return None

    # Clean up any open orders before proceeding
    # if order_result and 'order_id' in order_result:
    #     try:
    #         derive_client_2.cancel(order_id=order_result['order_id'], instrument_name=instrument_name)
    #     except Exception:
    #         pass

    # Skip test if we don't have a position to transfer
    # if position_amount == 0:
    #     pytest.skip("No position created for transfer test - likely due to insufficient funds")

    # Return position information
    position_info = {
        'from_subaccount_id': from_subaccount_id,
        'to_subaccount_id': to_subaccount_id,
        'instrument_name': instrument_name,
        'position_amount': position_amount,
        'order_price': order_price,
        'mark_price': mark_price,
        'created_order': order_result,
    }

    return position_info
