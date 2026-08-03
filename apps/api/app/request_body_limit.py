from __future__ import annotations

import re
import uuid

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        request_id_header: str,
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be greater than zero")
        if not request_id_header.strip():
            raise ValueError("request_id_header must not be empty")
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.request_id_header = request_id_header.strip()
        self._request_id_header_bytes = self.request_id_header.lower().encode("latin-1")

    def _request_id(self, scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name.lower() != self._request_id_header_bytes:
                continue
            candidate = value.decode("latin-1")
            if _REQUEST_ID_PATTERN.fullmatch(candidate):
                return candidate
            break
        return uuid.uuid4().hex

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        values = [
            value.strip()
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if not values:
            return None
        if len(set(values)) != 1:
            raise ValueError("conflicting Content-Length headers")
        try:
            content_length = int(values[0].decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("invalid Content-Length header") from exc
        if content_length < 0:
            raise ValueError("invalid Content-Length header")
        return content_length

    async def _send_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        detail: str,
        code: str,
        request_id: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"detail": detail, "code": code, "request_id": request_id},
            headers={self.request_id_header: request_id},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._request_id(scope)
        try:
            content_length = self._content_length(scope)
        except ValueError:
            await self._send_error(
                scope,
                receive,
                send,
                status_code=400,
                detail="Invalid Content-Length header",
                code="invalid_content_length",
                request_id=request_id,
            )
            return
        if content_length is not None and content_length > self.max_body_bytes:
            await self._send_error(
                scope,
                receive,
                send,
                status_code=413,
                detail="Request body is too large",
                code="request_body_too_large",
                request_id=request_id,
            )
            return

        bytes_received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal bytes_received
            message = await receive()
            if message["type"] == "http.request":
                bytes_received += len(message.get("body", b""))
                if bytes_received > self.max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._send_error(
                scope,
                receive,
                send,
                status_code=413,
                detail="Request body is too large",
                code="request_body_too_large",
                request_id=request_id,
            )
