import aiohttp

from derive_client._clients.models import (
    PublicGetTickerResponseSchema,
    PublicGetTickerResultSchema,
    RPCErrorFormatSchema,
)
from derive_client.constants import CONFIGS, PUBLIC_HEADERS
from derive_client.data_types import Address, Environment
from derive_client.endpoints import RestAPI as EndPoints


class AioClient:
    """Pure asynchronous HTTP client"""

    def __init__(self, wallet: Address, session_key: str, env: Environment):
        self.wallet = wallet
        self.session_key = session_key
        self.config = CONFIGS[env]

        self.session = None

    @property
    def endpoints(self):
        return EndPoints(self.config.base_url)

    async def _ensure_session(self):
        """Lazy session creation"""

        if not self.session:
            self.session = aiohttp.ClientSession()

    async def get_ticker(self, instrument_name: str) -> PublicGetTickerResultSchema:
        await self._ensure_session()

        url = self.endpoints.public.get_ticker
        payload = {"instrument_name": instrument_name}

        response = await self.session.post(url, json=payload, headers=PUBLIC_HEADERS)
        response_data = await response.json()

        if "error" in response_data:
            return RPCErrorFormatSchema(**response_data["error"])

        response_data = PublicGetTickerResponseSchema(**response_data)

        return response_data.result
