"""
Example: Transfer a single position using derive_client

This example shows how to use the derive_client to transfer a single position
between subaccounts using the transfer_position method.
"""

from derive_client import DeriveClient
from derive_client.data_types import Environment


def main():
    # Initialize the client
    WALLET_ADDRESS = "0xeda0656dab4094C7Dc12F8F12AF75B5B3Af4e776"
    PRIVATE_KEY = "0x83ee63dc6655509aabce0f7e501a31c511195e61e9d0e9917f0a55fd06041a66"

    client = DeriveClient(
        wallet=WALLET_ADDRESS,
        private_key=PRIVATE_KEY,
        env=Environment.TEST,  # Use TEST for testnet, PROD for mainnet
        subaccount_id=137402,  # default subaccount ID
    )

    # Define transfer parameters
    FROM_SUBACCOUNT_ID = 137402
    TO_SUBACCOUNT_ID = 137404
    INSTRUMENT_NAME = "ETH-PERP"
    TRANSFER_AMOUNT = 0.1  # Amount to transfer (absolute value)
    LIMIT_PRICE = 2500.0  # Price for the transfer

    try:
        print(f"Transferring {TRANSFER_AMOUNT} of {INSTRUMENT_NAME}")
        print(f"From subaccount: {FROM_SUBACCOUNT_ID}")
        print(f"To subaccount: {TO_SUBACCOUNT_ID}")
        print(f"At limit price: {LIMIT_PRICE}")

        # First, get the current position amount to determine direction
        try:
            position_amount = client.get_position_amount(INSTRUMENT_NAME, FROM_SUBACCOUNT_ID)
            print(f"Current position amount: {position_amount}")
        except ValueError as e:
            print(f"Error: {e}")
            return

        # Transfer the position
        result = client.transfer_position(
            instrument_name=INSTRUMENT_NAME,
            amount=TRANSFER_AMOUNT,
            limit_price=LIMIT_PRICE,
            from_subaccount_id=FROM_SUBACCOUNT_ID,
            to_subaccount_id=TO_SUBACCOUNT_ID,
            position_amount=position_amount,  # Now required parameter
        )

        print("Transfer successful!")
        print(f"Transaction ID: {result.transaction_id}")
        print(f"Status: {result.status}")
        print(f"Transaction Hash: {result.tx_hash}")

    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
