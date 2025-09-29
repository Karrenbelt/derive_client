from __future__ import annotations

import asyncio
import json
import uuid
import weakref
from typing import Any, AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

import aiohttp
from pydantic import BaseModel
from web3 import AsyncWeb3
from derive_action_signing.utils import sign_ws_login

from derive_client._clients.models import (
    PublicGetTickerResultSchema,
    PrivateGetSubaccountsResultSchema,
    PrivateGetOrdersResultSchema,
    PublicLoginResponseSchema,
)
from derive_client.constants import CONFIGS
from derive_client.data_types import Address, Environment
from derive_client.endpoints import RestAPI as EndPoints
from derive_client._clients.utils import try_cast_response
from derive_client._clients.logger import logger


_CLOSE_SENTINEL = object()
MAX_MSG_SIZE = 4 * 1024 * 1024  # 4MiB


def wire_size_bytes(obj) -> int:
    """Return number of bytes the JSON encoding will use (utf-8)."""
    # Use orjson if available (much faster and often more compact for floats/decimals)
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


class WebSocketConnectionError(ConnectionError):
    """WebSocketConnectionError"""


class WebSocketSession:
    """WebSocket Session"""

    def __init__(self, ws_address: str):
        self.ws_address = ws_address

        # lazy: create on connect
        self._connector: aiohttp.TCPConnector | None = None
        self._aiohttp_session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._message_task: asyncio.Task | None = None

        self._refcount = 0
        self._idle_cleanup_timeout = 0.0
        self._idle_cleanup_task: asyncio.Task | None = None

        self._request_futures: dict[str, asyncio.Future] = {}
        self._request_timeout = 1

        self._subscriptions: dict[str, set[asyncio.Queue]] = {}
        self._notifications: asyncio.Queue = asyncio.Queue(maxsize=1000)

        self._connection_lock = asyncio.Lock()
        self._futures_lock = asyncio.Lock()
        self._subscriptions_lock = asyncio.Lock()

        self._finalizer = weakref.finalize(self, self._finalize)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def connect(self):
        """Lazy connection with aiohttp built-ins"""

        async with self._connection_lock:
            if self.is_connected:
                self._refcount += 1
                # cancel pending idle close if any
                if self._idle_cleanup_task and not self._idle_cleanup_task.done():
                    self._idle_cleanup_task.cancel()
                    self._idle_cleanup_task = None
                return

            if self._aiohttp_session is None or self._aiohttp_session.closed:
                self._connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=10,
                    keepalive_timeout=30,
                    enable_cleanup_closed=True,
                )
                self._aiohttp_session = aiohttp.ClientSession(connector=self._connector)

            try:
                self._ws = await self._aiohttp_session.ws_connect(
                    self.ws_address,
                    timeout=aiohttp.ClientTimeout(total=60),
                    heartbeat=30,
                    autoping=True,
                    max_msg_size=MAX_MSG_SIZE,
                )
                if not self._message_task or self._message_task.done():
                    self._message_task = asyncio.create_task(self._message_loop())
                self._refcount += 1

            except Exception:
                if self._aiohttp_session and not self._aiohttp_session.closed:
                    await self._aiohttp_session.close()
                if self._connector and not self._connector.closed:
                    await self._connector.close()
                self._aiohttp_session = None
                self._connector = None
                raise

    async def disconnect(self, force: bool = False):
        """Disconnect: decrement reference count and cleanup"""

        # no optimistic check: because network can drop, we must always acquire the lock
        async with self._connection_lock:
            self._refcount = max(0, self._refcount - 1)

            if not force and self._refcount > 0:
                return

            if not self.is_connected:
                return

            # cancel any pending idle cleanup
            if self._idle_cleanup_task and not self._idle_cleanup_task.done():
                self._idle_cleanup_task.cancel()
                self._idle_cleanup_task = None

            should_cleanup_now = force or self._idle_cleanup_timeout <= 0

        if should_cleanup_now:
            await self._cleanup()
        else:
            loop = asyncio.get_running_loop()
            self._idle_cleanup_task = loop.create_task(self._cleanup_after_delay(self._idle_cleanup_timeout))

    async def _cleanup_after_delay(self, delay: float):
        """Sleep then cleanup if refcount still zero."""

        try:
            await asyncio.sleep(delay)
            # check refcount under lock but call cleanup outside
            async with self._connection_lock:
                should_cleanup = self._refcount == 0 and self.is_connected
            if should_cleanup:
                await self._cleanup()
        except asyncio.CancelledError:
            # cancelled because someone re-entered
            return

    async def _cleanup(self):
        """Cleanup resources"""

        # snapshot and clear instance refs while holding the lock
        async with self._connection_lock:
            ws = self._ws
            session = self._aiohttp_session
            connector = self._connector
            message_task = self._message_task

            self._ws = None
            self._aiohttp_session = None
            self._connector = None
            self._message_task = None
            self._refcount = 0

        if message_task and not message_task.done():
            message_task.cancel()
            try:
                await message_task
            except asyncio.CancelledError:
                pass

        if ws and not ws.closed:
            try:
                await ws.close()
            except Exception:
                logger.exception("Error closing websocket")

        # websocket does not own the session
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

        await self._cleanup_pending_requests()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def _send_request(
        self,
        method: str,
        params: dict,
        *,
        timeout: float | None = None,
    ) -> Any:
        if not self.is_connected:
            raise RuntimeError("WebSocket not connected. Call await .connect() or use 'async with' before making RPCs.")

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        async with self._futures_lock:
            self._request_futures[request_id] = future

        message = {"method": method, "params": params, "id": request_id}
        try:
            await self._ws.send_str(json.dumps(message))
        except Exception as exc:
            async with self._futures_lock:
                future = self._request_futures.get(request_id)
            if future and not future.done():
                future.set_exception(exc)
            raise

        try:
            wait_timeout = timeout or self._request_timeout
            result = await asyncio.wait_for(future, timeout=wait_timeout)
            return result
        except (asyncio.TimeoutError, asyncio.CancelledError):
            async with self._futures_lock:
                future = self._request_futures.get(request_id)
            if future and not future.done():
                future.cancel()
            raise
        finally:
            async with self._futures_lock:
                self._request_futures.pop(request_id, None)

    async def _message_loop(self):
        """Background task: listen for ALL incoming messages"""

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.PING:
                    logger.debug("Received PING")
                elif msg.type == aiohttp.WSMsgType.PONG:
                    logger.debug("Received PONG")
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    message = json.loads(msg.data)  # orjson
                    await self._handle_message(message)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    try:
                        message = json.loads(msg.data.decode("utf-8"))
                        await self._handle_message(message)
                    except Exception:
                        # may try: message = msgpack.loads(msg.data, raw=False)
                        logger.warning("Unhandled BINARY message (not utf8/json); len=%d", len(msg.data))
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                    logger.info("WebSocket closing/closed: %s", msg.type)
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {self._ws.exception()}")
                    break
                else:
                    # should not get CONTINUATION because the library reassembles fragments and yields complete messages
                    logger.warning("Unhandled WS message type: %s", msg.type)
        except Exception as e:
            logger.error(f"Message loop error: {e}")
        finally:
            await self._cleanup_pending_requests()
            if self._ws and not self._ws.closed:
                await self._ws.close()

    async def _handle_response(self, message: dict[str, Any]):
        """Handle RPC responses."""

        request_id = message["id"]

        async with self._futures_lock:
            future = self._request_futures.get(request_id)

        if not future:
            logger.debug("No future found for id %s; ignoring message", request_id)
            return

        if not future.done():
            try:
                future.set_result(message)
            except asyncio.InvalidStateError:
                logger.debug("Race completing future %s: already done", request_id)

        async with self._futures_lock:
            future = self._request_futures.pop(request_id, None)

    async def _handle_subscription(self, message: dict[str, Any]):
        """Handle subscription messages."""

        params = message.get("params", {})
        channel = params.get("channel")
        data = params.get("data")

        async with self._subscriptions_lock:
            queues = list(self._subscriptions.get(channel))

        if not queues:
            logger.debug("No subscription queues for channel %s; dropping message", channel)
            return

        for q in queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning("Subscription queue full for %s; dropping message", channel)

    async def _handle_notification(self, message: dict[str, Any]):
        """Handle notification messages."""

        try:
            self._notifications.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("Notification queue full, dropping message: %s", message)
        logger.info("Notification: %s", message)

    async def _handle_message(self, message: dict[str, Any]):
        """Route messages to their respecitve handler."""

        if "id" in message:
            await self._handle_response(message)
        elif message.get("method") == "subscription":
            await self._handle_subscription(message)
        else:
            await self._handle_notification(message)

    async def _cleanup_pending_requests(self):
        """Fail all pending requests when connection dies."""

        # prevents `RuntimeError: dict changed size during iteration`
        async with self._futures_lock:
            futures = list(self._request_futures.values())
            self._request_futures.clear()

        # `future.set_exception()` runs future callbacks synchronously on the event loop
        # Those callbacks are user-controlled and may do arbitrary work;
        # running them while holding `_futures_lock` can deadlock
        for future in futures:
            if not future.done():
                try:
                    future.set_exception(WebSocketConnectionError("WebSocket connection lost"))
                except asyncio.InvalidStateError:
                    # Rare race: the future completed between the check and set_exception
                    logger.debug("Future already done during cleanup")

    async def _attach_channel(self, channel: str, queue: asyncio.Queue) -> None:
        """
        Register a local queue as a consumer for 'channel'.
        If this is the first local consumer, send the subscribe RPC to server.
        """
        need_subscribe = False
        async with self._subscriptions_lock:
            s = self._subscriptions.get(channel)
            if s is None:
                s = set()
                self._subscriptions[channel] = s
                need_subscribe = True
            s.add(queue)

        if need_subscribe:
            try:
                # send subscribe to server (await confirmation from server-side RPC)
                await self._send_request("subscribe", {"channels": [channel]})
            except Exception:
                # rollback on failure
                async with self._subscriptions_lock:
                    s = self._subscriptions.get(channel)
                    if s:
                        s.discard(queue)
                        if not s:
                            self._subscriptions.pop(channel, None)
                raise

    async def _detach_channel(self, channel: str, queue: asyncio.Queue) -> None:
        """Remove a local consumer queue. If there are no more local consumers, unsubscribe from server."""

        need_unsubscribe = False
        async with self._subscriptions_lock:
            s = self._subscriptions.get(channel)
            if not s:
                return
            s.discard(queue)
            if not s:
                # last local consumer removed
                self._subscriptions.pop(channel, None)
                need_unsubscribe = True

        if need_unsubscribe:
            # best-effort: don't hold lock while awaiting _send_request
            try:
                await self._send_request("unsubscribe", {"channels": [channel]})
            except Exception:
                # log and ignore; we've already removed local state
                logger.debug("unsubscribe failed for %s", channel)

    def _finalize(self):
        """Synchronous finalizer."""

        # do not schedule async work from a finalizer!
        # may run at any time, event loop may not be running -> async task fails silently
        if self._aiohttp_session and not self._aiohttp_session.closed:
            logger.warning(
                f"{self.__class__.__name__} client was garbage collected without explicit close(). "
                "Use 'async with' or call close() explicitly to ensure proper cleanup."
            )


