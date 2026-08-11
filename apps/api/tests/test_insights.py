from __future__ import annotations

import os
import types
import unittest
from unittest.mock import AsyncMock, patch

import httpx

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")

from app.services.insights import MarketInsightEngine, ProviderConfig


settings_stub = types.SimpleNamespace(
    ai_provider_order="groq,gemini,openrouter,deepseek",
    groq_api_base_url="https://api.groq.test/openai/v1",
    groq_model="openai/gpt-oss-120b",
    groq_api_key=None,
    gemini_api_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    gemini_model="gemini-3.6-flash",
    gemini_api_key=None,
    insight_api_base_url="https://secondary.test",
    insight_model="secondary-model",
    insight_api_key=None,
    deepseek_api_base_url="https://api.deepseek.com",
    deepseek_model="deepseek-v4-flash",
    deepseek_api_key=None,
    openrouter_api_base_url="https://openrouter.ai/api/v1",
    openrouter_model="openrouter/free",
    openrouter_api_key=None,
    ai_allow_openrouter_free=False,
    ai_request_timeout_seconds=25,
    ai_max_retries=0,
    ai_max_tokens=600,
    ai_global_daily_request_limit=500,
    ai_user_daily_request_limit=20,
    ai_deduplication_window_seconds=15,
)


def response(status_code: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload or {},
        request=httpx.Request("POST", "https://provider.test/chat/completions"),
    )


class _ClientContext:
    def __init__(self, post: AsyncMock) -> None:
        self.post = post

    async def __aenter__(self) -> "_ClientContext":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class InsightFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def complete(self, post: AsyncMock) -> str:
        providers = [
            ProviderConfig("https://primary.test", "primary-model", "primary-key"),
            ProviderConfig("https://secondary.test", "secondary-model", "secondary-key"),
        ]
        with patch("app.services.insights.settings", settings_stub), patch(
            "app.services.insights.httpx.AsyncClient", return_value=_ClientContext(post)
        ):
            return await MarketInsightEngine()._complete(
                [{"role": "user", "content": "test"}],
                temperature=0.4,
                providers=providers,
            )

    async def test_timeout_uses_secondary_provider(self) -> None:
        post = AsyncMock(
            side_effect=[
                httpx.TimeoutException("slow provider"),
                response(200, {"choices": [{"message": {"content": "fallback result"}}]}),
            ]
        )

        result = await self.complete(post)

        self.assertEqual(result, "fallback result")
        self.assertEqual(post.await_count, 2)
        self.assertEqual(post.await_args_list[1].kwargs["json"]["model"], "secondary-model")
        self.assertEqual(post.await_args_list[1].kwargs["json"]["max_tokens"], 600)

    async def test_http_error_uses_secondary_provider(self) -> None:
        post = AsyncMock(
            side_effect=[
                response(503),
                response(200, {"choices": [{"message": {"content": "secondary result"}}]}),
            ]
        )

        result = await self.complete(post)

        self.assertEqual(result, "secondary result")
        self.assertEqual(post.await_count, 2)

    async def test_transport_error_uses_secondary_provider(self) -> None:
        post = AsyncMock(
            side_effect=[
                httpx.TransportError("connection lost"),
                response(200, {"choices": [{"message": {"content": "safe result"}}]}),
            ]
        )

        result = await self.complete(post)

        self.assertEqual(result, "safe result")
        self.assertEqual(post.await_count, 2)

    async def test_invalid_payload_uses_secondary_provider(self) -> None:
        post = AsyncMock(
            side_effect=[
                response(200, {"bad": "shape"}),
                response(200, {"choices": [{"message": {"content": "safe result"}}]}),
            ]
        )

        result = await self.complete(post)

        self.assertEqual(result, "safe result")

    def test_quota_uses_real_user_and_shared_buckets(self) -> None:
        allowed = types.SimpleNamespace(blocked=False)
        with patch("app.services.insights.rate_limit_hit", return_value=allowed) as hit:
            MarketInsightEngine()._check_quota(
                "user-42", [{"role": "user", "content": "gold"}]
            )

        identities = [call.args[1] for call in hit.call_args_list]
        self.assertTrue(any(identity.startswith("user-42:") for identity in identities))
        self.assertIn("user-42", identities)
        self.assertIn("all-users", identities)

    def test_default_provider_order_uses_groq_first(self) -> None:
        with patch("app.services.insights.settings", settings_stub):
            settings_stub.groq_api_key = "groq-key"
            settings_stub.gemini_api_key = "gemini-key"
            engine = MarketInsightEngine()
            settings_stub.groq_api_key = None
            settings_stub.gemini_api_key = None

        self.assertEqual(engine.providers[0].name, "groq")
        self.assertEqual(engine.providers[0].model, "openai/gpt-oss-120b")

    def test_openrouter_free_skipped_without_opt_in(self) -> None:
        with patch("app.services.insights.settings", settings_stub):
            settings_stub.openrouter_api_key = "router-key"
            engine = MarketInsightEngine()
            settings_stub.openrouter_api_key = None

        self.assertNotIn("openrouter", [provider.name for provider in engine.providers])


if __name__ == "__main__":
    unittest.main()
