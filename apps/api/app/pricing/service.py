from __future__ import annotations

import asyncio
import secrets
from decimal import Decimal
from typing import Any, Iterable

import httpx

from .anomaly import AnomalyAssessment, DynamicAnomalyDetector, anomaly_detector
from .backfill import PricingBackfillQueue, backfill_queue
from .budgets import RedisRequestBudget, pricing_budget
from .cache import PricingRedisStore, PricingRedisUnavailable, pricing_redis
from .canonical import CanonicalPricePolicy, canonical_policy
from .derived import DerivedPriceEngine, DerivedPriceUnavailable, derived_price_engine
from .freshness import FreshnessStatus
from .history import HistoryResult, InternalPriceHistory, internal_history
from .instruments import INSTRUMENTS, get_instrument
from .locks import DistributedPricingLocks, pricing_locks
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    PersistenceStatus,
    ProviderQuote,
    ProviderRole,
    RequestPurpose,
    ValidationStatus,
    utc_now,
)
from .persistence import PricingPersistence, pricing_persistence
from .operational import OperationalPricingSettings, operational_pricing_settings
from .providers import ProviderQuoteCollector, QuoteFetchOutcome, provider_collector
from .registry import PROVIDERS_BY_INSTRUMENT, ProviderDefinition
from .source_policy import SourceEligibilityPolicy, source_eligibility_policy
from .telegram import StoredTelegramQuoteRepository, stored_telegram_quotes


class PricingRefreshSuspended(RuntimeError):
    pass


