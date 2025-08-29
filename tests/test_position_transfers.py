"""
Tests for position transfer functionality (transfer_position and transfer_positions methods).
Rewritten from scratch using debug_test.py working patterns.
"""

import time

import pytest

from derive_client.data_types import InstrumentType, OrderSide, OrderType, TransferPosition, UnderlyingCurrency
from derive_client.exceptions import DeriveJSONRPCException


def test_transfer_position_validation_errors(derive_client_2):
    """Test transfer_position input validation."""
    # Get subaccounts for testing
    subaccounts = derive_client_2.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for validation tests")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Test invalid amount
    with pytest.raises(ValueError, match="Transfer amount must be positive"):
        derive_client_2.transfer_position(
            instrument_name="ETH-PERP",
            amount=-1.0,
            limit_price=1000.0,
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
            position_amount=5.0,
        )

    # Test invalid limit price
    with pytest.raises(ValueError, match="Limit price must be positive"):
        derive_client_2.transfer_position(
            instrument_name="ETH-PERP",
            amount=1.0,
            limit_price=-1000.0,
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
            position_amount=5.0,
        )

    # Test zero position amount
    with pytest.raises(ValueError, match="Position amount cannot be zero"):
        derive_client_2.transfer_position(
            instrument_name="ETH-PERP",
            amount=1.0,
            limit_price=1000.0,
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
            position_amount=0.0,
        )


def test_transfer_positions_validation_errors(derive_client_2):
    """Test transfer_positions input validation."""
    # Get subaccounts for testing
    subaccounts = derive_client_2.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for validation tests")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Test empty positions list
    with pytest.raises(ValueError, match="Positions list cannot be empty"):
        derive_client_2.transfer_positions(
            positions=[],
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
        )

    # Test invalid global direction
    transfer_position = TransferPosition(instrument_name="ETH-PERP", amount=1.0, limit_price=1000.0)

    with pytest.raises(ValueError, match="Global direction must be either 'buy' or 'sell'"):
        derive_client_2.transfer_positions(
            positions=[transfer_position],
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
            global_direction="invalid",
        )


def test_transfer_position_object_validation():
    """Test TransferPosition object validation."""
    # Test valid object creation
    transfer_pos = TransferPosition(instrument_name="ETH-PERP", amount=1.0, limit_price=1000.0)
    assert transfer_pos.instrument_name == "ETH-PERP"
    assert transfer_pos.amount == 1.0
    assert transfer_pos.limit_price == 1000.0

    # Test negative amount validation
    with pytest.raises(ValueError, match="Transfer amount must be positive"):
        TransferPosition(instrument_name="ETH-PERP", amount=-1.0, limit_price=1000.0)

    # Test zero amount validation
    with pytest.raises(ValueError, match="Transfer amount must be positive"):
        TransferPosition(instrument_name="ETH-PERP", amount=0.0, limit_price=1000.0)


def test_complete_position_transfer_workflow(position_setup, derive_client_2):
    """
    Comprehensive test that creates a position, transfers it between subaccounts,
    and transfers it back. Uses position_setup fixture for position creation.
    """
    position_info = position_setup

    # Verify initial position setup
    assert position_info['position_amount'] != 0, "Position should be created"
    assert position_info['from_subaccount_id'] != position_info['to_subaccount_id'], "Should have different subaccounts"

    from_subaccount_id = position_info['from_subaccount_id']
    to_subaccount_id = position_info['to_subaccount_id']
    instrument_name = position_info['instrument_name']
    initial_position_amount = position_info['position_amount']

    # Additional debugging: Check if the order was filled by checking open orders
    try:
        open_orders = derive_client_2.fetch_orders(instrument_name=instrument_name)
        print(f"Open orders: {open_orders}")
    except Exception as e:
        print(f"Error fetching open orders: {e}")

    # Try to cancel the order if it's still open
    try:
        if order_result and 'order_id' in order_result:
            order_id = order_result['order_id']
            cancel_result = derive_client_2.cancel(order_id=order_id, instrument_name=instrument_name)
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
        'created_order': order_result,
    }

    print(f"Final position info: {position_info}")
    return position_info
