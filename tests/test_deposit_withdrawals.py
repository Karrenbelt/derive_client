"""
Tests for the DeriveClient deposit and withdrawal methods for subaccounts.
"""

import pytest

from derive_client.enums import CollateralAsset


@pytest.mark.parametrize(
    "asset",
    [
        CollateralAsset.USDC,
    ],
)
def test_transfer_from_subaccount_to_pm_funding(derive_client, asset):
    """Test transfer from subaccount to funding."""
    # freeze_time(derive_client)
    amount = 1
    from_subaccount_id = derive_client.fetch_subaccounts()['subaccount_ids'][0]
    result = derive_client.transfer_from_subaccount_to_funding(
        amount=amount,
        subaccount_id=from_subaccount_id,
        asset_name=asset.name,
    )
    assert result


@pytest.mark.parametrize(
    "asset",
    [
        CollateralAsset.USDC,
    ],
)
def test_transfer_from_funding_to_pm_subaccount(derive_client, asset):
    """Test transfer from funding to subaccount."""
    # freeze_time(derive_client)
    amount = 1
    to_subaccount_id = derive_client.fetch_subaccounts()['subaccount_ids'][0]
    result = derive_client.transfer_from_funding_to_subaccount(
        amount=amount,
        subaccount_id=to_subaccount_id,
        asset_name=asset.name,
    )
    assert result
