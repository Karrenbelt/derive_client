"""
Example: Transfer multiple positions using derive_client

This example shows how to use the derive_client to transfer multiple positions
between subaccounts using the transfer_positions method.
"""

from derive_client import DeriveClient
from derive_client.data_types import Environment, TransferPosition


def main():
    # Initialize the client
    WALLET_ADDRESS = "0x8772185a1516f0d61fC1c2524926BfC69F95d698"
    PRIVATE_KEY = "0x2ae8be44db8a590d20bffbe3b6872df9b569147d3bf6801a35a28281a4816bbd"

    client = DeriveClient(
        wallet=WALLET_ADDRESS,
        private_key=PRIVATE_KEY,
        env=Environment.TEST,  # Use TEST for testnet, PROD for mainnet
        subaccount_id=30769,  # default subaccount ID
    )

    # Define transfer parameters
    FROM_SUBACCOUNT_ID = 30769
    TO_SUBACCOUNT_ID = 31049
    GLOBAL_DIRECTION = "buy"  # Global direction for the transfer

    # Define positions to transfer using TransferPosition objects
    positions_to_transfer = [
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

    try:
        print("Transferring multiple positions:")
        for pos in positions_to_transfer:
            print(f"  - {pos.amount} of {pos.instrument_name} at {pos.limit_price}")
        print(f"From subaccount: {FROM_SUBACCOUNT_ID}")
        print(f"To subaccount: {TO_SUBACCOUNT_ID}")
        print(f"Global direction: {GLOBAL_DIRECTION}")

        # Transfer the positions
        result = client.transfer_positions(
            positions=positions_to_transfer,
            from_subaccount_id=FROM_SUBACCOUNT_ID,
            to_subaccount_id=TO_SUBACCOUNT_ID,
            global_direction=GLOBAL_DIRECTION,
        )

        print("Transfer successful!")
        print(f"Transaction ID: {result.transaction_id}")
        print(f"Status: {result.status}")
        print(f"Transaction Hash: {result.tx_hash}")

    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


def fetch_position_then_transfer():
    """
    Advanced example showing how to get user's current positions
    and transfer a portion of them.
    """
    WALLET_ADDRESS = "0x8772185a1516f0d61fC1c2524926BfC69F95d698"
    PRIVATE_KEY = "0x2ae8be44db8a590d20bffbe3b6872df9b569147d3bf6801a35a28281a4816bbd"

    client = DeriveClient(
        wallet=WALLET_ADDRESS,
        private_key=PRIVATE_KEY,
        env=Environment.TEST,
        subaccount_id=30769,
    )

    # Get current positions
    positions_data = client.get_positions()
    current_positions = positions_data.get("positions", [])

    if not current_positions:
        print("No positions found to transfer")
        return

    # Filter positions that have a non-zero amount
    transferable_positions = [pos for pos in current_positions if float(pos.get("amount", 0)) != 0]

    if not transferable_positions:
        print("No positions with non-zero amounts found")
        return

    # Create transfer list from current positions (transfer 50% of each)
    positions_to_transfer = []
    for pos in transferable_positions[:2]:  # Limit to first 2 positions
        current_amount = abs(float(pos["amount"]))
        transfer_amount = current_amount * 0.5  # Transfer 50%

        # Get current mark price or use a reasonable price
        mark_price = float(pos.get("mark_price", "0"))
        if mark_price == 0:
            mark_price = 2500.0  # Default price if no mark price available

        positions_to_transfer.append(
            TransferPosition(
                instrument_name=pos["instrument_name"],
                amount=transfer_amount,
                limit_price=mark_price,
            )
        )

    print("Transferring 50% of current positions:")
    for pos in positions_to_transfer:
        print(f"  - {pos.amount:.4f} of {pos.instrument_name} at {pos.limit_price}")

    try:
        result = client.transfer_positions(
            positions=positions_to_transfer,
            from_subaccount_id=30769,
            to_subaccount_id=31049,
            global_direction="buy",
        )

        print("Advanced transfer successful!")
        print(f"Transaction ID: {result.transaction_id}")
        print(f"Status: {result.status}")

    except Exception as e:
        print(f"Error in advanced transfer: {e}")


if __name__ == "__main__":
    # Run basic example
    # print("=== Basic Multiple Positions Transfer Example ===")
    # main()

    print("\n" + "=" * 50)
    print("=== Advanced Example: Transfer from Current Positions ===")
    fetch_position_then_transfer()
