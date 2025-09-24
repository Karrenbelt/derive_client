import requests
import weakref

from derive_client._clients.models import (
    PublicGetTickerResultSchema,
)
from derive_client.constants import CONFIGS, PUBLIC_HEADERS
from derive_client.data_types import Address, Environment
from derive_client.endpoints import RestAPI as EndPoints
from derive_client._clients.utils import try_cast_response
from derive_client._clients.logger import logger


class HttpClient:
    """Pure synchronous HTTP client"""

    def __init__(self, wallet: Address, session_key: str, env: Environment):
        self.wallet = wallet
        self.session_key = session_key
        self.config = CONFIGS[env]

        self.default_timeout = 5
        self.session: requests.Session | None = None
        self._finalizer = weakref.finalize(self, self._cleanup)

    @property
    def endpoints(self):
        return EndPoints(self.config.base_url)

    def _ensure_session(self):
        """Lazy session creation"""

        if not self.session:
            self.session = requests.Session()

    def close(self):
        """Explicit cleanup"""
        if self.session:
            self.session.close()
            self.session = None

    def _cleanup(self):
        if self.session:
            logger.warning(
                f"{self.__class__.__name__} was garbage collected without explicit close(). "
                "Use 'with' or call close() to ensure proper cleanup."
            )
            self.session.close()
            self.session = None

    def _send_request(self, url: str, params: dict, *, timeout: float | None = None):
        self._ensure_session()
        headers = PUBLIC_HEADERS
        timeout = timeout or self.default_timeout
        response = self.session.post(url, json=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        try:
            message = response.json()
        except Exception as e:
            raise ValueError(f"Failed to decode JSON from {url}: {e}") from e
        return message

    def __enter__(self):
        self._ensure_session()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            self.session.close()
            self.session = None

    def get_ticker(self, instrument_name: str) -> PublicGetTickerResultSchema:
        url = self.endpoints.public.get_ticker
        params = {"instrument_name": instrument_name}
        message = self._send_request(url=url, params=params)
        result = try_cast_response(message=message, result_schema=PublicGetTickerResultSchema)
        return result
