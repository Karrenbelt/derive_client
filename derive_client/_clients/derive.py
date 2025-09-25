import asyncio

from dotenv import load_dotenv

from derive_client._clients.aio import DeriveAioClient
from derive_client._clients.http import DeriveHttpClient
from derive_client._clients.ws import DeriveWsClient
from derive_client._clients.logger import logger
from derive_client.data_types import Address, Environment

load_dotenv()


class DeriveClient:
    """Unified client facade providing access to all transport methods."""

    def __init__(self, wallet: Address, session_key: str, env: Environment):
        self.wallet = wallet
        self.session_key = session_key
        self.env = env

        # Lazy initialization
        self._sync_client = None
        self._async_client = None
        self._ws_client = None

    @property
    def http(self) -> DeriveHttpClient:
        """Access synchronous HTTP client"""
        if not self._sync_client:
            self._sync_client = DeriveHttpClient(self.wallet, self.session_key, self.env)
        return self._sync_client

    @property
    def aio(self) -> DeriveAioClient:
        """Access asynchronous HTTP client"""
        if not self._async_client:
            self._async_client = DeriveAioClient(self.wallet, self.session_key, self.env)
        return self._async_client

    @property
    def ws(self) -> DeriveWsClient:
        """Access WebSocket client (always async)"""
        if not self._ws_client:
            self._ws_client = DeriveWsClient(self.wallet, self.session_key, self.env)
        return self._ws_client

    @property
    def bridge(self): ...


async def test_it(instrument_name: str):
    with client.http as http:
        http_ticker = http.get_ticker(instrument_name=instrument_name)

    http_ticker = client.http.get_ticker(instrument_name=instrument_name)
    client.http.close()

    async with client.aio as aio:
        aio_ticker = await aio.get_ticker(instrument_name=instrument_name)

    aio_ticker = await client.aio.get_ticker(instrument_name=instrument_name)
    await client.aio.close()

    async with client.ws as ws:
        ws_ticker = await ws.rpc.get_ticker(instrument_name=instrument_name)

    ws_ticker = await client.ws.rpc.get_ticker(instrument_name=instrument_name)
    await client.ws.close()

    # NOTE: caller, not the subscription, should own the connection
    async with client.ws:
        async with client.ws.channels.ticker(instrument_name=instrument_name) as sub:
            async for ticker in sub:
                logger.error(f"{ticker}")
                break

    async with client.ws.channels.ticker(instrument_name=instrument_name) as sub:
        async for ticker in sub:
            logger.error(f"{ticker}")
            break
    await client.ws.close()

    async with client.ws as ws:
        async with ws.channels.ticker(instrument_name=instrument_name) as sub1:
            async with ws.channels.ticker(instrument_name=instrument_name) as sub2:
                async for msg in sub1:
                    logger.error(f"Sub1: {msg}")
                    break
                async for msg in sub2:
                    logger.error(f"Sub2: {msg}")
                    break

    http_ticker = aio_ticker = ws_ticker = ticker = None
    return http_ticker, aio_ticker, ws_ticker, ticker


if __name__ == "__main__":
    TEST_WALLET = "0x8772185a1516f0d61fC1c2524926BfC69F95d698"
    TEST_SESSION_KEY = "0x2ae8be44db8a590d20bffbe3b6872df9b569147d3bf6801a35a28281a4816bbd"

    client = DeriveClient(
        wallet=TEST_WALLET,
        session_key=TEST_SESSION_KEY,
        env=Environment.TEST,
    )

    instrument_name = "ETH-PERP"

    async def _run():
        return await test_it(instrument_name)

    http_ticker, aio_ticker, ws_ticker, ticker = asyncio.run(_run())
    breakpoint()
