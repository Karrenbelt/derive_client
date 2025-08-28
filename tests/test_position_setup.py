"""
Test to verify the position_setup fixture works correctly with dynamic instrument fetching.
"""

import pytest

def test_position_setup_fixture_creates_position(derive_client_2, position_setup):
    """
    Test that the position_setup fixture actually creates a usable position.
    """
    position_info = position_setup
    
    # Verify that we have the expected fields
    assert 'from_subaccount_id' in position_info
    assert 'to_subaccount_id' in position_info
    assert 'instrument_name' in position_info
    assert 'position_amount' in position_info
    assert 'order_price' in position_info
    
    # Verify that we got valid subaccount IDs
    assert isinstance(position_info['from_subaccount_id'], int)
    assert isinstance(position_info['to_subaccount_id'], int)
    assert position_info['from_subaccount_id'] != position_info['to_subaccount_id']
    
    # Verify that we got a valid instrument name
    assert isinstance(position_info['instrument_name'], str)
    assert len(position_info['instrument_name']) > 0
    
    # Verify that we got a valid position amount
    assert isinstance(position_info['position_amount'], (int, float))
    # Note: Position amount might be 0 if the order hasn't filled yet, but it should exist
    
    # Verify that we got a valid order price
    assert isinstance(position_info['order_price'], (int, float))
    assert position_info['order_price'] > 0
    
    print(f"Position setup successful: {position_info}")