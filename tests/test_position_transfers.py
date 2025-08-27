"""
Tests for the DeriveClient transfer_position and transfer_positions methods.
"""

import pytest

from derive_client.data_types import InstrumentType, TransferPosition

PM_SUBACCOUNT_ID = 31049
SM_SUBACCOUNT_ID = 30769
TARGET_SUBACCOUNT_ID = 137404

# Test instrument parameters
TEST_INSTRUMENTS = [
    ("ETH-PERP", InstrumentType.PERP, 2500.0, 0.1),
    ("BTC-PERP", InstrumentType.PERP, 45000.0, 0.01),
]

# Position transfer amounts for testing
TRANSFER_AMOUNTS = [0.1, 0.01, 0.5]


def get_position_amount_for_test(derive_client, instrument_name, subaccount_id):
    """Helper function to get position amount for testing, with fallback to mock data."""
    try:
        return derive_client.get_position_amount(instrument_name, subaccount_id)
    except (ValueError, Exception):
        pass  # If no position found or API call fails, use mock data

    # Return mock position amount if no real position found
    return 1.0


@pytest.mark.parametrize(
    "instrument_name,instrument_type,limit_price,amount",
    TEST_INSTRUMENTS,
)
def test_transfer_position_basic(derive_client, instrument_name, instrument_type, limit_price, amount):
    """Test basic transfer_position functionality."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    # Use first two subaccounts for transfer
    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Get position amount for testing (with fallback to mock data)
    position_amount = get_position_amount_for_test(derive_client, instrument_name, from_subaccount_id)
    result = derive_client.transfer_position(
        instrument_name=instrument_name,
        amount=amount,
        limit_price=limit_price,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        position_amount=position_amount,
    )

    assert result is not None
    assert hasattr(result, 'transaction_id')
    assert hasattr(result, 'status')
    assert hasattr(result, 'tx_hash')


@pytest.mark.parametrize(
    "from_subaccount,to_subaccount",
    [
        (SM_SUBACCOUNT_ID, PM_SUBACCOUNT_ID),
        (PM_SUBACCOUNT_ID, SM_SUBACCOUNT_ID),
    ],
)
def test_transfer_position_between_specific_subaccounts(derive_client, from_subaccount, to_subaccount):
    """Test transfer_position between specific subaccount types."""
    instrument_name = "ETH-PERP"
    amount = 0.1
    limit_price = 2500.0
    position_amount = get_position_amount_for_test(derive_client, instrument_name, from_subaccount)

    result = derive_client.transfer_position(
        instrument_name=instrument_name,
        amount=amount,
        limit_price=limit_price,
        from_subaccount_id=from_subaccount,
        to_subaccount_id=to_subaccount,
        position_amount=position_amount,
    )

    assert result is not None
    assert result.transaction_id
    assert result.status


def test_transfer_position_with_position_amount(derive_client):
    """Test transfer_position with explicit position_amount parameter."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Get position amount using helper function
    position_amount = get_position_amount_for_test(derive_client, "ETH-PERP", from_subaccount_id)

    result = derive_client.transfer_position(
        instrument_name="ETH-PERP",
        amount=0.1,
        limit_price=2500.0,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        position_amount=position_amount,
    )

    assert result is not None
    assert result.transaction_id


@pytest.mark.parametrize(
    "global_direction",
    ["buy", "sell"],
)
def test_transfer_positions_basic(derive_client, global_direction):
    """Test basic transfer_positions functionality with different directions."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Define multiple positions to transfer
    positions = [
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=2500.0,
        ),
        TransferPosition(
            instrument_name="BTC-PERP",
            amount=0.01,
            limit_price=45000.0,
        ),
    ]

    result = derive_client.transfer_positions(
        positions=positions,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        global_direction=global_direction,
    )

    assert result is not None
    assert hasattr(result, 'transaction_id')
    assert hasattr(result, 'status')
    assert hasattr(result, 'tx_hash')


def test_transfer_positions_single_position(derive_client):
    """Test transfer_positions with a single position."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Single position
    positions = [
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.5,
            limit_price=2500.0,
        )
    ]

    result = derive_client.transfer_positions(
        positions=positions,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        global_direction="buy",
    )

    assert result is not None
    assert result.transaction_id


