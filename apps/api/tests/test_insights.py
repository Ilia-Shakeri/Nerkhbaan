from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")


class _HTTPError(Exception):
    pass


class _TimeoutException(_HTTPError):
    pass


class _HTTPStatusError(_HTTPError):
    def __init__(self, response: "_Response") -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _HTTPStatusError(self)

    def json(self) -> dict:
        return self._payload


httpx_stub = types.SimpleNamespace(
    AsyncClient=object,
    HTTPError=_HTTPError,
    HTTPStatusError=_HTTPStatusError,
    TimeoutException=_TimeoutException,
)
sys.modules.setdefault("httpx", httpx_stub)

settings_stub = types.SimpleNamespace(
    groq_api_base_url="https://api.groq.test/openai/v1",
    groq_model="llama3-70b-8192",
    groq_api_key=None,
    insight_api_base_url="https://secondary.test",
    insight_model="secondary-model",
    insight_api_key=None,
    deepseek_api_key=None,
)
sys.modules.setdefault("app.config", types.SimpleNamespace(settings=settings_stub))

from app.services.insights import MarketInsightEngine, ProviderConfig


class _ClientContext:
    def __init__(self, post: AsyncMock) -> None:
        self.post = post

    async def __aenter__(self) -> "_ClientContext":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class InsightFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_uses_secondary_provider(self) -> None:
        success = _Response(
            200, {"choices": [{"message": {"content": "fallback result"}}]}
        )
        post = AsyncMock(side_effect=[_TimeoutException("slow provider"), success])
        providers = [
            ProviderConfig("https://primary.test", "primary-model", "primary-key"),
            ProviderConfig("https://secondary.test", "secondary-model", "secondary-key"),
        ]

        with patch("app.services.insights.httpx.AsyncClient", return_value=_ClientContext(post)):
            result = await MarketInsightEngine()._complete(
                [{"role": "user", "content": "test"}],
                temperature=0.4,
                providers=providers,
            )

        self.assertEqual(result, "fallback result")
        self.assertEqual(post.await_count, 2)
        self.assertEqual(post.await_args_list[1].kwargs["json"]["model"], "secondary-model")

    async def test_http_error_uses_secondary_provider(self) -> None:
        rejected = _Response(503)
        success = _Response(
            200, {"choices": [{"message": {"content": "secondary result"}}]}
        )
        post = AsyncMock(side_effect=[rejected, success])
        providers = [
            ProviderConfig("https://primary.test", "primary-model", "primary-key"),
            ProviderConfig("https://secondary.test", "secondary-model", "secondary-key"),
        ]

        with patch("app.services.insights.httpx.AsyncClient", return_value=_ClientContext(post)):
            result = await MarketInsightEngine()._complete(
                [{"role": "user", "content": "test"}],
                temperature=0.4,
                providers=providers,
            )

        self.assertEqual(result, "secondary result")
        self.assertEqual(post.await_count, 2)


if __name__ == "__main__":
    unittest.main()