class InstrumentPricingService:
    def __init__(
        self,
        *,
        store: PricingRedisStore = pricing_redis,
        locks: DistributedPricingLocks = pricing_locks,
        budgets: RedisRequestBudget = pricing_budget,
        collector: ProviderQuoteCollector = provider_collector,
        detector: DynamicAnomalyDetector = anomaly_detector,
        policy: CanonicalPricePolicy = canonical_policy,
        derived: DerivedPriceEngine = derived_price_engine,
        history: InternalPriceHistory = internal_history,
        persistence: PricingPersistence = pricing_persistence,
        backfill: PricingBackfillQueue = backfill_queue,
        operational: OperationalPricingSettings = operational_pricing_settings,
        telegram_quotes: StoredTelegramQuoteRepository = stored_telegram_quotes,
        source_policy: SourceEligibilityPolicy = source_eligibility_policy,
    ) -> None:
        self.store = store
        self.locks = locks
        self.budgets = budgets
        self.collector = collector
        self.detector = detector
        self.policy = policy
        self.derived = derived
        self.history = history
        self.persistence = persistence
        self.backfill = backfill
        self.operational = operational
        self.telegram_quotes = telegram_quotes
        self.source_policy = source_policy

    async def initialize(self) -> None:
        await self.persistence.sync_provider_catalog()

    async def refresh_instrument(self, instrument_id: str) -> CanonicalQuote | None:
        instrument = await self.operational.instrument(instrument_id)
        if not instrument.enabled:
            return None
        if not await self.store.ping():
            raise PricingRefreshSuspended(
                "Redis is unavailable; distributed pricing refresh is suspended"
            )
        async with self.locks.refresh_lock(instrument.instrument_id) as lease:
            if lease is None:
                return await self.get_canonical(instrument.instrument_id)
            previous = await self.get_canonical(instrument.instrument_id)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=3.0),
                follow_redirects=False,
            ) as client:
                primary = await self._normal_quote(instrument, client)
                if primary is None or not primary.usable or primary.quote is None:
                    primary = await self._fallback_quote(instrument, client)

                if primary is None or not primary.usable or primary.quote is None:
                    telegram = await self._try_telegram_fallback(instrument, previous)
                    if telegram is not None:
                        await self._attach_changes(telegram)
                        return await self._commit(telegram, previous)
                    derived = await self._try_derived(instrument)
                    if derived is None:
                        return previous
                    persistence_result = await self.persistence.persist_provider_quote(
                        derived
                    )
                    if not persistence_result.persisted:
                        return previous
                    await self.store.set_provider_quote(
                        derived, instrument.operational_ttl_seconds
                    )
                    canonical = self.policy.derived_fallback(
                        instrument=instrument, derived=derived
                    )
                    await self._attach_changes(canonical)
                    return await self._commit(canonical, previous)

                candidate = primary.quote
                assessment = await self._assess_candidate(candidate, previous, instrument)
                if assessment is not None and assessment.is_suspicious:
                    candidate.is_suspicious = True
                    candidate.validation_status = ValidationStatus.SUSPICIOUS
                    if primary.sanitized_payload:
                        candidate.raw_payload_reference = await self.persistence.store_raw_payload(
                            provider_id=candidate.provider_id,
                            instrument_id=candidate.instrument_id,
                            reason="anomaly",
                            sanitized_text=primary.sanitized_payload,
                            content_type=primary.content_type,
                        )
                    try:
                        await self.persistence.mark_provider_quote_suspicious(candidate)
                    except Exception:
                        pass
                    await self.store.set_provider_quote(
                        candidate,
                        self._provider_ttl(candidate.provider_id, instrument.operational_ttl_seconds),
                    )
                    anomaly_id = await self.persistence.persist_anomaly(
                        instrument_id=instrument.instrument_id,
                        candidate_quote_id=candidate.id,
                        previous_canonical_quote_id=previous.id if previous else None,
                        deviation_percent=assessment.deviation_percent,
                        dynamic_threshold_percent=assessment.dynamic_threshold_percent,
                        severity=assessment.severity,
                        reason=assessment.reason,
                    )
                    publish_base = previous
                    if previous is not None:
                        verifying = self.policy.keep_previous(
                            previous=previous,
                            candidate=candidate,
                            assessment=assessment,
                            status=CanonicalStatus.VERIFYING,
                        )
                        publish_base = await self._commit(verifying, previous)
                    verifiers = await self._verification_quotes(
                        instrument.instrument_id,
                        candidate,
                        assessment,
                        client,
                    )
                    decision = self.policy.select(
                        instrument=instrument,
                        primary=candidate,
                        previous=previous,
                        assessment=assessment,
                        verifier_quotes=verifiers,
                        from_fresh_cache=primary.from_fresh_cache,
                    )
                    await self.persistence.persist_verification(
                        anomaly_id=anomaly_id,
                        instrument_id=instrument.instrument_id,
                        decision=decision.verification,
                    )
                    canonical = decision.canonical
                    await self._attach_changes(canonical)
                    return await self._commit(canonical, publish_base)

                decision = self.policy.select(
                    instrument=instrument,
                    primary=candidate,
                    previous=previous,
                    assessment=assessment,
                    verifier_quotes=[],
                    from_fresh_cache=primary.from_fresh_cache,
                )
                canonical = decision.canonical
                await self._attach_changes(canonical)
                return await self._commit(canonical, previous)

    async def refresh_cycle(self) -> dict[str, str]:
        if not await self.store.ping():
            return {instrument_id: "suspended_redis_unavailable" for instrument_id in INSTRUMENTS}
        results: dict[str, str] = {}
        for instrument_id in _REFRESH_ORDER:
            current = await self.get_canonical(instrument_id)
            if current is not None and utc_now() <= current.valid_until:
                results[instrument_id] = "fresh"
                continue
            try:
                refreshed = await self.refresh_instrument(instrument_id)
                results[instrument_id] = refreshed.effective_status().value if refreshed else "unavailable"
            except Exception as exc:
                results[instrument_id] = f"failed:{type(exc).__name__}"
            await asyncio.sleep(secrets.randbelow(250) / 1000)
        return results

    async def get_canonical(self, instrument_id: str) -> CanonicalQuote | None:
        normalized = get_instrument(instrument_id).instrument_id
        try:
            cached = await self.store.get_canonical(normalized)
            if cached is not None:
                return cached
        except Exception:
            pass
        try:
            return await self.history.latest_canonical(normalized)
        except Exception:
            return None

    async def get_all_canonical(self) -> dict[str, CanonicalQuote]:
        cached: dict[str, CanonicalQuote] = {}
        try:
            cached = await self.store.get_all_canonical()
        except Exception:
            pass
        try:
            database = await self.history.latest_all()
        except Exception:
            database = {}
        return {**database, **cached}

    async def list_instruments(self, *, authenticated: bool = False) -> list[dict[str, Any]]:
        snapshots = await self.get_all_canonical()
        return [
            self._instrument_payload(
                instrument_id,
                snapshots.get(instrument_id),
                authenticated=authenticated,
            )
            for instrument_id in INSTRUMENTS
        ]

    async def instrument(
        self, instrument_id: str, *, authenticated: bool = False
    ) -> dict[str, Any]:
        definition = get_instrument(instrument_id)
        quote = await self.get_canonical(definition.instrument_id)
        return self._instrument_payload(
            definition.instrument_id, quote, authenticated=authenticated
        )

    async def canonical_history(
        self, instrument_id: str, timeframe: str
    ) -> HistoryResult:
        result = await self.history.canonical_history(
            get_instrument(instrument_id).instrument_id, timeframe
        )
        if result.status == "partial":
            try:
                await self.backfill.enqueue(
                    instrument_id=result.instrument_id,
                    range_start=result.range_start,
                    range_end=(result.missing_before or result.range_end),
                    priority=250,
                )
            except Exception:
                pass
        return result

    async def sources(
        self, instrument_id: str, *, authenticated: bool
    ) -> dict[str, Any]:
        normalized = get_instrument(instrument_id).instrument_id
        if not await self.operational.feature_enabled("comparison_visible"):
            return {
                "instrument_id": normalized,
                "visible": False,
                "source_count": 0,
                "usable_source_count": 0,
                "sources": [],
                "details": [],
            }
        try:
            rows = await self.history.latest_sources(normalized)
        except Exception:
            rows = []
            for provider in PROVIDERS_BY_INSTRUMENT.get(normalized, ()):
                try:
                    quote = await self.store.get_provider_quote(
                        provider.provider_id, normalized
                    )
                except PricingRedisUnavailable:
                    break
                if quote is not None:
                    rows.append(quote.to_dict(authenticated=True))
        if not authenticated:
            usable = sum(
                1 for row in rows if row.get("validation_status") == "accepted"
            )
            return {
                "instrument_id": normalized,
                "source_count": len(rows),
                "usable_source_count": usable,
                "sources": [],
                "details": [],
                "authentication_required_for_details": True,
            }
        return {
            "instrument_id": normalized,
            "source_count": len(rows),
            "sources": rows,
            "details": rows,
        }

    async def source_history(
        self, instrument_id: str, timeframe: str, provider_id: str | None
    ) -> dict[str, Any]:
        normalized = get_instrument(instrument_id).instrument_id
        if not await self.operational.feature_enabled("comparison_visible"):
            return {
                "instrument_id": normalized,
                "timeframe": timeframe,
                "status": "disabled",
                "visible": False,
                "sources": [],
            }
        return await self.history.provider_history(
            normalized,
            timeframe,
            provider_id,
        )

    async def verification(
        self, instrument_id: str, *, authenticated: bool
    ) -> dict[str, Any]:
        return await self.history.verification_details(
            get_instrument(instrument_id).instrument_id,
            authenticated=authenticated,
        )

    async def flush_persistence_backlog(self, batch_size: int = 100) -> dict[str, int]:
        return await self.persistence.flush_stream(batch_size=batch_size)

    async def process_backfill_jobs(self, maximum_jobs: int = 2) -> dict[str, int]:
        return await self.backfill.process_jobs(maximum_jobs=maximum_jobs)

    async def provider_catalog(self, *, authenticated: bool = False) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for instrument_id in INSTRUMENTS:
            providers = await self.operational.providers_for(instrument_id)
            for provider in providers:
                runtime = None
                try:
                    runtime = await self.store.get_provider_runtime(
                        provider.provider_id, instrument_id
                    )
                except Exception:
                    pass
                row: dict[str, Any] = {
                    "instrument_id": instrument_id,
                    "provider_id": provider.provider_id,
                    "display_name": provider.display_name,
                    "role": provider.role.value,
                    "enabled": provider.enabled,
                    "configured": provider.configured(_settings_object()),
                    "status": runtime.operational_status if runtime else "unknown",
                    "last_success_at": (
                        runtime.last_success_at.isoformat()
                        if runtime and runtime.last_success_at
                        else None
                    ),
                }
                if authenticated:
                    row.update(
                        {
                            "priority": provider.priority,
                            "trust_score": float(provider.trust_score),
                            "parser_version": provider.parser_version,
                            "operational_ttl_seconds": provider.operational_ttl_seconds,
                            "budget": {
                                "requests_per_minute": provider.budget.requests_per_minute,
                                "requests_per_hour": provider.budget.requests_per_hour,
                                "requests_per_day": provider.budget.requests_per_day,
                                "reserved_anomaly_requests": provider.budget.reserved_anomaly_requests,
                                "reserved_fallback_requests": provider.budget.reserved_fallback_requests,
                            },
                            "runtime": runtime.to_dict() if runtime else None,
                        }
                    )
                rows.append(row)
        return {"providers": rows}

    async def _normal_quote(
        self, instrument: Any, client: httpx.AsyncClient
    ) -> QuoteFetchOutcome | None:
        primaries = await self.operational.providers_for(
            instrument.instrument_id, ProviderRole.PRIMARY
        )
        if not primaries:
            return None
        ranked = await self._rank_candidates(primaries, instrument)
        maximum_external_calls = min(
            len(ranked),
            2 if instrument.importance >= 8 else 1,
        )
        return await self._first_usable(
            ranked,
            RequestPurpose.NORMAL,
            client,
            maximum_external_calls=maximum_external_calls,
            instrument=instrument,
        )

    async def _fallback_quote(
        self,
        instrument: Any,
        client: httpx.AsyncClient,
        *,
        maximum_external_calls: int | None = None,
    ) -> QuoteFetchOutcome | None:
        candidates = await self.operational.providers_for(
            instrument.instrument_id, ProviderRole.FALLBACK, ProviderRole.VERIFIER
        )
        ranked = await self._rank_candidates(candidates, instrument)
        call_limit = (
            min(len(ranked), 2)
            if maximum_external_calls is None
            else min(len(ranked), max(0, maximum_external_calls))
        )
        return await self._first_usable(
            ranked,
            RequestPurpose.FALLBACK,
            client,
            maximum_external_calls=call_limit,
            instrument=instrument,
        )

    async def _verification_quotes(
        self,
        instrument_id: str,
        candidate: ProviderQuote,
        assessment: AnomalyAssessment,
        client: httpx.AsyncClient,
    ) -> list[ProviderQuote]:
        instrument = await self.operational.instrument(instrument_id)
        ranked = await self._rank_verifiers(
            provider
            for provider in await self.operational.providers_for(
                instrument_id, ProviderRole.VERIFIER, ProviderRole.COMPARE
            )
            if provider.provider_id != candidate.provider_id
            and self._provider_is_independent(candidate, provider)
        )
        quotes: list[ProviderQuote] = []
        for provider in ranked:
            outcome = await self.collector.quote(
                provider,
                RequestPurpose.ANOMALY,
                client=client,
                instrument=instrument,
            )
            if outcome.usable and outcome.quote is not None:
                quotes.append(outcome.quote)
                confirms = (
                    outcome.quote.price is not None
                    and candidate.price is not None
                    and abs(outcome.quote.price - candidate.price)
                    / outcome.quote.price
                    * Decimal(100)
                    <= assessment.dynamic_threshold_percent
                )
                if confirms:
                    break
            if len(quotes) >= 1 and not (
                assessment.severity in {"high", "critical"}
                and instrument.importance >= 8
                and instrument.maximum_verification_depth >= 2
            ):
                break
            if len(quotes) >= instrument.maximum_verification_depth:
                break
        remaining = max(0, instrument.maximum_verification_depth - len(quotes))
        has_confirmation = any(
            quote.price is not None
            and candidate.price is not None
            and abs(quote.price - candidate.price) / quote.price * Decimal(100)
            <= assessment.dynamic_threshold_percent
            for quote in quotes
        )
        if remaining and not has_confirmation:
            try:
                stored = await self.telegram_quotes.latest(
                    instrument,
                    roles=("verifier",),
                )
                accepted_telegram = self.source_policy.telegram_verifiers(
                    instrument=instrument,
                    candidate=candidate,
                    quotes=stored,
                    maximum_difference_percent=assessment.dynamic_threshold_percent,
                    maximum_count=remaining,
                )
            except Exception:
                accepted_telegram = []
            quotes.extend(accepted_telegram)
        return quotes

    @staticmethod
    def _provider_is_independent(
        candidate: ProviderQuote,
        provider: ProviderDefinition,
    ) -> bool:
        candidate_family = str(
            candidate.source_family or candidate.provider_id
        ).strip().lower()
        candidate_venue = str(
            candidate.venue or candidate.source_family or candidate.provider_id
        ).strip().lower()
        provider_family = str(
            provider.source_family or provider.provider_id
        ).strip().lower()
        provider_venue = str(
            provider.venue or provider.source_family or provider.provider_id
        ).strip().lower()
        return (
            candidate_family != provider_family
            and candidate_venue != provider_venue
        )

    async def _rank_verifiers(
        self, providers: Iterable[ProviderDefinition]
    ) -> list[ProviderDefinition]:
        scored: list[tuple[Decimal, ProviderDefinition]] = []
        for provider in providers:
            if not provider.enabled or not provider.configured(_settings_object()):
                continue
            runtime = await self.store.get_provider_runtime(
                provider.provider_id, provider.instrument_id
            )
            pressure = Decimal(str(await self.budgets.pressure(provider)))
            circuit_penalty = Decimal(1000) if runtime.circuit_state.value == "open" else Decimal(0)
            score = (
                provider.trust_score * Decimal(100)
                + runtime.success_rate * Decimal(20)
                - pressure * Decimal(30)
                - provider.budget.estimated_request_cost * Decimal(2)
                - circuit_penalty
            )
            scored.append((score, provider))
        scored.sort(key=lambda item: (item[0], -item[1].priority), reverse=True)
        return [item[1] for item in scored]

    async def _first_usable(
        self,
        providers: Iterable[ProviderDefinition],
        purpose: RequestPurpose,
        client: httpx.AsyncClient,
        *,
        maximum_external_calls: int,
        instrument: Any,
    ) -> QuoteFetchOutcome | None:
        candidates = list(providers)
        trace: list[dict[str, object]] = []
        for provider in candidates:
            cache_reason = "no_live_cached_quote"
            try:
                cached = await self.store.get_provider_quote(
                    provider.provider_id,
                    provider.instrument_id,
                )
            except Exception:
                cached = None
                cache_result = "read_failed"
                cache_reason = "cache_read_failed"
            else:
                cache_status = ProviderQuoteCollector._cache_status(
                    cached,
                    provider,
                    instrument,
                )
                cache_result = cache_status.value if cache_status is not None else "miss"
                provider_eligible = bool(
                    provider.enabled and provider.configured(_settings_object())
                )
                if cache_status is FreshnessStatus.LIVE and not provider_eligible:
                    cache_result = "ineligible"
                    cache_reason = (
                        "provider_disabled"
                        if not provider.enabled
                        else "disabled_missing_key"
                    )
                elif (
                    cached is not None
                    and cache_status is FreshnessStatus.LIVE
                    and cached.persistence_status is not PersistenceStatus.PERSISTED
                ):
                    cache_result = "ineligible"
                    cache_reason = "source_not_persisted"
                if (
                    cached is not None
                    and cache_status is FreshnessStatus.LIVE
                    and provider_eligible
                    and cached.persistence_status is PersistenceStatus.PERSISTED
                ):
                    ProviderQuoteCollector._apply_current_live_boundary(
                        cached,
                        provider,
                        instrument,
                    )
                    trace.append(
                        {
                            "provider_id": provider.provider_id,
                            "stage": "cache",
                            "result": "selected_live_cache",
                            "reason": None,
                        }
                    )
                    return QuoteFetchOutcome(
                        quote=cached,
                        usable=True,
                        from_fresh_cache=True,
                        external_called=False,
                        failure_reason=None,
                        cache_status=FreshnessStatus.LIVE,
                        selection_trace=trace,
                    )
            trace.append(
                {
                    "provider_id": provider.provider_id,
                    "stage": "cache",
                    "result": cache_result,
                    "reason": cache_reason,
                }
            )

        last: QuoteFetchOutcome | None = None
        external_calls = 0
        for index, provider in enumerate(candidates):
            if external_calls >= maximum_external_calls:
                trace.extend(
                    {
                        "provider_id": skipped.provider_id,
                        "stage": "external",
                        "result": "skipped",
                        "reason": "external_call_budget_exhausted",
                    }
                    for skipped in candidates[index:]
                )
                break
            outcome = await self.collector.quote(
                provider, purpose, client=client, instrument=instrument
            )
            last = outcome
            trace.append(
                {
                    "provider_id": provider.provider_id,
                    "stage": "external",
                    "result": "selected" if outcome.usable else "not_selected",
                    "reason": outcome.failure_reason,
                }
            )
            if outcome.usable:
                outcome.selection_trace = trace
                return outcome
            external_calls += int(outcome.external_called)
        if last is not None:
            last.selection_trace = trace
        return last

    async def _rank_candidates(
        self,
        providers: Iterable[ProviderDefinition],
        instrument: Any,
    ) -> list[ProviderDefinition]:
        ranked: list[tuple[tuple[float, ...], ProviderDefinition]] = []
        for provider in providers:
            try:
                cached = await self.store.get_provider_quote(
                    provider.provider_id,
                    provider.instrument_id,
                )
                cache_status = ProviderQuoteCollector._cache_status(
                    cached,
                    provider,
                    instrument,
                )
            except Exception:
                cached = None
                cache_status = None
            try:
                runtime = await self.store.get_provider_runtime(
                    provider.provider_id,
                    provider.instrument_id,
                )
                success_rate = float(runtime.success_rate)
                circuit_ready = float(runtime.circuit_state.value != "open")
            except Exception:
                success_rate = 0.0
                circuit_ready = 1.0
            try:
                pressure = float(await self.budgets.pressure(provider))
            except Exception:
                pressure = 1.0
            freshness = cached.observed_at.timestamp() if cached is not None else 0.0
            configured = float(
                provider.enabled and provider.configured(_settings_object())
            )
            saved_cache = bool(
                cached is not None
                and cached.persistence_status is PersistenceStatus.PERSISTED
            )
            score = (
                float(
                    cache_status is FreshnessStatus.LIVE
                    and configured == 1.0
                    and saved_cache
                ),
                configured,
                circuit_ready,
                success_rate,
                float(provider.trust_score),
                -pressure,
                freshness,
                -float(provider.priority),
                -float(provider.budget.estimated_request_cost),
            )
            ranked.append((score, provider))
        ranked.sort(key=lambda item: (item[0], item[1].provider_id), reverse=True)
        return [provider for _score, provider in ranked]

    async def _assess_candidate(
        self,
        candidate: ProviderQuote,
        previous: CanonicalQuote | None,
        instrument: Any,
    ) -> AnomalyAssessment | None:
        if previous is None or candidate.price is None:
            return None
        try:
            recent = [quote.price for quote in await self.store.recent_canonical(candidate.instrument_id)]
        except PricingRedisUnavailable:
            recent = []
        if len(recent) < 3:
            try:
                recent = await self.history.recent_prices(candidate.instrument_id)
            except Exception:
                recent = []
        runtime = await self.store.get_provider_runtime(
            candidate.provider_id, candidate.instrument_id
        )
        return self.detector.assess(
            instrument=instrument,
            candidate_price=candidate.price,
            previous_price=previous.price,
            previous_observed_at=previous.observed_at,
            recent_prices=recent,
            provider_success_rate=runtime.success_rate,
        )

    async def _try_derived(self, instrument: Any) -> ProviderQuote | None:
        if (
            not instrument.allow_derived_fallback
            or not await self.operational.feature_enabled("derived_fallback_enabled")
        ):
            return None
        snapshots = await self.get_all_canonical()
        try:
            return self.derived.derive(instrument.instrument_id, snapshots)
        except DerivedPriceUnavailable:
            return None

    async def _try_telegram_fallback(
        self,
        instrument: Any,
        previous: CanonicalQuote | None,
    ) -> CanonicalQuote | None:
        try:
            stored = await self.telegram_quotes.latest(
                instrument,
                roles=("fallback",),
            )
        except Exception:
            return None
        try:
            current = utc_now()
            reference_price = (
                previous.price
                if previous is not None and current <= previous.expires_at
                else None
            )
            decision = self.source_policy.telegram_fallback(
                instrument=instrument,
                quotes=stored,
                maximum_difference_percent=instrument.base_anomaly_threshold_percent,
                reference_price=reference_price,
                now=current,
            )
            if not decision.eligible or decision.price is None:
                return None
            selected_ids = set(decision.quote_ids)
            if not selected_ids:
                return None
            selected = [
                quote
                for quote in stored
                if quote.id is not None and quote.id in selected_ids
            ]
            if len(selected) != len(selected_ids):
                return None
            return self.policy.telegram_fallback(
                instrument=instrument,
                quotes=selected,
                price=decision.price,
                reason=decision.reason,
                current=current,
            )
        except Exception:
            return None

    async def _attach_changes(self, quote: CanonicalQuote) -> None:
        try:
            changes = await self.history.changes(
                quote.instrument_id, quote.price, quote.canonical_at
            )
        except Exception:
            return
        quote.change_1h = changes["1h"]
        quote.change_24h = changes["24h"]
        quote.change_7d = changes["7d"]
        quote.change_30d = changes["30d"]

    async def _commit(
        self,
        quote: CanonicalQuote,
        previous: CanonicalQuote | None,
    ) -> CanonicalQuote:
        quote.sequence_number = await self.store.next_sequence()
        await self.persistence.persist_canonical(quote)
        await self.store.set_canonical(quote)
        await self.store.append_short_history(quote)
        if self._publication_changed(previous, quote):
            await self.store.publish_canonical(quote)
        return quote

    @staticmethod
    def _publication_changed(
        previous: CanonicalQuote | None, current: CanonicalQuote
    ) -> bool:
        if previous is None:
            return True
        return any(
            (
                previous.price != current.price,
                previous.effective_status() != current.effective_status(),
                previous.candidate_price != current.candidate_price,
                previous.verification_status != current.verification_status,
                previous.is_persisted != current.is_persisted,
            )
        )

    @staticmethod
    def _provider_ttl(provider_id: str, default: int) -> int:
        from .registry import PROVIDERS

        provider = PROVIDERS.get(provider_id)
        return provider.operational_ttl_seconds if provider else default

    @staticmethod
    def _instrument_payload(
        instrument_id: str,
        quote: CanonicalQuote | None,
        *,
        authenticated: bool,
    ) -> dict[str, Any]:
        definition = get_instrument(instrument_id)
        payload = definition.to_public_dict()
        payload["canonical"] = (
            quote.to_dict(authenticated=authenticated)
            if quote is not None
            else {
                "instrument_id": instrument_id,
                "price": None,
                "status": CanonicalStatus.UNAVAILABLE.value,
                "age_seconds": None,
                "canonical_at": None,
            }
        )
        return payload


def _settings_object() -> object:
    from ..config import settings

    return settings


_REFRESH_ORDER = (
    "USDT_USD",
    "USDT_TOMAN",
    "BTC_USD",
    "XAU_USD_OZ",
    "XAG_USD_OZ",
    "BTC_TOMAN",
    "GOLD_24K_TOMAN_GRAM",
    "GOLD_18K_TOMAN_GRAM",
    "SILVER_999_TOMAN_GRAM",
    "SILVER_925_TOMAN_GRAM",
)


instrument_pricing_service = InstrumentPricingService()
