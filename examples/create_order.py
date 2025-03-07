"""
Sample for creating an order on the derive client.
"""

from rich import print

from derive.derive import DeriveClient
from derive.enums import Environment, OrderSide
from tests.conftest import TEST_PRIVATE_KEY


def main():
    """
    Demonstrate fetching instruments from the derive client.
    """

    client = DeriveClient(TEST_PRIVATE_KEY, env=Environment.TEST)
    order = client.create_order(
        instrument_name="BTC-PERP",
        side=OrderSide.BUY,
        price=1000,
        amount=1,
    )
    print(order)


if __name__ == "__main__":
    main()
