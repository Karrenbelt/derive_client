"""
Conftest for derive tests
"""

from unittest.mock import MagicMock

import pytest

from derive.derive import DeriveClient
from derive.enums import Environment
from derive.utils import get_logger

TEST_WALLET = "0x3A5c777edf22107d7FdFB3B02B0Cdfe8b75f3453"
TEST_PRIVATE_KEY = "0xc14f53ee466dd3fc5fa356897ab276acbef4f020486ec253a23b0d1c3f89d4f4"


def freeze_time(derive_client):
    ts = 1705439697008
    nonce = 17054396970088651
    expiration = 1705439703008
    derive_client.get_nonce_and_signature_expiry = MagicMock(return_value=(ts, nonce, expiration))
    return derive_client


@pytest.fixture
def derive_client():
    derive_client = DeriveClient(TEST_PRIVATE_KEY, env=Environment.TEST, logger=get_logger())
    derive_client.subaccount_id = 5
    yield derive_client
    derive_client.cancel_all()


@pytest.fixture
def derive_client_2():
    derive_client = DeriveClient(TEST_PRIVATE_KEY, env=Environment.TEST, logger=get_logger())
    derive_client.subaccount_id = derive_client.fetch_subaccounts()[-1]['id']
    yield derive_client
    derive_client.cancel_all()
