from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from ..config import settings
from ..observability import provider_request_duration_seconds, provider_request_total
from .budgets import RedisRequestBudget, pricing_budget
from .cache import PricingRedisStore, pricing_redis
from .freshness import (
    FreshnessPolicy,
    FreshnessStatus,
    freshness_boundaries,
)
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
    ensure_utc,
    utc_now,
)
from .parsers import ParserContext, ParserError, build_parser
from .parsers.base import sanitize_raw_payload
from .persistence import PricingPersistence, pricing_persistence
from .registry import ProviderDefinition
from .source_snapshots import SharedSourceSnapshots, SourceSnapshot, SourceSnapshotUnavailable
from . import rights


def _raw_payload_bound(provider: ProviderDefinition) -> int:
    """Byte ceiling for a stored raw payload.

    Stored payloads are diagnostic evidence, not the transfer bound, so they
    are capped well below what the provider is allowed to send.
    """
    return min(provider.maximum_payload_bytes, settings.raw_provider_payload_max_bytes)


@dataclass(slots=True)
class QuoteFetchOutcome:
    quote: ProviderQuote | None
    usable: bool
    from_fresh_cache: bool
    external_called: bool
    failure_reason: str | None
    sanitized_payload: str | None = None
    content_type: str | None = None
    cache_status: FreshnessStatus | None = None
    selection_trace: list[dict[str, object]] = field(default_factory=list)
    retry_after_seconds: int | None = None

    def __post_init__(self):
        if self.quote is not None and not all(
            rights.provider_allowed(self.quote.provider_id, action) for action in ("collect", "store")
        ):
            self.quote = None
            self.usable = self.from_fresh_cache = False
            self.sanitized_payload = None
            self.failure_reason = "provider_rights_denied"


class ProviderCallFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        http_status: int | None = None,
        payload: object | None = None,
        content_type: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.http_status = http_status
        self.payload = payload
        self.content_type = content_type
        self.retry_after_seconds = retry_after_seconds


