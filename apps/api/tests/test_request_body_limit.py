from __future__ import annotations

import asyncio
import json
import unittest
from collections import deque

from fastapi import FastAPI, Request, Response

from app.request_body_limit import RequestBodyLimitMiddleware


class _BodyReaderApp:
    def __init__(self) -> None:
        self.calls = 0
        self.body: bytes | None = None

    async def __call__(self, scope, receive, send) -> None:
        del scope
        self.calls += 1
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        self.body = b"".join(chunks)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


async def _run_request(
    app,
    *,
    headers: list[tuple[bytes, bytes]],
    chunks: list[bytes],
) -> list[dict]:
    request_messages = deque(
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    )
    sent: list[dict] = []

    async def receive() -> dict:
        if request_messages:
            return request_messages.popleft()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/upload",
        "raw_path": b"/upload",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("198.51.100.10", 42000),
        "server": ("example.test", 443),
        "state": {},
    }
    await app(scope, receive, send)
    return sent


def _response(sent: list[dict]) -> tuple[int, dict, dict[str, str]]:
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in start.get("headers", [])
    }
    return start["status"], json.loads(body) if body else {}, headers


class RequestBodyLimitTests(unittest.TestCase):
    def _middleware(self, downstream: _BodyReaderApp) -> RequestBodyLimitMiddleware:
        return RequestBodyLimitMiddleware(
            downstream,
            max_body_bytes=8,
            request_id_header="X-Request-ID",
        )

    def test_declared_oversized_body_is_rejected_before_downstream(self) -> None:
        downstream = _BodyReaderApp()
        sent = asyncio.run(
            _run_request(
                self._middleware(downstream),
                headers=[
                    (b"content-length", b"9"),
                    (b"x-request-id", b"phase-5-fixed"),
                ],
                chunks=[b"123456789"],
            )
        )

        status_code, payload, headers = _response(sent)
        self.assertEqual(status_code, 413)
        self.assertEqual(payload["detail"], "Request body is too large")
        self.assertEqual(payload["code"], "request_body_too_large")
        self.assertEqual(payload["request_id"], "phase-5-fixed")
        self.assertEqual(headers["x-request-id"], "phase-5-fixed")
        self.assertEqual(downstream.calls, 0)

    def test_invalid_content_length_keeps_existing_bad_request_contract(self) -> None:
        downstream = _BodyReaderApp()
        sent = asyncio.run(
            _run_request(
                self._middleware(downstream),
                headers=[
                    (b"content-length", b"not-a-number"),
                    (b"x-request-id", b"phase-5-invalid"),
                ],
                chunks=[b"1234"],
            )
        )

        status_code, payload, headers = _response(sent)
        self.assertEqual(status_code, 400)
        self.assertEqual(payload["detail"], "Invalid Content-Length header")
        self.assertEqual(payload["code"], "invalid_content_length")
        self.assertEqual(payload["request_id"], "phase-5-invalid")
        self.assertEqual(headers["x-request-id"], "phase-5-invalid")
        self.assertEqual(downstream.calls, 0)

    def test_chunked_oversized_body_without_content_length_is_rejected(self) -> None:
        downstream = _BodyReaderApp()
        sent = asyncio.run(
            _run_request(
                self._middleware(downstream),
                headers=[(b"x-request-id", b"phase-5-chunked")],
                chunks=[b"1234", b"5678", b"9"],
            )
        )

        status_code, payload, _headers = _response(sent)
        self.assertEqual(status_code, 413)
        self.assertEqual(payload["code"], "request_body_too_large")
        self.assertEqual(payload["request_id"], "phase-5-chunked")
        self.assertEqual(downstream.calls, 1)
        self.assertIsNone(downstream.body)

    def test_understated_content_length_cannot_bypass_stream_limit(self) -> None:
        downstream = _BodyReaderApp()
        sent = asyncio.run(
            _run_request(
                self._middleware(downstream),
                headers=[(b"content-length", b"4")],
                chunks=[b"1234", b"56789"],
            )
        )

        status_code, payload, _headers = _response(sent)
        self.assertEqual(status_code, 413)
        self.assertEqual(payload["code"], "request_body_too_large")
        self.assertIsNone(downstream.body)

    def test_bounded_chunked_body_is_forwarded_unchanged(self) -> None:
        downstream = _BodyReaderApp()
        sent = asyncio.run(
            _run_request(
                self._middleware(downstream),
                headers=[],
                chunks=[b"12", b"345", b"678"],
            )
        )

        status_code, payload, _headers = _response(sent)
        self.assertEqual(status_code, 204)
        self.assertEqual(payload, {})
        self.assertEqual(downstream.body, b"12345678")

    def test_bounded_fixed_length_body_is_forwarded_unchanged(self) -> None:
        downstream = _BodyReaderApp()
        sent = asyncio.run(
            _run_request(
                self._middleware(downstream),
                headers=[(b"content-length", b"8")],
                chunks=[b"12345678"],
            )
        )

        status_code, _payload, _headers = _response(sent)
        self.assertEqual(status_code, 204)
        self.assertEqual(downstream.body, b"12345678")

    def test_chunked_limit_wraps_existing_http_middleware_stack(self) -> None:
        received_bodies: list[bytes] = []
        test_app = FastAPI()

        @test_app.middleware("http")
        async def pass_through_guard(request: Request, call_next):
            return await call_next(request)

        @test_app.post("/upload")
        async def upload(request: Request) -> Response:
            received_bodies.append(await request.body())
            return Response(status_code=204)

        test_app.add_middleware(
            RequestBodyLimitMiddleware,
            max_body_bytes=8,
            request_id_header="X-Request-ID",
        )
        sent = asyncio.run(
            _run_request(
                test_app,
                headers=[],
                chunks=[b"1234", b"5678", b"9"],
            )
        )

        status_code, payload, _headers = _response(sent)
        self.assertEqual(status_code, 413)
        self.assertEqual(payload["code"], "request_body_too_large")
        self.assertEqual(received_bodies, [])


if __name__ == "__main__":
    unittest.main()