class Subscription:
    """Async iterable for a subscription."""

    def __init__(self, session: WebSocketSession, channel: str, key: str, schema: BaseModel):
        self._session = session
        self._channel = channel
        self._queue: asyncio.Queue | None = None
        self._key = key
        self._schema = schema
        self._lock = asyncio.Lock()

    @property
    def active(self):
        return self._queue is not None

    async def open(self):
        async with self._lock:
            if self.active:
                return

            self._queue = asyncio.Queue(maxsize=1000)
            await self._session._attach_channel(self._channel, self._queue)

    async def close(self):
        if not self.active:
            return

        async with self._lock:
            if not self.active:
                return

            if self._queue:
                await self._session._detach_channel(self._channel, self._queue)
            self._queue = None

    def __aiter__(self) -> AsyncIterator:
        return self

    async def __anext__(self):
        if not self.active:
            raise RuntimeError("Subscription not active. Call await .open() or use 'async with' before streaming.")

        try:
            message = await self._queue.get()
            payload = message.get(self._key, message)
            return self._schema(**payload)
        except asyncio.CancelledError:
            await self.close()
            raise

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


class WebSocketRPC:
    """Facade for WebSocket RPC endpoints."""

    def __init__(self, ws: WebSocketClient):
        self.ws = ws

    async def get_ticker(self, instrument_name: str) -> PublicGetTickerResultSchema:
        params = {"instrument_name": instrument_name}
        message = await self.ws._session._send_request("public/get_ticker", params)
        return try_cast_response(message, PublicGetTickerResultSchema)

    async def login(self):
        params = sign_ws_login(
            web3_client=self.ws.w3,
            smart_contract_wallet=self.ws.wallet,
            session_key_or_wallet_private_key=self.ws.account.key,
        )
        message = await self.ws._session._send_request("public/login", params)
        return PublicLoginResponseSchema(**message)

    async def get_subaccounts(self) -> PrivateGetSubaccountsResultSchema:
        params = {"wallet": self.ws.wallet}
        message = await self.ws._session._send_request("private/get_subaccounts", params)
        return try_cast_response(message, PrivateGetSubaccountsResultSchema)

    async def get_orders(self, subaccount_id: int, **kwargs) -> PrivateGetOrdersResultSchema:
        params = {"subaccount_id": subaccount_id, **kwargs}
        message = await self.ws._session._send_request("private/get_orders", params)
        return try_cast_response(message, PrivateGetOrdersResultSchema)


