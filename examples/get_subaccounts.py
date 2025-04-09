"""
Simple demo script to show how to get a list of subaccounts.

This script is equivalent to the test_fetch_first_subaccount() test in tests/test_main.py.
"""

from pathlib import Path

import click

from derive_client.enums import Environment
from derive_client.http_client import HttpClient as DeriveClient
from tests.conftest import TEST_PRIVATE_KEY, TEST_WALLET


def main():
    """
    Demonstrate fetching subaccounts from the derive client.
    """

    client = DeriveClient(
        private_key=TEST_PRIVATE_KEY,
        wallet=TEST_WALLET,
        env=Environment.TEST,
    )
    subaccounts = client.fetch_subaccounts()
    for subaccount in subaccounts:
        print(subaccount)

    subaccounts = client.fetch_subaccounts()
    for subaccount in subaccounts['subaccount_ids']:
        client.subaccount_id = subaccount
        print(f"Subaccount ID: {subaccount}")
        client.cancel_all()
    print(subaccounts)


if __name__ == '__main__':
    main()
