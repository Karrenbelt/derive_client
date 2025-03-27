"""
Simple demo script to show how to get a list of subaccounts.

This script is equivalent to the test_fetch_first_subaccount() test in tests/test_main.py.
"""

from pathlib import Path
import click

from derive_client.enums import Environment
from derive_client.http_client import HttpClient as DeriveClient

@click.command()
@click.option('--signer-key-path', required=True, help='Path to signer key file')
@click.option('--derive-sc-wallet', required=True, help='Derive SC wallet address')
def main(signer_key_path, derive_sc_wallet):
    key_file = Path(signer_key_path)
    if not key_file.exists():
        click.echo(f"Signer key file not found: {signer_key_path}")
        return
    
    client = DeriveClient(
        private_key=key_file.read_text(),
        wallet=derive_sc_wallet,
        env=Environment.PROD,
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
