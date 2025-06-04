"""
Example of how to poll RFQ (Request for Quote) status and handle transfers between subaccount and funding account.
"""

import os
from pathlib import Path
from time import sleep

import click
from dotenv import load_dotenv

from derive_client import DeriveClient
from derive_client.data_types import CollateralAsset, Environment


@click.command()
@click.option('--signer-key-path', required=True, help='Path to signer key file')
@click.option('--derive-sc-wallet', required=True, help='Derive SC wallet address')
def main(signer_key_path, derive_sc_wallet):
    """
    A command-line interface to poll RFQs (Request for Quotes) using the DeriveClient.

    Example usage:
        python examples/poll_rfq.py \ 
        --signer-key-path ./ethereum_private_key.txt \ 
        --derive-sc-wallet 0xYourDeriveSCWalletAddress
    """
    key_file = Path(signer_key_path)
    if not key_file.exists():
        click.echo(f"Signer key file not found: {signer_key_path}")
        return

    load_dotenv()
    subaccount_id = os.environ.get("SUBACCOUNT_ID")
    if not subaccount_id:
        click.echo("SUBACCOUNT_ID not found in environment variables.")
        return

    client = DeriveClient(
        private_key=key_file.read_text(),
        wallet=derive_sc_wallet,
        env=Environment.PROD,
        subaccount_id=subaccount_id,
    )

    while True:
        print("Polling RFQs...")
        quotes = client.poll_rfqs()
        sleep(5)  # Sleep for a while before polling again
        print(f"Found {len(quotes)} RFQs.") 
        for quote in quotes:
            print(f"RFQ ID: {quote.id}, Status: {quote.status}")


if __name__ == "__main__":
    main()
