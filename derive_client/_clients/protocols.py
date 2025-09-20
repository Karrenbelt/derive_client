"""
Protocol definitions for derive client with consistent naming conventions
"""

from typing import AsyncGenerator, Protocol, runtime_checkable

from derive_client._clients.models import PublicGetTickerResultSchema


@runtime_checkable
class HTTPProtocol(Protocol):
    """Synchronous HTTP client protocol"""

    def get_ticker(self, instrument_name: str) -> PublicGetTickerResultSchema: ...


@runtime_checkable
class AsyncHTTPProtocol(Protocol):
    """Asynchronous HTTP client protocol"""

    async def get_ticker(self, instrument_name: str) -> PublicGetTickerResultSchema: ...


@runtime_checkable
class WSRPCProtocol(Protocol):
    """WebSocket RPC (request-response) protocol"""

    async def get_ticker(self, instrument: str) -> PublicGetTickerResultSchema: ...


@runtime_checkable
class WSSubsProtocol(Protocol):
    """WebSocket subscriptions (streaming) protocol"""

    async def ticker(self, instrument: str) -> AsyncGenerator[PublicGetTickerResultSchema, None]: ...


@runtime_checkable
class WebSocketProtocol(Protocol):
    """Complete WebSocket client protocol combining RPC and subscriptions"""

    @property
    def rpc(self) -> WSRPCProtocol: ...

    @property
    def subs(self) -> WSSubsProtocol: ...

    async def __aenter__(self): ...
    async def __aexit__(self, exc_type, exc_val, exc_tb): ...
    async def close(self) -> None: ...


@runtime_checkable
class DeriveClientProtocol(Protocol):
    """Complete Derive client protocol"""

    @property
    def sync(self) -> HTTPProtocol: ...

    @property
    def aio(self) -> AsyncHTTPProtocol: ...

    @property
    def ws(self) -> WebSocketProtocol: ...
