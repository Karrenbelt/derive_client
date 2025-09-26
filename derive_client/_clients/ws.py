from __future__ import annotations

import asyncio
import json
import uuid
import weakref
from enum import Enum
from typing import Any

import aiohttp
from pydantic import BaseModel

from derive_client._clients.models import (
    PublicGetTickerResultSchema,
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


class WsConnectionError(ConnectionError):
    """"""


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    CLOSED = "closed"


class WsClient:
    """WebSocket client - ALWAYS async (as it should be!)"""

    def __init__(self, ws_address: str):
        self.ws_address = ws_address

        # lazy: create on connect
        self._connector: aiohttp.TCPConnector | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._message_task: asyncio.Task | None = None

        self._refcount = 0
        self._idle_timeout = 0.0
        self._idle_task: asyncio.Task | None = None

        self._closing = False

        self._request_futures: dict[str, asyncio.Future] = {}
        self._request_timeout = 1

        self._subscriptions: dict[str, set[asyncio.Queue]] = {}
        self._notifications: asyncio.Queue = asyncio.Queue(maxsize=1000)

        self._connection_lock = asyncio.Lock()
        self._futures_lock = asyncio.Lock()
        self._subscriptions_lock = asyncio.Lock()

        self._finalizer = weakref.finalize(self, self._cleanup)

    async def _ensure_connected(self):
        """Lazy connection with aiohttp built-ins"""

        # quick optimistic check to avoid acquiring the lock unnecessarily
        if self._ws and not self._ws.closed:
            return

        async with self._connection_lock:
            # double-check after acquiring the lock to prevent TOCTOU vulnerability
            if self._ws and not self._ws.closed:
                return

            if self._session is None or self._session.closed:
                self._connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=10,
                    keepalive_timeout=30,
                    enable_cleanup_closed=True,
                )
                self._session = aiohttp.ClientSession(connector=self._connector)

            # headers = {"Authorization": f"Bearer {self.session_key}"} if self.session_key else None
            headers = None
            self._ws = await self._session.ws_connect(
                self.ws_address,
                timeout=aiohttp.ClientTimeout(total=60),
                heartbeat=30,
                autoping=True,
                max_msg_size=MAX_MSG_SIZE,
                headers=headers,
            )

            if not self._message_task or self._message_task.done():
                self._message_task = asyncio.create_task(self._message_loop())

    async def _send_request(self, method: str, params: dict, *, timeout: float | None = None) -> Any:
        await self._ensure_connected()
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
        try:
            self._notifications.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("Notification queue full, dropping message: %s", message)
        logger.info("Notification: %s", message)

    async def _handle_message(self, message: dict[str, Any]):
        """Route messages to waiting requests"""

        if "id" in message:
            await self._handle_response(message)
        elif message.get("method") == "subscription":
            await self._handle_subscription(message)
        else:
            await self._handle_notification(message)

    async def _cleanup_pending_requests(self):
        """Fail all pending requests when connection dies"""

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
                    future.set_exception(WsConnectionError("WebSocket connection lost"))
                except asyncio.InvalidStateError:
                    # Rare race: the future completed between the check and set_exception
                    logger.debug("Future already done during cleanup")

    async def __aenter__(self):
        """Enter context manager"""

        await self._ensure_connected()
        async with self._connection_lock:
            # If we've scheduled an idle-close, cancel it because someone re-entered
            if self._idle_task and not self._idle_task.done():
                self._idle_task.cancel()
                self._idle_task = None
            self._refcount += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager"""

        if exc_type not in (None, GeneratorExit, asyncio.CancelledError):
            logger.error("Context manager exiting due to %s: %s", exc_type.__name__, exc_val)

        close_now = False
        async with self._connection_lock:
            self._refcount = max(0, self._refcount - 1)
            if self._refcount == 0:
                if self._idle_timeout <= 0:
                    # immediate close-if-unused (do not spawn a task)
                    close_now = True
                else:
                    loop = asyncio.get_running_loop()
                    # if there's already an idle task, cancel and replace it (defensive)
                    if self._idle_task and not self._idle_task.done():
                        self._idle_task.cancel()
                    self._idle_task = loop.create_task(self._idle_close(self._idle_timeout))

        if close_now:
            await self.close(force=close_now)

    async def _idle_close(self, delay: float):
        """Close after delay if refcount still zero."""

        try:
            await asyncio.sleep(delay)
            # check refcount under lock but call close outside
            async with self._connection_lock:
                should_close = self._refcount == 0
            if should_close:
                await self.close(force=False)
        except asyncio.CancelledError:
            # cancelled because someone re-entered
            return

    async def close(self, force: bool = True):
        """Explicit cleanup"""

        async with self._connection_lock:
            if self._closing:
                return
            if not force and self._refcount > 0:
                return

            self._closing = True

            if self._idle_task and not self._idle_task.done():
                self._idle_task.cancel()
                self._idle_task = None

            # snapshot and clear instance refs while holding the lock
            ws = self._ws
            session = self._session
            connector = self._connector
            message_task = self._message_task

            self._ws = None
            self._session = None
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
        self._closing = False

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
        """
        Remove a local consumer queue. If there are no more local consumers,
        unsubscribe from server.
        """
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

    def _cleanup(self):
        """Synchronous cleanup for finalizer"""

        # do not schedule async work from a finalizer!
        # may run at any time, event loop may not be running -> async task fails silently
        if self._session and not self._session.closed:
            logger.warning(
                f"{self.__class__.__name__} client was garbage collected without explicit close(). "
                "Use 'async with' or call close() explicitly to ensure proper cleanup."
            )


class Channel:
    """Async iterable for a subscription."""

    def __init__(self, ws: WsClient, channel: str, key: str, schema: BaseModel):
        self._ws = ws
        self._channel = channel
        self._queue = asyncio.Queue(maxsize=1000)
        self._key = key
        self._schema = schema

        self._open: bool = False
        self._closed_event = asyncio.Event()
        self._lock = asyncio.Lock()

        self._finalizer = weakref.finalize(self, self._cleanup)

    async def open(self) -> None:
        """Idempotent attach. Waits for server subscribe to succeed."""

        if self._open:
            return

        async with self._lock:
            if self._open:
                return
            # register with WsClient which does subscribe-on-first-consumer
            await self._ws._attach_channel(self._channel, self._queue)
            self._open = True
            self._closed_event.clear()

    async def close(self) -> None:
        """Idempotent detach and stop iteration. Unblocks waiting readers."""

        if not self._open and self._closed_event.is_set():
            return

        async with self._lock:
            if not self._open and self._closed_event.is_set():
                return

            self._open = False
            self._closed_event.set()

            # detach: unregister local queue and possibly unsubscribe server-side
            try:
                await self._ws._detach_channel(self._channel, self._queue)
            except Exception:
                logger.debug("Detach/Unsubscribe failed for %s (ignored)", self._channel)

            # put sentinel to unblock any waiting __anext__ consumer(s)
            # Use non-blocking put_nowait; if queue full, that's OK: consumer will still read previous messages
            try:
                self._queue.put_nowait(_CLOSE_SENTINEL)
            except asyncio.QueueFull:
                logger.debug("Queue full when closing channel %s; sentinel not enqueued", self._channel)

    def __aiter__(self):
        return self

    async def __aenter__(self) -> Channel:
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def __anext__(self):
        """Return next parsed item from the channel. Stop iteration when channel is closed."""

        if self._closed_event.is_set():
            raise StopAsyncIteration

        while True:
            try:
                message = await self._queue.get()
            except asyncio.CancelledError:
                raise

            if message is _CLOSE_SENTINEL:
                raise StopAsyncIteration

            payload = message.get(self._key) if isinstance(message, dict) else message
            try:
                return self._schema(**payload)
            except Exception:
                logger.exception("Failed to parse payload from channel %s: %s", self._channel, payload)

    def _cleanup(self):
        if self._open:
            msg = "Channel %s was garbage-collected while still open. Call await channel.close() or use 'async with'."
            logger.warning(msg, self._channel)


class WsRPC:
    def __init__(self, ws: WsClient):
        self._ws = ws

    async def get_ticker(self, instrument_name: str):
        message = await self._ws._send_request("public/get_ticker", {"instrument_name": instrument_name})
        return try_cast_response(message, PublicGetTickerResultSchema)


class WsChannels:
    def __init__(self, ws: WsClient):
        self._ws = ws

    def ticker(self, instrument_name: str, interval: int = 1000) -> Channel:
        channel = f"ticker.{instrument_name}.{interval}"
        return Channel(
            ws=self._ws,
            channel=channel,
            key="instrument_ticker",
            schema=PublicGetTickerResultSchema,
        )


class DeriveWsClient:
    def __init__(self, wallet: Address, session_key: str, env: Environment):
        self.wallet = wallet
        self.session_key = session_key
        self.config = CONFIGS[env]

        self._ws = WsClient(self.config.ws_address)
        self.rpc = WsRPC(self._ws)
        self.channels = WsChannels(self._ws)

    @property
    def endpoints(self):
        return EndPoints(self.config.base_url)

    async def __aenter__(self):
        """Enter context manager"""
        await self._ws.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Enter context manager"""
        await self._ws.__aexit__(exc_type, exc_val, exc_tb)

    async def close(self, force: bool = True):
        await self._ws.close(force=force)