class WebSocketChannels:
    """Facade for WebSocket channels."""

    def __init__(self, ws: WebSocketClient):
        self.ws = ws

    @asynccontextmanager
    async def ticker_generator(
        self,
        instrument_name: str,
        interval: int = 1000,
    ) -> AsyncGenerator[PublicGetTickerResultSchema, None]:
        channel = f"ticker.{instrument_name}.{interval}"
        queue = asyncio.Queue(maxsize=1000)

        try:
            await self.ws._session._attach_channel(channel, queue)

            async def stream():
                while True:
                    message = await queue.get()
                    payload = message.get("instrument_ticker", message)
                    yield PublicGetTickerResultSchema(**payload)

            yield stream()

        finally:
            await self.ws._session._detach_channel(channel, queue)

    def ticker_iterator(self, instrument_name: str, interval: int = 1000) -> Subscription:
        channel = f"ticker.{instrument_name}.{interval}"
        return Subscription(
            session=self.ws._session,
            channel=channel,
            key="instrument_ticker",
            schema=PublicGetTickerResultSchema,
        )

    def orders(self, subaccount_id: int) -> Subscription:
        channel = f"{subaccount_id}.orders"
        return Subscription(
            session=self.ws._session,
            channel=channel,
            key="instrument_ticker",
            schema=PrivateGetOrdersResultSchema,
        )


class WebSocketClient:
    """WebSocket client - ALWAYS async (as it should be!)"""

    def __init__(self, wallet: Address, session_key: str, env: Environment):
        self.wallet = wallet
        self.session_key = session_key
        self.config = CONFIGS[env]
        self.w3 = AsyncWeb3(AsyncWeb3.HTTPProvider(self.config.rpc_endpoint))
        self.account = self.w3.eth.account.from_key(session_key)

        self._session = WebSocketSession(self.config.ws_address)
        self.rpc = WebSocketRPC(self)
        self.channels = WebSocketChannels(self)

    @property
    def endpoints(self):
        return EndPoints(self.config.base_url)

    async def connect(self):
        await self._session.connect()

    async def disconnect(self, force: bool = True):
        await self._session.disconnect(force=force)

    async def login(self):
        await self.rpc.login()

    async def __aenter__(self):
        """Enter context manager"""
        await self._session.__aenter__()
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Enter context manager"""
        await self._session.__aexit__(exc_type, exc_val, exc_tb)
