from __future__ import annotations

import ipaddress
import ssl
from typing import AsyncIterator

import httpcore
import httpx


class PinnedWebhookBackend(httpcore.AsyncNetworkBackend):
    """Connect only to vetted literal IPs; preserve the original TLS hostname."""

    def __init__(self, hostname: str, addresses: set[str], port: int = 443, *, backend=None) -> None:
        self.hostname = hostname.encode("idna").decode("ascii").lower()
        self.port = port
        self.addresses = frozenset(str(ipaddress.ip_address(item)) for item in addresses)
        if not self.addresses or any(not ipaddress.ip_address(item).is_global for item in self.addresses):
            raise ValueError("Webhook requires vetted public addresses")
        self.backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(self, host: str, port: int, timeout=None, local_address=None, socket_options=None):
        if host.lower() != self.hostname or port != self.port:
            raise httpcore.ConnectError("Webhook destination changed")
        last_error = None
        for address in sorted(self.addresses):
            try:
                stream = await self.backend.connect_tcp(address, port, timeout=timeout,
                    local_address=local_address, socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
                continue
            try:
                peer = stream.get_extra_info("server_addr")
                accepted = bool(peer) and str(ipaddress.ip_address(peer[0])) in self.addresses
            except Exception:
                accepted = False
            if not accepted:
                await stream.aclose()
                raise httpcore.ConnectError("Webhook peer is unavailable or not vetted")
            return stream
        raise httpcore.ConnectError("Vetted webhook destination is unreachable") from last_error

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("Webhook Unix sockets are forbidden")

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream) -> None:
        self.stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self.stream:
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()


class PinnedWebhookTransport(httpx.AsyncBaseTransport):
    def __init__(self, hostname: str, addresses: set[str], port: int = 443) -> None:
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), max_connections=1,
            max_keepalive_connections=0, retries=0,
            network_backend=PinnedWebhookBackend(hostname, addresses, port),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.pool.handle_async_request(httpcore.Request(
            method=request.method, url=httpcore.URL(scheme=request.url.raw_scheme,
                host=request.url.raw_host, port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=request.extensions,
        ))
        return httpx.Response(response.status, headers=response.headers,
            stream=_ResponseStream(response.stream), extensions=response.extensions)

    async def aclose(self) -> None:
        await self.pool.aclose()
