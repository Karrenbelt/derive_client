"""
Sample for cancelling an order on the derive client.
"""

from rich import print

from derive_client.derive import DeriveClient
from derive_client.enums import Environment
from tests.conftest import TEST_PRIVATE_KEY


def main():
    """
    Demonstrate canceling all orders on the derive client.
    """

    client = DeriveClient(TEST_PRIVATE_KEY, env=Environment.TEST)
    order = client.cancel_all()
    print(order)


if __name__ == "__main__":
    main()