@pytest.mark.parametrize(
    "from_subaccount,to_subaccount,global_direction",
    [
        (SM_SUBACCOUNT_ID, PM_SUBACCOUNT_ID, "buy"),
        (PM_SUBACCOUNT_ID, SM_SUBACCOUNT_ID, "sell"),
        (SM_SUBACCOUNT_ID, PM_SUBACCOUNT_ID, "sell"),
        (PM_SUBACCOUNT_ID, SM_SUBACCOUNT_ID, "buy"),
    ],
)
def test_transfer_positions_between_subaccount_types(derive_client, from_subaccount, to_subaccount, global_direction):
    """Test transfer_positions between different subaccount types."""
    positions = [
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=2500.0,
        ),
        TransferPosition(
            instrument_name="BTC-PERP",
            amount=0.01,
            limit_price=45000.0,
        ),
    ]

    result = derive_client.transfer_positions(
        positions=positions,
        from_subaccount_id=from_subaccount,
        to_subaccount_id=to_subaccount,
        global_direction=global_direction,
    )

    assert result is not None
    assert result.transaction_id
    assert result.status


def test_transfer_positions_multiple_instruments(derive_client):
    """Test transfer_positions with multiple different instruments."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Get available instruments to ensure we test with valid ones
    perp_instruments = derive_client.fetch_instruments(instrument_type=InstrumentType.PERP)

    if len(perp_instruments) < 3:
        pytest.skip("Need at least 3 perpetual instruments for comprehensive test")

    # Use first 3 available instruments
    positions = []
    for i, instrument in enumerate(perp_instruments[:3]):
        positions.append(
            TransferPosition(
                instrument_name=instrument["instrument_name"],
                amount=0.1 * (i + 1),  # Varying amounts
                limit_price=1000.0 + (i * 1000),  # Varying prices
            )
        )

    result = derive_client.transfer_positions(
        positions=positions,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        global_direction="buy",
    )

    assert result is not None
    assert result.transaction_id


@pytest.mark.parametrize(
    "amount",
    TRANSFER_AMOUNTS,
)
def test_transfer_position_different_amounts(derive_client, amount):
    """Test transfer_position with different transfer amounts."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    position_amount = get_position_amount_for_test(derive_client, "ETH-PERP", from_subaccount_id)
    result = derive_client.transfer_position(
        instrument_name="ETH-PERP",
        amount=amount,
        limit_price=2500.0,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        position_amount=position_amount,
    )

    assert result is not None
    assert result.transaction_id


def test_transfer_position_invalid_instrument(derive_client):
    """Test transfer_position with invalid instrument name."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Test with invalid instrument name (position_amount doesn't matter since instrument validation comes first)
    position_amount = 1.0  # Mock amount for error case
    with pytest.raises(ValueError, match="Instrument .* not found"):
        derive_client.transfer_position(
            instrument_name="INVALID-INSTRUMENT",
            amount=0.1,
            limit_price=2500.0,
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
            position_amount=position_amount,
        )


def test_transfer_positions_empty_list(derive_client):
    """Test transfer_positions with empty positions list."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Empty positions list should be handled gracefully
    positions = []

    result = derive_client.transfer_positions(
        positions=positions,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        global_direction="buy",
    )

    # Should still return a result object, even if no transfers occurred
    assert result is not None


def test_transfer_positions_invalid_instrument_in_list(derive_client):
    """Test transfer_positions with invalid instrument in positions list."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Mix of valid and invalid instruments
    positions = [
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=2500.0,
        ),
        TransferPosition(
            instrument_name="INVALID-INSTRUMENT",
            amount=0.1,
            limit_price=1000.0,
        ),
    ]

    # Should raise error due to invalid instrument
    with pytest.raises(ValueError, match="Instrument .* not found"):
        derive_client.transfer_positions(
            positions=positions,
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
            global_direction="buy",
        )


def test_transfer_position_same_subaccount(derive_client):
    """Test transfer_position between same subaccount (should work but be a no-op)."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 1:
        pytest.skip("Need at least 1 subaccount for test")

    same_subaccount_id = subaccount_ids[0]

    position_amount = get_position_amount_for_test(derive_client, "ETH-PERP", same_subaccount_id)
    result = derive_client.transfer_position(
        instrument_name="ETH-PERP",
        amount=0.1,
        limit_price=2500.0,
        from_subaccount_id=same_subaccount_id,
        to_subaccount_id=same_subaccount_id,
        position_amount=position_amount,
    )

    assert result is not None
    assert result.transaction_id


