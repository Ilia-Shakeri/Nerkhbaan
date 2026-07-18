from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx

from ..config import settings
from .budgets import RedisRequestBudget, pricing_budget
from .cache import PricingRedisStore, pricing_redis
from .instruments import get_instrument
from .locks import DistributedPricingLocks, pricing_locks
from .models import (
    CircuitState,
    PersistenceStatus,
    ProviderQuote,
    ProviderRuntimeState,
    InstrumentDefinition,
    RequestPurpose,
    SourceType,
    ValidationStatus,
    utc_now,
)
from .parsers import ParserContext, ParserError, build_parser
from .parsers.base import sanitize_raw_payload
from .persistence import PricingPersistence, pricing_persistence
from .registry import ProviderDefinition


@dataclass(slots=True)
class QuoteFetchOutcome:
    quote: ProviderQuote | None
    usable: bool
    from_fresh_cache: bool
    external_called: bool
    failure_reason: str | None
    sanitized_payload: str | None = None
    content_type: str | None = None


class ProviderCallFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        http_status: int | None = None,
        payload: object | None = None,
        content_type: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.http_status = http_status
        self.payload = payload
        self.content_type = content_type


class ProviderQuoteCollector:
    failure_threshold = 3
    circuit_open_seconds = 60

    def __init__(
        self,
        *,
        store: PricingRedisStore = pricing_redis,
        budgets: RedisRequestBudget = pricing_budget,
        locks: DistributedPricingLocks = pricing_locks,
        persistence: PricingPersistence = pricing_persistence,
    ) -> None:
        self.store = store
        self.budgets = budgets
        self.locks = locks
        self.persistence = persistence

    async def quote(
        self,
        provider: ProviderDefinition,
        purpose: RequestPurpose,
        *,
        client: httpx.AsyncClient | None = None,
        instrument: InstrumentDefinition | None = None,
    ) -> QuoteFetchOutcome:
        effective_instrument = instrument or get_instrument(provider.instrument_id)
        cached = await self.store.get_provider_quote(
            provider.provider_id, provider.instrument_id
        )
        if cached is not None and self._is_fresh(cached, provider, effective_instrument):
            runtime = await self.store.get_provider_runtime(
                provider.provider_id, provider.instrument_id
            )
            runtime.operational_status = "fresh_cache"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(cached, True, True, False, None)

        runtime = await self.store.get_provider_runtime(
            provider.provider_id, provider.instrument_id
        )
        if not provider.enabled:
            runtime.operational_status = "disabled"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(cached, False, False, False, "provider_disabled")
        if not provider.configured(settings):
            runtime.operational_status = "disabled_missing_key"
            runtime.last_error_code = "missing_key"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(cached, False, False, False, "disabled_missing_key")
        if self._circuit_open(runtime):
            runtime.operational_status = "circuit_open"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(cached, False, False, False, "circuit_open")

        async with self.locks.provider_lock(
            provider.provider_id, provider.instrument_id
        ) as lease:
            if lease is None:
                return QuoteFetchOutcome(cached, False, False, False, "provider_refresh_locked")
            cached_after_lock = await self.store.get_provider_quote(
                provider.provider_id, provider.instrument_id
            )
            if cached_after_lock is not None and self._is_fresh(
                cached_after_lock, provider, effective_instrument
            ):
                return QuoteFetchOutcome(cached_after_lock, True, True, False, None)
            budget = await self.budgets.consume(provider, purpose)
            if not budget.allowed:
                runtime.operational_status = budget.reason
                await self.store.set_provider_runtime(runtime)
                return QuoteFetchOutcome(cached, False, False, False, budget.reason)
            return await self._call_and_parse(
                provider,
                purpose,
                runtime,
                client,
                effective_instrument,
            )

    async def _call_and_parse(
        self,
        provider: ProviderDefinition,
        purpose: RequestPurpose,
        runtime: ProviderRuntimeState,
        client: httpx.AsyncClient | None,
        instrument: InstrumentDefinition,
    ) -> QuoteFetchOutcome:
        started = time.monotonic()
        payload: object | None = None
        content_type: str | None = None
        http_status: int | None = None
        owns_client = client is None
        request_client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
        )
        try:
            payload, content_type, http_status = await self._request_payload(
                request_client, provider
            )
            parser = build_parser(provider.parser_id)
            received_at = utc_now()
            parsed = parser.parse(
                payload,
                ParserContext(
                    instrument=instrument,
                    received_at=received_at,
                    maximum_timestamp_age_seconds=max(
                        provider.operational_ttl_seconds * 2,
                        instrument.stale_after_seconds,
                    ),
                ),
            )
            latency_ms = max(0, int((time.monotonic() - started) * 1000))
            quote = ProviderQuote.create(
                instrument_id=provider.instrument_id,
                provider_id=provider.provider_id,
                source_type=SourceType.HTTP,
                price=parsed.price,
                currency=parsed.currency,
                weight_unit=parsed.weight_unit,
                purity=parsed.purity,
                bid=parsed.bid,
                ask=parsed.ask,
                volume=parsed.volume,
                observed_at=parsed.observed_at,
                received_at=received_at,
                latency_ms=latency_ms,
                http_status=http_status,
                parser_version=parser.parser_version,
                validation_status=ValidationStatus.ACCEPTED,
                confidence_score=provider.trust_score,
                is_direct=True,
                is_derived=False,
                is_suspicious=False,
                metadata={
                    **parsed.metadata,
                    "quote_role": purpose.value,
                    "provider_role": provider.role.value,
                },
                persistence_status=PersistenceStatus.UNPERSISTED,
            )
            await self.persistence.persist_provider_quote(quote)
            await self.store.set_provider_quote(
                quote, provider.operational_ttl_seconds
            )
            await self._record_success(provider, runtime, latency_ms, http_status)
            sanitized = sanitize_raw_payload(payload, provider.maximum_payload_bytes)
            return QuoteFetchOutcome(
                quote,
                True,
                False,
                True,
                None,
                sanitized_payload=sanitized,
                content_type=content_type,
            )
        except ProviderCallFailure as exc:
            if exc.http_status == 429:
                await self.budgets.record_rate_limit(provider)
            rejected = await self._rejected_quote(
                provider,
                purpose,
                exc.code,
                exc.http_status,
                exc.payload,
                exc.content_type,
                started,
                instrument,
            )
            await self._record_failure(
                provider, runtime, exc.code, exc.http_status, started
            )
            return QuoteFetchOutcome(
                rejected,
                False,
                False,
                True,
                exc.code,
                sanitized_payload=(
                    sanitize_raw_payload(exc.payload, provider.maximum_payload_bytes)
                    if exc.payload is not None
                    else None
                ),
                content_type=exc.content_type,
            )
        except ParserError as exc:
            rejected = await self._rejected_quote(
                provider,
                purpose,
                exc.code,
                http_status,
                payload,
                content_type,
                started,
                instrument,
            )
            await self._record_failure(
                provider, runtime, exc.code, http_status, started
            )
            return QuoteFetchOutcome(
                rejected,
                False,
                False,
                True,
                exc.code,
                sanitized_payload=(
                    sanitize_raw_payload(payload, provider.maximum_payload_bytes)
                    if payload is not None
                    else None
                ),
                content_type=content_type,
            )
        except (httpx.HTTPError, OSError, ValueError) as exc:
            code = "transport_error" if isinstance(exc, (httpx.HTTPError, OSError)) else "invalid_response"
            rejected = await self._rejected_quote(
                provider,
                purpose,
                code,
                http_status,
                payload,
                content_type,
                started,
                instrument,
            )
            await self._record_failure(provider, runtime, code, http_status, started)
            return QuoteFetchOutcome(rejected, False, False, True, code)
        finally:
            if owns_client:
                await request_client.aclose()

    async def _request_payload(
        self,
        client: httpx.AsyncClient,
        provider: ProviderDefinition,
    ) -> tuple[object, str | None, int]:
        headers = dict(provider.static_headers)
        params: dict[str, str] = {}
        if provider.api_key_setting:
            key = getattr(settings, provider.api_key_setting, None)
            if not key:
                raise ProviderCallFailure("missing_key", "Provider key is not configured")
            if provider.api_key_header:
                value = str(key)
                if provider.api_key_header.lower() == "authorization" and not value.lower().startswith("bearer "):
                    value = f"Bearer {value}"
                headers[provider.api_key_header] = value
            elif provider.api_key_query_parameter:
                params[provider.api_key_query_parameter] = str(key)
        try:
            async with client.stream(
                provider.method,
                provider.url,
                headers=headers,
                params=params,
            ) as response:
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > provider.maximum_payload_bytes:
                        raise ProviderCallFailure(
                            "payload_too_large",
                            "Provider payload exceeded the configured bound",
                            http_status=response.status_code,
                            content_type=content_type,
                        )
                payload: object | None = None
                if body:
                    try:
                        payload = json.loads(body)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ProviderCallFailure(
                            "invalid_json",
                            "Provider response is not valid JSON",
                            http_status=response.status_code,
                            content_type=content_type,
                        ) from exc
                if response.status_code == 429:
                    raise ProviderCallFailure(
                        "rate_limited",
                        "Provider rate limit reached",
                        http_status=429,
                        payload=payload,
                        content_type=content_type,
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    raise ProviderCallFailure(
                        "http_error",
                        "Provider returned an unsuccessful status",
                        http_status=response.status_code,
                        payload=payload,
                        content_type=content_type,
                    )
                if payload is None:
                    raise ProviderCallFailure(
                        "empty_payload",
                        "Provider returned an empty payload",
                        http_status=response.status_code,
                        content_type=content_type,
                    )
                return payload, content_type, response.status_code
        except httpx.HTTPError as exc:
            raise ProviderCallFailure("transport_error", "Provider request failed") from exc

    async def _rejected_quote(
        self,
        provider: ProviderDefinition,
        purpose: RequestPurpose,
        reason: str,
        http_status: int | None,
        payload: object | None,
        content_type: str | None,
        started: float,
        instrument: InstrumentDefinition,
    ) -> ProviderQuote:
        now = utc_now()
        sanitized = (
            sanitize_raw_payload(payload, provider.maximum_payload_bytes)
            if payload is not None
            else None
        )
        raw_reference = None
        if sanitized is not None:
            raw_reference = await self.persistence.store_raw_payload(
                provider_id=provider.provider_id,
                instrument_id=provider.instrument_id,
                reason=reason,
                sanitized_text=sanitized,
                content_type=content_type,
            )
        quote = ProviderQuote.create(
            instrument_id=provider.instrument_id,
            provider_id=provider.provider_id,
            source_type=SourceType.HTTP,
            price=None,
            currency=instrument.quote_currency,
            weight_unit=instrument.weight_unit,
            purity=instrument.purity,
            observed_at=now,
            received_at=now,
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            http_status=http_status,
            parser_version=provider.parser_version,
            validation_status=ValidationStatus.REJECTED,
            confidence_score=Decimal(0),
            is_direct=True,
            is_derived=False,
            rejection_reason=reason,
            raw_payload_reference=raw_reference,
            metadata={"quote_role": purpose.value, "provider_role": provider.role.value},
            persistence_status=PersistenceStatus.UNPERSISTED,
        )
        await self.persistence.persist_provider_quote(quote)
        return quote

    async def _record_success(
        self,
        provider: ProviderDefinition,
        runtime: ProviderRuntimeState,
        latency_ms: int,
        http_status: int | None,
    ) -> None:
        now = utc_now()
        previous_total = runtime.success_count
        runtime.success_count += 1
        runtime.consecutive_failures = 0
        runtime.last_success_at = now
        runtime.last_error_code = None
        runtime.circuit_state = CircuitState.CLOSED
        runtime.circuit_open_until = None
        runtime.operational_status = "connected"
        latency = Decimal(latency_ms)
        if runtime.average_latency_ms is None:
            runtime.average_latency_ms = latency
        else:
            runtime.average_latency_ms = (
                runtime.average_latency_ms * Decimal(previous_total) + latency
            ) / Decimal(max(1, runtime.success_count))
        await self.store.set_provider_runtime(runtime)
        await self.persistence.record_runtime_event(
            provider_id=provider.provider_id,
            instrument_id=provider.instrument_id,
            event_type="request",
            status="success",
            latency_ms=latency_ms,
            http_status=http_status,
        )

    async def _record_failure(
        self,
        provider: ProviderDefinition,
        runtime: ProviderRuntimeState,
        error_code: str,
        http_status: int | None,
        started: float,
    ) -> None:
        now = utc_now()
        runtime.failure_count += 1
        runtime.consecutive_failures += 1
        runtime.last_failure_at = now
        runtime.last_error_code = error_code
        runtime.operational_status = "failed"
        if error_code == "rate_limited":
            runtime.cooldown_until = now + timedelta(
                seconds=provider.budget.cooldown_after_429_seconds
            )
            runtime.operational_status = "cooldown"
        if runtime.consecutive_failures >= self.failure_threshold:
            runtime.circuit_state = CircuitState.OPEN
            runtime.circuit_open_until = now + timedelta(seconds=self.circuit_open_seconds)
            runtime.operational_status = "circuit_open"
        await self.store.set_provider_runtime(runtime)
        await self.persistence.record_runtime_event(
            provider_id=provider.provider_id,
            instrument_id=provider.instrument_id,
            event_type="request",
            status="failed",
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            http_status=http_status,
            sanitized_error=error_code,
        )

    @staticmethod
    def _is_fresh(
        quote: ProviderQuote,
        provider: ProviderDefinition,
        instrument: InstrumentDefinition,
    ) -> bool:
        if quote.validation_status is not ValidationStatus.ACCEPTED or quote.price is None:
            return False
        age = (utc_now() - quote.observed_at).total_seconds()
        usable_window = min(
            provider.operational_ttl_seconds, instrument.expire_after_seconds
        )
        return 0 <= age <= usable_window

    @staticmethod
    def _circuit_open(runtime: ProviderRuntimeState) -> bool:
        now = utc_now()
        if runtime.cooldown_until is not None and now < runtime.cooldown_until:
            return True
        if runtime.circuit_state is not CircuitState.OPEN:
            return False
        if runtime.circuit_open_until is None or now >= runtime.circuit_open_until:
            runtime.circuit_state = CircuitState.HALF_OPEN
            return False
        return True


provider_collector = ProviderQuoteCollector()