class ProviderBudgetUnavailable(RuntimeError):
    pass


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
        self.source_snapshots = SharedSourceSnapshots(store=store, budgets=budgets)

    async def quote(
        self,
        provider: ProviderDefinition,
        purpose: RequestPurpose,
        *,
        client: httpx.AsyncClient | None = None,
        instrument: InstrumentDefinition | None = None,
    ) -> QuoteFetchOutcome:
        if provider.history_only:
            return QuoteFetchOutcome(None, False, False, False, "history_only")
        if (not rights.provider_allowed(provider.provider_id, "collect")
                or not rights.provider_allowed(provider.provider_id, "store")
                or not rights.endpoint_allowed(provider.provider_id, provider.url)):
            return QuoteFetchOutcome(None, False, False, False, "provider_rights_denied")
        effective_instrument = instrument or get_instrument(provider.instrument_id)
        cached = await self.store.get_provider_quote(
            provider.provider_id, provider.instrument_id
        )
        cached_status = self._cache_status(cached, provider, effective_instrument)
        runtime = await self.store.get_provider_runtime(
            provider.provider_id, provider.instrument_id
        )
        if not provider.enabled:
            runtime.operational_status = "disabled"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(
                cached,
                False,
                False,
                False,
                "provider_disabled",
                cache_status=cached_status,
            )
        if not provider.configured(settings):
            runtime.operational_status = "disabled_missing_key"
            runtime.last_error_code = "missing_key"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(
                cached,
                False,
                False,
                False,
                "disabled_missing_key",
                cache_status=cached_status,
            )
        if (
            cached is not None
            and cached_status is FreshnessStatus.LIVE
            and cached.persistence_status is PersistenceStatus.PERSISTED
        ):
            self._apply_current_live_boundary(
                cached,
                provider,
                effective_instrument,
            )
            runtime.operational_status = "fresh_cache"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(
                cached,
                True,
                True,
                False,
                None,
                cache_status=FreshnessStatus.LIVE,
            )
        if self._circuit_open(runtime):
            runtime.operational_status = "circuit_open"
            await self.store.set_provider_runtime(runtime)
            return QuoteFetchOutcome(
                cached,
                False,
                False,
                False,
                "circuit_open",
                cache_status=cached_status,
            )

        async with self.locks.provider_lock(
            provider.provider_id, provider.instrument_id
        ) as lease:
            if lease is None:
                return QuoteFetchOutcome(
                    cached,
                    False,
                    False,
                    False,
                    "provider_refresh_locked",
                    cache_status=cached_status,
                )
            cached_after_lock = await self.store.get_provider_quote(
                provider.provider_id, provider.instrument_id
            )
            locked_cache_status = self._cache_status(
                cached_after_lock, provider, effective_instrument
            )
            if (
                cached_after_lock is not None
                and locked_cache_status is FreshnessStatus.LIVE
                and cached_after_lock.persistence_status is PersistenceStatus.PERSISTED
            ):
                self._apply_current_live_boundary(
                    cached_after_lock,
                    provider,
                    effective_instrument,
                )
                return QuoteFetchOutcome(
                    cached_after_lock,
                    True,
                    True,
                    False,
                    None,
                    cache_status=FreshnessStatus.LIVE,
                )
            try:
                return await self._call_and_parse(
                    provider,
                    purpose,
                    runtime,
                    client,
                    effective_instrument,
                )
            except ProviderBudgetUnavailable as exc:
                reason = str(exc)
                runtime.operational_status = reason
                await self.store.set_provider_runtime(runtime)
                return QuoteFetchOutcome(
                    cached_after_lock or cached,
                    False,
                    False,
                    False,
                    reason,
                    cache_status=locked_cache_status or cached_status,
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
        external_called = provider.source_family != "nerkhsanj"
        owns_client = client is None
        request_client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                float(settings.pricing_provider_request_timeout_seconds),
                connect=float(settings.pricing_provider_connect_timeout_seconds),
            ),
            follow_redirects=False,
        )
        try:
            if provider.source_family == "nerkhsanj":
                snapshot = await self._source_snapshot(request_client, provider, purpose)
                payload, content_type, http_status = snapshot.payload, snapshot.content_type, snapshot.http_status
                received_at = snapshot.fetched_at
                external_called = snapshot.network_called
            else:
                payload, content_type, http_status = await self._request_payload(
                    request_client, provider, purpose=purpose
                )
                received_at = utc_now()
            if (not rights.provider_allowed(provider.provider_id, "collect")
                    or not rights.provider_allowed(provider.provider_id, "store")
                    or not rights.endpoint_allowed(provider.provider_id, provider.url)):
                return QuoteFetchOutcome(None, False, False, external_called, "provider_rights_denied")
            parser = build_parser(provider.parser_id)
            parsed = parser.parse(
                payload,
                ParserContext(
                    instrument=instrument,
                    received_at=received_at,
                    maximum_timestamp_age_seconds=min(
                        provider.maximum_source_age_seconds
                        or provider.operational_ttl_seconds,
                        instrument.expire_after_seconds,
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
                source_semantic=provider.source_semantic,
                source_family=provider.source_family,
                venue=provider.venue,
                last=(
                    parsed.price
                    if provider.selected_price_semantic.value == "last"
                    else None
                ),
                selected_price_semantic=provider.selected_price_semantic,
                original_currency=parsed.metadata.get("source_currency"),
                original_value=parsed.metadata.get("original_value"),
                conversion_factor=(
                    Decimal("0.1")
                    if parsed.metadata.get("normalization") == "rial_to_toman"
                    else Decimal(str(parsed.metadata.get("conversion_factor", 1)))
                ),
                route_id=provider.route_id,
                metadata={
                    **parsed.metadata,
                    "quote_role": purpose.value,
                    "provider_role": provider.role.value,
                    "provider_live_ttl_seconds": provider.operational_ttl_seconds,
                    "maximum_source_age_seconds": (
                        provider.maximum_source_age_seconds
                        or min(
                            provider.operational_ttl_seconds,
                            instrument.operational_ttl_seconds,
                            instrument.expire_after_seconds,
                        )
                    ),
                    "anchor_live_window_at_receive_time": (
                        provider.anchor_live_window_at_receive_time
                    ),
                },
                persistence_status=PersistenceStatus.UNPERSISTED,
            )
            self._apply_current_live_boundary(quote, provider, instrument)
            freshness = self._cache_status(quote, provider, instrument)
            persistence_result = await self.persistence.persist_provider_quote(quote)
            if (not rights.provider_allowed(provider.provider_id, "collect")
                    or not rights.provider_allowed(provider.provider_id, "store")
                    or getattr(persistence_result, "sanitized_error", None) == "provider_rights_denied"):
                return QuoteFetchOutcome(None, False, False, external_called, "provider_rights_denied")
            await self.store.set_provider_quote(
                quote, provider.operational_ttl_seconds
            )
            await self._record_success(
                provider, runtime, latency_ms, http_status,
                received_at=received_at if provider.source_family == "nerkhsanj" else None,
                external_called=external_called,
            )
            sanitized = sanitize_raw_payload(payload, _raw_payload_bound(provider))
            failure_reason = None
            if freshness is not FreshnessStatus.LIVE:
                failure_reason = "source_not_live"
            elif not persistence_result.persisted:
                failure_reason = "source_persistence_queued" if persistence_result.queued else "source_persistence_failed"
            return QuoteFetchOutcome(
                quote,
                persistence_result.persisted and freshness is FreshnessStatus.LIVE,
                not external_called,
                external_called,
                failure_reason,
                sanitized_payload=sanitized,
                content_type=content_type,
                cache_status=freshness,
            )
        except ProviderCallFailure as exc:
            external_called = getattr(exc, "network_called", external_called)
            if exc.http_status == 429:
                await self.budgets.record_rate_limit(
                    provider, source_url=provider.url,
                    retry_after_seconds=exc.retry_after_seconds,
                )
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
                provider,
                runtime,
                exc.code,
                exc.http_status,
                started,
                retry_after_seconds=exc.retry_after_seconds,
                external_called=external_called,
            )
            return QuoteFetchOutcome(
                rejected,
                False,
                False,
                external_called,
                exc.code,
                sanitized_payload=(
                    sanitize_raw_payload(exc.payload, _raw_payload_bound(provider))
                    if exc.payload is not None
                    else None
                ),
                content_type=exc.content_type,
                retry_after_seconds=exc.retry_after_seconds,
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
                provider, runtime, exc.code, http_status, started, external_called=external_called
            )
            return QuoteFetchOutcome(
                rejected,
                False,
                False,
                external_called,
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
            await self._record_failure(provider, runtime, code, http_status, started, external_called=external_called)
            return QuoteFetchOutcome(rejected, False, False, external_called, code)
        finally:
            if owns_client:
                await request_client.aclose()

    async def _source_snapshot(
        self, client: httpx.AsyncClient, provider: ProviderDefinition,
        purpose: RequestPurpose | None,
    ) -> SourceSnapshot:
        self._validate_destination(provider)

        async def load():
            return await self._request_once(client, provider, dict(provider.static_headers), {})

        try:
            return await self.source_snapshots.get(provider, provider.url, load, purpose or RequestPurpose.NORMAL)
        except SourceSnapshotUnavailable as exc:
            if not exc.network_called and (exc.code.startswith("budget_limit_") or exc.code in {
                "provider_budget_disabled", "provider_cooldown", "snapshot_locked", "snapshot_cache_unavailable",
            }):
                raise ProviderBudgetUnavailable(exc.code) from exc
            if isinstance(exc.cause, ProviderCallFailure):
                exc.cause.network_called = exc.network_called
                raise exc.cause from exc
            code = "transport_error" if isinstance(exc.cause, (httpx.HTTPError, OSError, TimeoutError)) else exc.code
            failure = ProviderCallFailure(code, "Shared source snapshot unavailable")
            failure.network_called = exc.network_called
            raise failure from exc

    async def _request_payload(
        self,
        client: httpx.AsyncClient,
        provider: ProviderDefinition,
        *,
        purpose: RequestPurpose | None = None,
    ) -> tuple[object, str | None, int]:
        if getattr(provider, "history_only", False):
            raise ProviderCallFailure("history_only", "This source supports historical collection only")
        if provider.source_family == "nerkhsanj":
            snapshot = await self._source_snapshot(client, provider, purpose)
            return snapshot.payload, snapshot.content_type, snapshot.http_status
        if (not rights.provider_allowed(provider.provider_id, "collect")
                or not rights.endpoint_allowed(provider.provider_id, provider.url)):
            raise ProviderCallFailure("provider_rights_denied", "Source permission unavailable")
        headers = dict(provider.static_headers)
        params: dict[str, str] = {}
        self._validate_destination(provider)
        if settings.pricing_relay_base_url:
            relay_host = urlparse(settings.pricing_relay_base_url).hostname
            provider_host = urlparse(provider.url).hostname
            if relay_host and provider_host == relay_host:
                if not rights.provider_allowed(provider.provider_id, "own_app_transport"):
                    raise ProviderCallFailure("provider_rights_denied", "Application transport permission unavailable")
                if not settings.pricing_relay_shared_token:
                    raise ProviderCallFailure(
                        "missing_relay_token", "Relay token is not configured"
                    )
                headers["X-Relay-Token"] = settings.pricing_relay_shared_token
        if provider.requires_https and provider.api_key_setting:
            parsed = urlparse(provider.url)
            if parsed.scheme != "https":
                raise ProviderCallFailure(
                    "insecure_http_blocked",
                    "Provider credentials require HTTPS",
                )
        if provider.api_key_setting:
            key = getattr(settings, provider.api_key_setting, None)
            use_header = bool(provider.api_key_header)
            if provider.provider_id.startswith("nerkh_io_") and not key:
                key = getattr(settings, "nerkh_io_api_key", None)
                provider_query_key = "x-api-key"
                use_header = False
            else:
                provider_query_key = provider.api_key_query_parameter
            if not key:
                raise ProviderCallFailure("missing_key", "Provider key is not configured")
            if use_header and provider.api_key_header:
                value = str(key)
                if provider.api_key_header.lower() == "authorization" and not value.lower().startswith("bearer "):
                    value = f"Bearer {value}"
                headers[provider.api_key_header] = value
            elif provider_query_key:
                params[provider_query_key] = str(key)
        maximum_attempts = 1 if provider.source_family == "gta_silver" else settings.pricing_provider_max_retries + 1
        last_failure: ProviderCallFailure | None = None
        for attempt in range(maximum_attempts):
            if not rights.provider_allowed(provider.provider_id, "collect"):
                raise ProviderCallFailure("provider_rights_denied", "Source permission unavailable")
            # Operator probes omit a purpose; managed refreshes charge every
            # actual attempt, including retries, through the shared limits.
            if purpose is not None or provider.source_family == "gta_silver":
                budget = await self.budgets.consume(provider, purpose or RequestPurpose.NORMAL)
                if not budget.allowed:
                    if last_failure is not None:
                        raise last_failure
                    raise ProviderBudgetUnavailable(budget.reason)
            try:
                return await self._request_once(client, provider, headers, params)
            except ProviderCallFailure as exc:
                retryable = (
                    exc.code == "transport_error"
                    or exc.http_status == 408
                    or (exc.http_status is not None and exc.http_status >= 500)
                )
                if not retryable or attempt + 1 >= maximum_attempts:
                    raise
                last_failure = exc
                delay = float(settings.pricing_provider_backoff_base_seconds) * (2 ** attempt)
                if exc.retry_after_seconds is not None:
                    delay = max(delay, float(exc.retry_after_seconds))
                await asyncio.sleep(min(delay, 10.0))
        raise ProviderCallFailure("transport_error", "Provider retry loop ended")

    async def _request_once(
        self,
        client: httpx.AsyncClient,
        provider: ProviderDefinition,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> tuple[object, str | None, int]:
        if getattr(provider, "history_only", False):
            raise ProviderCallFailure("history_only", "This source supports historical collection only")
        if (not rights.provider_allowed(provider.provider_id, "collect")
                or not rights.endpoint_allowed(provider.provider_id, provider.url)):
            raise ProviderCallFailure("provider_rights_denied", "Source permission unavailable")
        try:
            async with client.stream(
                provider.method,
                provider.url,
                headers=headers,
                params=params,
            ) as response:
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65_536):
                    maximum_payload_bytes = min(
                        provider.maximum_payload_bytes,
                        settings.pricing_provider_max_response_bytes,
                    )
                    if len(body) + len(chunk) > maximum_payload_bytes:
                        raise ProviderCallFailure(
                            "payload_too_large",
                            "Provider payload exceeded the configured bound",
                            http_status=response.status_code,
                            content_type=content_type,
                        )
                    body.extend(chunk)
                payload: object | None = None
                if body:
                    try:
                        payload = json.loads(body)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        # Error pages may be HTML. Preserve the HTTP status so
                        # throttling and bounded server-error retries still work.
                        if 200 <= response.status_code < 300:
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
                        retry_after_seconds=self._parse_retry_after(
                            response.headers.get("retry-after")
                        ),
                    )
                if response.status_code < 200 or response.status_code >= 300:
                    if (
                        provider.source_family == "servix"
                        and response.status_code == 403
                        and isinstance(payload, dict)
                        and payload.get("code") == "EMAIL_VERIFICATION_REQUIRED"
                    ):
                        # The source account needs verification. Keep the stable
                        # reason while dropping messages and account identifiers.
                        raise ProviderCallFailure(
                            "email_verification_required",
                            "Source account email verification is required",
                            http_status=403,
                            payload={"status": 403, "code": "EMAIL_VERIFICATION_REQUIRED"},
                            content_type=content_type,
                        )
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

    @staticmethod
    def _validate_destination(provider: ProviderDefinition) -> None:
        parsed = urlparse(provider.url)
        if not parsed.scheme or not parsed.hostname:
            raise ProviderCallFailure("invalid_provider_url", "Provider URL is invalid")
        if parsed.username or parsed.password:
            raise ProviderCallFailure("url_credentials_blocked", "Provider URL credentials are not allowed")
        query = parsed.query.lower()
        if any(marker in query for marker in ("api_key=", "apikey=", "token=", "secret=", "password=")):
            raise ProviderCallFailure("url_secret_blocked", "Provider URL cannot contain credentials")
        allowed_hosts = {
            host.strip().lower()
            for host in settings.pricing_provider_allowed_hosts.split(",")
            if host.strip()
        }
        hostname = parsed.hostname.lower()
        if allowed_hosts and hostname not in allowed_hosts:
            raise ProviderCallFailure("provider_host_not_allowed", "Provider host is not allowlisted")

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
            source_semantic=provider.source_semantic,
            source_family=provider.source_family,
            venue=provider.venue,
            selected_price_semantic=provider.selected_price_semantic,
            route_id=provider.route_id,
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
        *,
        received_at: datetime | None = None,
        external_called: bool = True,
    ) -> None:
        now = utc_now()
        previous_total = runtime.success_count
        runtime.success_count += 1
        runtime.consecutive_failures = 0
        runtime.last_success_at = received_at or now
        runtime.last_error_code = None
        runtime.circuit_state = CircuitState.CLOSED
        runtime.circuit_open_until = None
        runtime.operational_status = "connected" if external_called else "source_snapshot"
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
            event_type="request" if external_called else "source_snapshot",
            status="success",
            latency_ms=latency_ms,
            http_status=http_status,
        )
        if not external_called:
            return
        provider_request_total.labels(
            provider=provider.provider_id,
            instrument=provider.instrument_id,
            status="success",
        ).inc()
        provider_request_duration_seconds.labels(
            provider=provider.provider_id,
            instrument=provider.instrument_id,
        ).observe(latency_ms / 1000)

    async def _record_failure(
        self,
        provider: ProviderDefinition,
        runtime: ProviderRuntimeState,
        error_code: str,
        http_status: int | None,
        started: float,
        retry_after_seconds: int | None = None,
        *,
        external_called: bool = True,
    ) -> None:
        now = utc_now()
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        runtime.failure_count += 1
        runtime.consecutive_failures += 1
        runtime.last_failure_at = now
        runtime.last_error_code = error_code
        runtime.operational_status = "failed"
        if error_code == "rate_limited":
            cooldown_seconds = max(
                provider.budget.cooldown_after_429_seconds,
                retry_after_seconds or 0,
            )
            runtime.cooldown_until = now + timedelta(
                seconds=cooldown_seconds
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
            event_type="request" if external_called else "source_snapshot",
            status="failed",
            latency_ms=latency_ms,
            http_status=http_status,
            sanitized_error=error_code,
        )
        if not external_called:
            return
        provider_request_total.labels(
            provider=provider.provider_id,
            instrument=provider.instrument_id,
            status=error_code,
        ).inc()
        provider_request_duration_seconds.labels(
            provider=provider.provider_id,
            instrument=provider.instrument_id,
        ).observe(latency_ms / 1000)

    @staticmethod
    def _parse_retry_after(
        value: str | None,
        *,
        now: datetime | None = None,
        maximum_seconds: int = 86_400,
    ) -> int | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.isdigit():
            digits = normalized.lstrip("0") or "0"
            if len(digits) > len(str(maximum_seconds)):
                return maximum_seconds
            return min(maximum_seconds, int(digits))
        try:
            retry_at = ensure_utc(parsedate_to_datetime(normalized))
        except (TypeError, ValueError, OverflowError):
            return None
        current = ensure_utc(now or utc_now())
        seconds = max(0, math.ceil((retry_at - current).total_seconds()))
        return min(maximum_seconds, seconds)

    @staticmethod
    def _is_fresh(
        quote: ProviderQuote,
        provider: ProviderDefinition,
        instrument: InstrumentDefinition,
    ) -> bool:
        if (
            quote.validation_status is not ValidationStatus.ACCEPTED
            or quote.price is None
            or quote.persistence_status is not PersistenceStatus.PERSISTED
        ):
            return False
        return (
            ProviderQuoteCollector._cache_status(quote, provider, instrument)
            is FreshnessStatus.LIVE
        )

    @staticmethod
    def _cache_status(
        quote: ProviderQuote | None,
        provider: ProviderDefinition,
        instrument: InstrumentDefinition,
    ) -> FreshnessStatus | None:
        if quote is None:
            return None
        if quote.validation_status is not ValidationStatus.ACCEPTED or quote.price is None:
            return FreshnessStatus.EXPIRED
        try:
            boundaries = ProviderQuoteCollector._freshness_boundaries(
                quote,
                provider,
                instrument,
            )
        except ValueError:
            return FreshnessStatus.EXPIRED
        return boundaries.status_at(utc_now())

    @staticmethod
    def _freshness_boundaries(
        quote: ProviderQuote,
        provider: ProviderDefinition,
        instrument: InstrumentDefinition,
    ):
        policy = FreshnessPolicy(
            maximum_source_age_seconds=min(
                provider.maximum_source_age_seconds
                or provider.operational_ttl_seconds,
                instrument.expire_after_seconds,
            ),
            provider_live_ttl_seconds=provider.operational_ttl_seconds,
            instrument_operational_ttl_seconds=instrument.operational_ttl_seconds,
            instrument_stale_after_seconds=instrument.stale_after_seconds,
            instrument_expire_after_seconds=instrument.expire_after_seconds,
            anchor_live_window_at_receive_time=(
                provider.anchor_live_window_at_receive_time
            ),
        )
        return freshness_boundaries(
            quote.observed_at,
            quote.received_at,
            policy,
        )

    @staticmethod
    def _apply_current_live_boundary(
        quote: ProviderQuote,
        provider: ProviderDefinition,
        instrument: InstrumentDefinition,
    ) -> None:
        boundaries = ProviderQuoteCollector._freshness_boundaries(
            quote,
            provider,
            instrument,
        )
        quote.metadata["effective_live_eligible_until"] = (
            boundaries.live_eligible_until.isoformat()
        )

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
