from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import settings
from ..security import rate_limit_hit

logger = logging.getLogger(__name__)

# Upper bound on conversation turns accepted per request to cap token usage and
# keep latency predictable under load.
MAX_HISTORY_MESSAGES = 20
REQUEST_TIMEOUT_SECONDS = 25
DAILY_WINDOW_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str | None
    name: str = "provider"


class InsightUnavailableError(RuntimeError):
    """Raised when the reasoning provider is not configured or unreachable."""


class MarketInsightEngine:
    """Bridges market data and a remote reasoning provider.

    The provider speaks the standard chat-completions protocol, so any
    compatible endpoint can be used by swapping the base URL, model and key in
    configuration without touching this code.
    """

    def __init__(self) -> None:
        available = {
            "groq": ProviderConfig(
                settings.groq_api_base_url,
                settings.groq_model,
                settings.groq_api_key,
                "groq",
            ),
            "gemini": ProviderConfig(
                settings.gemini_api_base_url,
                settings.gemini_model,
                settings.gemini_api_key,
                "gemini",
            ),
            "openrouter": ProviderConfig(
                settings.openrouter_api_base_url,
                settings.openrouter_model or "openrouter/free",
                settings.openrouter_api_key,
                "openrouter",
            ),
            "deepseek": ProviderConfig(
                settings.deepseek_api_base_url,
                settings.deepseek_model,
                settings.deepseek_api_key or settings.insight_api_key,
                "deepseek",
            ),
        }
        self.providers: list[ProviderConfig] = []
        for raw_name in settings.ai_provider_order.split(","):
            name = raw_name.strip().lower()
            provider = available.get(name)
            if provider is None:
                logger.warning("Unknown reasoning provider skipped: %s", name)
                continue
            if (
                provider.name == "openrouter"
                and provider.model == "openrouter/free"
                and not settings.ai_allow_openrouter_free
            ):
                continue
            self.providers.append(provider)

    def is_configured(self) -> bool:
        return any(provider.api_key for provider in self.providers)

    async def _complete(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        providers: list[ProviderConfig] | None = None,
    ) -> str:
        provider_chain = [provider for provider in (providers or self.providers) if provider.api_key]
        if not provider_chain:
            raise InsightUnavailableError("Reasoning provider API key is not configured")

        last_error: Exception | None = None
        timeout_seconds = float(getattr(settings, "ai_request_timeout_seconds", REQUEST_TIMEOUT_SECONDS))
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            for index, provider in enumerate(provider_chain):
                url = f"{provider.base_url.rstrip('/')}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {provider.api_key}",
                    "Content-Type": "application/json",
                }
                body = {
                    "model": provider.model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                    "max_tokens": settings.ai_max_tokens,
                }
                maximum_attempts = settings.ai_max_retries + 1
                for attempt in range(maximum_attempts):
                    try:
                        response = await client.post(url, headers=headers, json=body)
                        response.raise_for_status()
                        payload = response.json()
                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        status_code = exc.response.status_code
                        retryable = status_code == 408 or status_code >= 500
                        if retryable and attempt + 1 < maximum_attempts:
                            await asyncio.sleep(min(0.25 * (2 ** attempt), 1.0))
                            continue
                        break
                    except httpx.HTTPError as exc:
                        last_error = exc
                        if attempt + 1 < maximum_attempts:
                            await asyncio.sleep(min(0.25 * (2 ** attempt), 1.0))
                            continue
                        break
                    except (TypeError, ValueError) as exc:
                        last_error = exc
                        break

                    try:
                        content = payload["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as exc:
                        last_error = exc
                        break

                    text = (content or "").strip()
                    if text:
                        self.last_provider_metadata = {
                            "provider": provider.name,
                            "configured_model": provider.model,
                            "response_model": str(payload.get("model") or provider.model),
                        }
                        return text
                    last_error = InsightUnavailableError("Reasoning provider returned an empty response")
                    break

                logger.warning(
                    "Reasoning provider failed; trying fallback %s of %s",
                    index + 1,
                    len(provider_chain),
                )

        if isinstance(last_error, httpx.HTTPStatusError):
            raise InsightUnavailableError("All reasoning providers rejected the request") from last_error
        raise InsightUnavailableError("All reasoning providers are unreachable") from last_error

    async def analyze_chart(
        self,
        asset_id: str,
        snapshot: dict[str, Any],
        language: str,
        user_id: str,
    ) -> str:
        """Produce a concise market read for a single asset snapshot."""
        lang_directive = (
            "Reply in fluent Persian (Farsi)."
            if language == "fa"
            else "Reply in clear English."
        )

        system_prompt = (
            "You are a professional financial market analyst for the Nerkhbaan "
            "price platform. Analyze the provided price snapshot and recent "
            "history. Cover trend direction, momentum, notable changes and a "
            "short, practical outlook. Be objective and never give guaranteed "
            "financial promises. Keep it under 200 words. " + lang_directive
        )

        history = snapshot.get("history") or []
        # Trim history to the most recent points to keep the prompt compact.
        compact_history = history[-24:]

        user_prompt = (
            f"Asset: {asset_id} ({snapshot.get('label_en')}).\n"
            f"Price (USD): {snapshot.get('price_usd')}\n"
            f"Price (Toman): {snapshot.get('price_toman')}\n"
            f"24h change percent: {snapshot.get('change_percent')}\n"
            f"Trend: {snapshot.get('trend')}\n"
            f"Recent history points: {compact_history}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        self._check_quota(user_id, messages)
        return await self._complete(
            messages,
            temperature=0.4,
        )

    async def chat(self, messages: list[dict[str, str]], language: str, user_id: str) -> str:
        """Answer a free-form market question, grounded in the platform scope."""
        lang_directive = (
            "Reply in fluent Persian (Farsi)."
            if language == "fa"
            else "Reply in clear English."
        )
        system_prompt = (
            "You are the Nerkhbaan smart assistant. Help users understand gold, "
            "silver, currency and crypto markets, pricing concepts and how to use "
            "the platform. Be concise, accurate and avoid guaranteed financial "
            "promises. " + lang_directive
        )

        # Keep only the trailing window of the dialog to bound token usage.
        trimmed = messages[-MAX_HISTORY_MESSAGES:]
        self._check_quota(user_id, trimmed)
        conversation = [{"role": "system", "content": system_prompt}, *trimmed]
        response = await self._complete(conversation, temperature=0.7)
        disclaimer = (
            "این پاسخ فقط اطلاعات عمومی است، ممکن است نادرست باشد، تضمین نیست و توصیه سرمایه‌گذاری شخصی محسوب نمی‌شود."
            if language == "fa"
            else "This is informational, may be inaccurate, is not guaranteed, and is not personalized investment advice."
        )
        return f"{response}\n\n{disclaimer}"

    def _check_quota(self, user_id: str, messages: list[dict[str, str]]) -> None:
        fingerprint = hashlib.sha256(
            "|".join(str(item.get("content", ""))[:500] for item in messages).encode("utf-8")
        ).hexdigest()
        duplicate = rate_limit_hit(
            "insight-dedup",
            f"{user_id}:{fingerprint}",
            1,
            settings.ai_deduplication_window_seconds,
        )
        if duplicate.blocked:
            raise InsightUnavailableError("Duplicate reasoning request was throttled")
        user_state = rate_limit_hit(
            "insight-user-daily",
            user_id,
            settings.ai_user_daily_request_limit,
            DAILY_WINDOW_SECONDS,
        )
        if user_state.blocked:
            raise InsightUnavailableError("User reasoning quota is exhausted")
        global_state = rate_limit_hit(
            "insight-global-daily",
            "all-users",
            settings.ai_global_daily_request_limit,
            DAILY_WINDOW_SECONDS,
        )
        if global_state.blocked:
            raise InsightUnavailableError("Reasoning quota is exhausted")


insight_engine = MarketInsightEngine()
