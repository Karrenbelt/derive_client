import asyncio
import weakref
import aiohttp

from derive_client._clients.models import (
    PublicGetTickerResultSchema,
)
from derive_client.constants import CONFIGS, PUBLIC_HEADERS
from derive_client.data_types import Address, Environment
from derive_client.endpoints import RestAPI as EndPoints

from derive_client._clients.utils import try_cast_response
from derive_client._clients.logger import logger


class AioClient:
    """Pure asynchronous HTTP client"""

    def __init__(self):
        self.default_timeout = 5

        self._connector: aiohttp.TCPConnector | None = None
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()
        self._finalizer = weakref.finalize(self, self._finalize)

    async def open(self) -> None:
        """Explicit session creation."""

        if self._session and not self._session.closed:
            return

        async with self._lock:
            if self._session and not self._session.closed:
                return

            self._connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=10,
                keepalive_timeout=30,
                enable_cleanup_closed=True,
            )

            self._session = aiohttp.ClientSession(connector=self._connector)

    async def close(self):
        """Explicit cleanup"""

        async with self._lock:
            session = self._session
            connector = self._connector
            self._session = None
            self._connector = None

        if session and not session.closed:
            try:
                await session.close()
            except Exception:
                logger.exception("Error closing session")

        if connector and not connector.closed:
            try:
                await connector.close()
            except Exception:
                logger.exception("Error closing connector")

    async def _send_request(self, url: str, params: dict, *, timeout: float | None = None):
        await self.open()

        headers = PUBLIC_HEADERS
        timeout = timeout or self.default_timeout
        async with self._session.post(url, json=params, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            try:
                return await response.json()
            except Exception as e:
                raise ValueError(f"Failed to decode JSON from {url}: {e}") from e

    def _finalize(self):
        if self._session:
            msg = "%s was garbage collected with an open session. Session will be closed by process exit if needed."
            logger.debug(msg, self.__class__.__name__)

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class DeriveAioClient:
    def __init__(self, wallet: str, session_key: str, env: str):
        self.wallet = wallet
        self.session_key = session_key
        self.config = CONFIGS[env]
        self._aio = AioClient()

    @property
    def endpoints(self):
        return EndPoints(self.config.base_url)

    async def __aenter__(self):
        await self._aio.open()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._aio.close()

    async def open(self):
        await self._aio.open()

    async def close(self):
        await self._aio.close()

    async def get_ticker(self, instrument_name: str) -> PublicGetTickerResultSchema:
        url = self.endpoints.public.get_ticker
        params = {"instrument_name": instrument_name}
        message = await self._aio._send_request(url=url, params=params)
        result = try_cast_response(message=message, result_schema=PublicGetTickerResultSchema)
        return result
