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

    def __init__(self):
        self.default_timeout = 5

        self._session: requests.Session | None = None
        self._finalizer = weakref.finalize(self, self._finalize)

    def open(self):
        """Lazy session creation"""

        if not self._session:
            self._session = requests.Session()

    def close(self):
        """Explicit cleanup"""
        if self._session:
            self._session.close()
            self._session = None

    def _send_request(self, url: str, params: dict, *, timeout: float | None = None):
        self.open()

        headers = PUBLIC_HEADERS
        timeout = timeout or self.default_timeout
        response = self._session.post(url, json=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        try:
            message = response.json()
        except Exception as e:
            raise ValueError(f"Failed to decode JSON from {url}: {e}") from e
        return message

    def _finalize(self):
        if self._session:
            msg = "%s was garbage collected without explicit close(); closing session automatically"
            logger.debug(msg, self.__class__.__name__)
            try:
                self._session.close()
            except Exception:
                logger.exception("Error closing session in finalizer")
            self._session = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class DeriveHttpClient:
    def __init__(self, wallet: str, session_key: str, env: str):
        self.wallet = wallet
        self.session_key = session_key
        self.config = CONFIGS[env]
        self._http = HttpClient()

    @property
    def endpoints(self):
        return EndPoints(self.config.base_url)

    def __enter__(self):
        self._http.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._http.__exit__(exc_type, exc_val, exc_tb)

    def open(self):
        self._http.open()

    def close(self):
        self._http.close()

    def get_ticker(self, instrument_name: str):
        url = self.endpoints.public.get_ticker
        params = {"instrument_name": instrument_name}
        message = self._http._send_request(url, params)
        return try_cast_response(message, PublicGetTickerResultSchema)
