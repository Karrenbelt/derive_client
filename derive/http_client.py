"""
Base class for HTTP client.
"""

from eth_account.messages import encode_defunct
from lyra_v2_action_signing.utils import utc_now_ms
from web3 import Web3

from derive.base_client import BaseClient


class HttpClient(BaseClient):
    def _create_signature_headers(self):
        """
        Create the signature headers
        """
        ts = utc_now_ms()
        msg = encode_defunct(
            text=str(ts),
        )
        signature = self.signer.sign_message(msg)
        return {
            "X-LyraWallet": self.wallet,
            "X-LyraTimestamp": str(ts),
            "X-LyraSignature": Web3.to_hex(signature.signature),
        }
