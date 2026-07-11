from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Upper bound on conversation turns accepted per request to cap token usage and
# keep latency predictable under load.
MAX_HISTORY_MESSAGES = 20
REQUEST_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str | None


class InsightUnavailableError(RuntimeError):
    """Raised when the reasoning provider is not configured or unreachable."""


class MarketInsightEngine:
    """Bridges market data and a remote reasoning provider.

    The provider speaks the standard chat-completions protocol, so any
    compatible endpoint can be used by swapping the base URL, model and key in
    configuration without touching this code.
    """

    def __init__(self) -> None:
        self.providers = [
            ProviderConfig(
                base_url=settings.groq_api_base_url,
                model=settings.groq_model,
                api_key=settings.groq_api_key,
            ),
            ProviderConfig(
                base_url=settings.insight_api_base_url,
                model=settings.insight_model,
                api_key=settings.insight_api_key or settings.deepseek_api_key,
            ),
        ]

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
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
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
                }
                try:
                    response = await client.post(url, headers=headers, json=body)
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                    last_error = exc
                    logger.warning(
                        "Reasoning provider %s failed; trying fallback %s of %s",
                        provider.base_url,
                        index + 1,
                        len(provider_chain),
                    )
                    continue
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.error("Reasoning provider request failed: %s", exc)
                    break

                try:
                    content = payload["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    logger.error("Unexpected reasoning provider payload: %s", payload)
                    raise InsightUnavailableError("Reasoning provider returned an invalid response") from exc

                text = (content or "").strip()
                if text:
                    return text
                raise InsightUnavailableError("Reasoning provider returned an empty response")

        if isinstance(last_error, httpx.HTTPStatusError):
            raise InsightUnavailableError("All reasoning providers rejected the request") from last_error
        raise InsightUnavailableError("All reasoning providers are unreachable") from last_error

    async def analyze_chart(
        self,
        asset_id: str,
        snapshot: dict[str, Any],
        language: str,
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

        return await self._complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
        )

    async def chat(self, messages: list[dict[str, str]], language: str) -> str:
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
        conversation = [{"role": "system", "content": system_prompt}, *trimmed]
        return await self._complete(conversation, temperature=0.7)


insight_engine = MarketInsightEngine()
