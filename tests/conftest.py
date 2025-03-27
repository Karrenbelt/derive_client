"""
Conftest for derive tests
"""

from unittest.mock import MagicMock

import pytest

from derive.derive import DeriveClient
from derive.enums import Environment
from derive.utils import get_logger

TEST_WALLET = "0x199c2aa4403C4C4ea200a854a34c3BA73C5b517e"
TEST_PRIVATE_KEY = "0x07d2a546f38573fe0f62e63d505d5b95a95ac5b12b115c8a7dde6ee76acc8556"


def freeze_time(derive_client):
    ts = 1705439697008
    nonce = 17054396970088651
    expiration = 1705439703008
    derive_client.get_nonce_and_signature_expiry = MagicMock(return_value=(ts, nonce, expiration))
    return derive_client


@pytest.fixture
def derive_client():
    derive_client = DeriveClient(TEST_PRIVATE_KEY, env=Environment.TEST, wallet=TEST_WALLET, logger=get_logger())
    derive_client.subaccount_id = 132849
    yield derive_client
    derive_client.cancel_all()


@pytest.fixture
def derive_client_2():
    derive_client = DeriveClient(TEST_PRIVATE_KEY, env=Environment.TEST, logger=get_logger())
    derive_client.subaccount_id = derive_client.fetch_subaccounts()[-1]['id']
    yield derive_client
    derive_client.cancel_all()
