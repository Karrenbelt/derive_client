"""
Tests for the DeriveClient deposit and withdrawal methods for subaccounts.
"""

import pytest

from derive_client.enums import CollateralAsset

PM_SUBACCOUNT_ID = 31049
SM_SUBACCOUNT_ID = 30769


@pytest.mark.parametrize(
    "asset,subaccount_id",
    [
        (CollateralAsset.USDC, PM_SUBACCOUNT_ID),
        (CollateralAsset.USDC, SM_SUBACCOUNT_ID),
    ],
)
def test_transfer_from_subaccount_to_funding(derive_client, asset, subaccount_id):
    """Test transfer from subaccount to funding."""
    # freeze_time(derive_client)
    amount = 1
    result = derive_client.transfer_from_subaccount_to_funding(
        amount=amount,
        subaccount_id=subaccount_id,
        asset_name=asset.name,
    )
    assert result


@pytest.mark.parametrize(
    "asset,subaccount_id",
    [
        (CollateralAsset.USDC, PM_SUBACCOUNT_ID),
        (CollateralAsset.USDC, SM_SUBACCOUNT_ID),
    ],
)
def test_transfer_from_subaccount_to_sm_funding(derive_client, asset, subaccount_id):
    """Test transfer from subaccount to funding."""
    # freeze_time(derive_client)
    amount = 1
    from_subaccount_id = derive_client.fetch_subaccounts()['subaccount_ids'][-1]
    result = derive_client.transfer_from_funding_to_subaccount(
        amount=amount,
        subaccount_id=from_subaccount_id,
        asset_name=asset.name,
    )
    assert result
