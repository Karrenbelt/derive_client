import asyncio

from dotenv import load_dotenv

from derive_client._clients.http import HTTPClient
from derive_client._clients.aio import AsyncHTTPClient
from derive_client._clients.ws import WebSocketClient
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
    def http(self) -> HTTPClient:
        """Access synchronous HTTP client"""
        if not self._sync_client:
            self._sync_client = HTTPClient(self.wallet, self.session_key, self.env)
        return self._sync_client

    @property
    def aio(self) -> AsyncHTTPClient:
        """Access asynchronous HTTP client"""
        if not self._async_client:
            self._async_client = AsyncHTTPClient(self.wallet, self.session_key, self.env)
        return self._async_client

    @property
    def ws(self) -> WebSocketClient:
        """Access WebSocket client (always async)"""
        if not self._ws_client:
            self._ws_client = WebSocketClient(self.wallet, self.session_key, self.env)
        return self._ws_client

    @property
    def bridge(self): ...


def subscription_consumers(ws):
    return {k: len(v) for k, v in ws._session._subscriptions.items()}


async def test_it(client, instrument_name: str):
    ## 1. REST API

    subaccounts = client.http.get_subaccounts()
    subaccount_id = subaccounts.subaccount_ids[0]

    # lazy session, ergonomic one-off call (session created on demand)
    http_ticker = client.http.get_ticker(instrument_name=instrument_name)
    http_orders = client.http.get_orders(subaccount_id=subaccount_id)

    # batch sync HTTP calls: use context manager to reuse a session and ensure deterministic close
    with client.http as http:
        http_ticker = http.get_ticker(instrument_name=instrument_name)
        http_orders = client.http.get_orders(subaccount_id=subaccount_id)

    # async HTTP: ergonomic one-off call (auto-open if needed; use open() or context manager for batch/low-latency)
    aio_ticker = await client.aio.get_ticker(instrument_name=instrument_name)
    aio_orders = await client.aio.get_orders(subaccount_id=subaccount_id)

    # async HTTP session managed by context: preferred for batch usage (pre-open, auto-close on exit)
    async with client.aio as aio:
        aio_ticker = await aio.get_ticker(instrument_name=instrument_name)
        aio_orders = await client.aio.get_orders(subaccount_id=subaccount_id)

    # 2. Websocket API

    # 2A. WebSocket RPC

    # explicit connect/disconnect for manual control across multiple operations
    await client.ws.connect()
    await client.ws.login()
    ws_ticker = await client.ws.rpc.get_ticker(instrument_name=instrument_name)
    subaccounts = await client.ws.rpc.get_subaccounts()
    subaccount_id = subaccounts.subaccount_ids[0]
    ws_ticker = await client.ws.rpc.get_ticker(instrument_name=instrument_name)
    ws_orders = await client.ws.rpc.get_orders(subaccount_id=subaccount_id)
    await client.ws.disconnect()

    # context-managed WS: connect, login, perform RPC, then auto-disconnect
    async with client.ws as ws:  # connect and login
        ws_ticker = await ws.rpc.get_ticker(instrument_name=instrument_name)
        ws_orders = await ws.rpc.get_orders(subaccount_id=subaccount_id)

    ## 2B. Channels

    # explicit stream opening / closing for manual control
    async with client.ws as ws:  # connect and login
        # public
        ticker_stream = ws.channels.ticker_iterator(instrument_name=instrument_name)  # lazy stream creation
        await ticker_stream.open()
        async for msg in ticker_stream:
            logger.info(f"Ticker timestamp: {msg.timestamp}")
            break
        await ticker_stream.close()

        # # private
        # orders_stream = ws.channels.orders(subaccount_id=subaccount_id)
        # await orders_stream.open()
        # logger.info("Orders OPEN!")
        # async for msg in orders_stream:
        #     logger.info(f"Orders timestamp: {msg.timestamp}")
        #     break
        # await orders_stream.close()

    # WebSocket session managed by context
    async with client.ws as ws:  # connect and login
        ticker_stream = ws.channels.ticker_iterator(instrument_name=instrument_name)  # lazy stream creation
        async with ticker_stream as ticker_sub:  # open subscription
            async for msg in ticker_sub:
                logger.info(f"Ticker timestamp: {msg.timestamp}")
                break

    # multiple consumer
    async with client.ws as ws:
        stream1 = ws.channels.ticker_iterator(instrument_name=instrument_name)
        stream2 = ws.channels.ticker_iterator(instrument_name=instrument_name)

        async with stream1 as sub1:  # open subscription 1
            async with stream2 as sub2:  # open subscription 2
                async for msg in sub1:
                    logger.info(f"Ticker timestamp: {msg.timestamp}")
                    break
                async for msg in sub2:
                    logger.info(f"Ticker timestamp: {msg.timestamp}")
                    break
                logger.info(f"Subscription consumers: {subscription_consumers(ws)}")
            logger.info(f"Subscription consumers: {subscription_consumers(ws)}")
        logger.info(f"Subscription consumers: {subscription_consumers(ws)}")


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
        return await test_it(client, instrument_name)

    asyncio.run(_run())