def test_transfer_positions_same_subaccount(derive_client):
    """Test transfer_positions between same subaccount."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 1:
        pytest.skip("Need at least 1 subaccount for test")

    same_subaccount_id = subaccount_ids[0]

    positions = [
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=2500.0,
        )
    ]

    result = derive_client.transfer_positions(
        positions=positions,
        from_subaccount_id=same_subaccount_id,
        to_subaccount_id=same_subaccount_id,
        global_direction="buy",
    )

    assert result is not None
    assert result.transaction_id


@pytest.mark.parametrize(
    "price_multiplier",
    [0.1, 0.5, 1.0, 1.5, 2.0],
)
def test_transfer_position_different_prices(derive_client, price_multiplier):
    """Test transfer_position with different price levels."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    base_price = 2500.0
    test_price = base_price * price_multiplier

    position_amount = get_position_amount_for_test(derive_client, "ETH-PERP", from_subaccount_id)
    result = derive_client.transfer_position(
        instrument_name="ETH-PERP",
        amount=0.1,
        limit_price=test_price,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        position_amount=position_amount,
    )

    assert result is not None
    assert result.transaction_id


def test_transfer_positions_varied_prices(derive_client):
    """Test transfer_positions with varied prices for different instruments."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Positions with varied price levels
    positions = [
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=100.0,  # Very low price
        ),
        TransferPosition(
            instrument_name="BTC-PERP",
            amount=0.01,
            limit_price=100000.0,  # Very high price
        ),
    ]

    result = derive_client.transfer_positions(
        positions=positions,
        from_subaccount_id=from_subaccount_id,
        to_subaccount_id=to_subaccount_id,
        global_direction="buy",
    )

    assert result is not None
    assert result.transaction_id


def test_transfer_position_object_validation():
    """Test TransferPosition object validation."""
    # Valid object should work
    valid_position = TransferPosition(
        instrument_name="ETH-PERP",
        amount=0.1,
        limit_price=2500.0,
    )
    assert valid_position.instrument_name == "ETH-PERP"
    assert valid_position.amount == 0.1
    assert valid_position.limit_price == 2500.0

    # Test negative amount validation
    with pytest.raises(ValueError, match="Transfer amount must be positive"):
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=-0.1,  # Should fail validation
            limit_price=2500.0,
        )

    # Test negative limit_price validation
    with pytest.raises(ValueError, match="Limit price must be positive"):
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=-2500.0,  # Should fail validation
        )


def test_transfer_positions_invalid_global_direction():
    """Test transfer_positions with invalid global_direction."""
    from derive_client import DeriveClient
    from derive_client.data_types import Environment

    client = DeriveClient(wallet="0x123", private_key="0x456", env=Environment.TEST)

    positions = [
        TransferPosition(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=2500.0,
        )
    ]

    # Test invalid global_direction
    with pytest.raises(ValueError, match="Global direction must be either 'buy' or 'sell'"):
        client.transfer_positions(
            positions=positions,
            from_subaccount_id=123,
            to_subaccount_id=456,
            global_direction="invalid",  # Should fail validation
        )


def test_transfer_position_zero_position_amount_error(derive_client):
    """Test transfer_position raises error for zero position amount."""
    # Get available subaccounts
    subaccounts = derive_client.fetch_subaccounts()
    subaccount_ids = subaccounts['subaccount_ids']

    if len(subaccount_ids) < 2:
        pytest.skip("Need at least 2 subaccounts for position transfer test")

    from_subaccount_id = subaccount_ids[0]
    to_subaccount_id = subaccount_ids[1]

    # Test zero position amount should raise error
    with pytest.raises(ValueError, match="Position amount cannot be zero"):
        derive_client.transfer_position(
            instrument_name="ETH-PERP",
            amount=0.1,
            limit_price=2500.0,
            from_subaccount_id=from_subaccount_id,
            to_subaccount_id=to_subaccount_id,
            position_amount=0.0,  # Should raise error
        )


def test_get_position_amount_helper(derive_client):
    """Test the get_position_amount helper method."""
    # Test with likely non-existent position should raise ValueError
    with pytest.raises(ValueError, match="No position found for"):
        derive_client.get_position_amount("NONEXISTENT-PERP", 999999)

    # Test with real data would require actual positions, so we just test the error case
