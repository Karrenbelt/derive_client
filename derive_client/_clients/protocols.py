"""
Protocol definitions for derive client with consistent naming conventions
"""

from typing import AsyncIterator, Protocol, runtime_checkable

from derive_client._clients.models import (
    PublicGetTickerParamsSchema,
    PublicGetTickerResultSchema,
    PrivateGetAccountParamsSchema,
    PrivateGetAccountResultSchema,
)


# Place-holders
PrivateBalancesResultSchema = object()
BridgeClientProtocol = object()


# -- Public / Private sub-protocols for HTTP/AsyncHTTP -----------------------


@runtime_checkable
class PublicHTTPProtocol(Protocol):
    """Public synchronous HTTP endpoints."""

    def get_ticker(self, params: PublicGetTickerParamsSchema) -> PublicGetTickerResultSchema: ...


@runtime_checkable
class PrivateHTTPProtocol(Protocol):
    """Private synchronous HTTP endpoints."""

    def get_account(self, params: PrivateGetAccountParamsSchema) -> PrivateGetAccountResultSchema: ...


@runtime_checkable
class PublicAsyncHTTPProtocol(Protocol):
    """Public asynchronous HTTP endpoints."""

    async def get_ticker(self, params: PublicGetTickerParamsSchema) -> PublicGetTickerResultSchema: ...


@runtime_checkable
class PrivateAsyncHTTPProtocol(Protocol):
    """Private asynchronous HTTP endpoints."""

    async def get_account(self, params: PrivateGetAccountParamsSchema) -> PrivateGetAccountResultSchema: ...


# -- WebSocket RPC / Subs namespaced sub-protocols --------------------------


@runtime_checkable
class PublicWSRPCProtocol(Protocol):
    """Public WebSocket RPC methods."""

    async def get_ticker(self, params: PublicGetTickerParamsSchema) -> PublicGetTickerResultSchema: ...


@runtime_checkable
class PrivateWSRPCProtocol(Protocol):
    """Private WebSocket RPC methods."""

    async def get_account(self, params: PrivateGetAccountParamsSchema) -> PrivateGetAccountResultSchema: ...


@runtime_checkable
class PublicWSSubsProtocol(Protocol):
    """Public WebSocket subscription streams."""

    def ticker(self, instrument_name: str, interval: int) -> AsyncIterator[PublicGetTickerResultSchema]: ...


@runtime_checkable
class PrivateWSSubsProtocol(Protocol):
    """Private WebSocket subscription streams."""

    def balances(self, subaccount_id: int) -> AsyncIterator[PrivateBalancesResultSchema]: ...


# -- Composite / facade protocols ------------------------------------------


@runtime_checkable
class HTTPProtocol(Protocol):
    """Facade exposing namespaced synchronous HTTP APIs."""

    @property
    def public(self) -> PublicHTTPProtocol: ...

    @property
    def private(self) -> PrivateHTTPProtocol: ...

    async def __enter__(self): ...
    async def __exit__(self, exc_type, exc_val, exc_tb): ...


@runtime_checkable
class AsyncHTTPProtocol(Protocol):
    """Asynchronous HTTP client protocol."""

    @property
    def public(self) -> PublicAsyncHTTPProtocol: ...

    @property
    def private(self) -> PrivateAsyncHTTPProtocol: ...

    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc_val, exc_tb): ...


@runtime_checkable
class WSRPCProtocol(Protocol):
    """Facade exposing namespaced WebSocket RPC adapters."""

    @property
    def public(self) -> PublicWSRPCProtocol: ...

    @property
    def private(self) -> PrivateWSRPCProtocol: ...


@runtime_checkable
class WSSubsProtocol(Protocol):
    """Facade exposing namespaced WebSocket subscription adapters."""

    @property
    def public(self) -> PublicWSSubsProtocol: ...

    @property
    def private(self) -> PrivateWSSubsProtocol: ...


@runtime_checkable
class WebSocketProtocol(Protocol):
    """Complete WebSocket client protocol combining RPC and subscriptions"""

    @property
    def rpc(self) -> WSRPCProtocol: ...

    @property
    def subs(self) -> WSSubsProtocol: ...

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...

    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc_val, exc_tb): ...
    async def close(self) -> None: ...


# -- Composite protocol ------------------------------------------


@runtime_checkable
class DeriveClientProtocol(Protocol):
    """Complete Derive client protocol"""

    @property
    def sync(self) -> HTTPProtocol: ...

    @property
    def aio(self) -> AsyncHTTPProtocol: ...

    @property
    def ws(self) -> WebSocketProtocol: ...

    @property
    def bridge(self) -> BridgeClientProtocol: ...


# http_ticker = client.http.public.get_ticker(instrument_name=instrument_name)
# aio_ticker = await client.aio.get_ticker(instrument_name=instrument_name)
# ws_ticker = await client.ws.rpc.get_ticker(instrument_name=instrument_name)
# async for ticker in client.ws.subs.ticker(instrument_name=instrument_name):
#     ticker


# def client.http.get_ticker(instrument_name):
#    self.http.public.get_ticker(params: Params)
