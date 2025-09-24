import weakref
import aiohttp

from derive_client._clients.models import (
    PublicGetTickerResponseSchema,
    PublicGetTickerResultSchema,
    RPCErrorFormatSchema,
)
from derive_client.constants import CONFIGS, PUBLIC_HEADERS
from derive_client.data_types import Address, Environment
from derive_client.endpoints import RestAPI as EndPoints

from derive_client._clients.utils import try_cast_response
from derive_client._clients.logger import logger


class AioClient:
    """Pure asynchronous HTTP client"""

    def __init__(self, wallet: Address, session_key: str, env: Environment):
        self.wallet = wallet
        self.session_key = session_key
        self.config = CONFIGS[env]

        self.default_timeout = 5
        self.session: aiohttp.ClientSession | None = None
        self._finalizer = weakref.finalize(self, self._cleanup)

    @property
    def endpoints(self):
        return EndPoints(self.config.base_url)

    async def _ensure_session(self):
        """Lazy session creation"""

        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Explicit cleanup"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _cleanup(self):
        if self.session:
            logger.warning(
                f"{self.__class__.__name__} was garbage collected without explicit close(). "
                "Use 'async with' or call close() explicitly to ensure proper cleanup."
            )
            self.session = None

    async def _send_request(self, url: str, params: dict, *, timeout: float | None = None):
        await self._ensure_session()
        headers = PUBLIC_HEADERS
        timeout = timeout or self.default_timeout
        async with self.session.post(url, json=params, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            try:
                return await response.json()
            except Exception as e:
                raise ValueError(f"Failed to decode JSON from {url}: {e}") from e

    async def get_ticker(self, instrument_name: str) -> PublicGetTickerResultSchema:
        url = self.endpoints.public.get_ticker
        params = {"instrument_name": instrument_name}
        message = await self._send_request(url=url, params=params)
        result = try_cast_response(message=message, result_schema=PublicGetTickerResultSchema)
        return result
