from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, func, or_, select

from ..config import settings
from ..db import SessionLocal
from .budgets import RedisRequestBudget, pricing_budget
from .cache import PricingRedisStore, pricing_redis
from .db_models import PricingBackfillJobRecord
from .instruments import get_instrument
from .locks import DistributedPricingLocks, pricing_locks
from .models import (
    CanonicalQuote,
    CanonicalStatus,
    PersistenceStatus,
    PriceSemantic,
    ProviderQuote,
    RequestPurpose,
    SourceType,
    ValidationStatus,
    VerificationStatus,
    canonical_json,
    ensure_utc,
    parse_datetime,
    utc_now,
)
from .operational import OperationalPricingSettings, operational_pricing_settings
from .parsers.history import build_history_parser
from .persistence import PricingPersistence, pricing_persistence
from .providers import ProviderQuoteCollector
from .registry import PROVIDERS_BY_INSTRUMENT, ProviderDefinition
from . import rights


@dataclass(frozen=True, slots=True)
class BackfillEnqueueResult:
    status: str
    idempotency_key: str
    database_job_id: int | None
    stream_event_id: str | None


class HistoryBudgetDeferred(RuntimeError):
    """A subsequent history page needs quota; the original range stays pending."""


def _servix_history_windows(start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], ...]:
    """Bound each request to 31 dates without changing source timestamps."""
    start, end = ensure_utc(start), ensure_utc(end)
    if start >= end:
        raise ValueError("Backfill range must have a positive duration")
    if end - start > timedelta(days=366):
        raise ValueError("history_range_exceeds_one_year")
    windows = []
    cursor = start
    while cursor < end:
        # Adjacent windows share midnight. A source observation at that exact
        # endpoint keeps its timestamp and is deduplicated by persistence.
        boundary = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=30)
        window_end = min(boundary, end)
        windows.append((cursor, window_end))
        cursor = window_end
    if len(windows) > 13:
        raise ValueError("history_window_limit_exceeded")
    return tuple(windows)


def _history_rights_allowed(provider: ProviderDefinition) -> bool:
    return (all(rights.provider_allowed(provider.provider_id, action)
                for action in ("collect", "store", "history"))
            and bool(provider.history_url)
            and rights.endpoint_allowed(provider.provider_id, provider.history_url))


def _history_request_options(
    provider: ProviderDefinition,
    parser: Any,
    range_start: datetime,
    range_end: datetime,
) -> tuple[dict[str, str | int], dict[str, str]]:
    if not _history_rights_allowed(provider):
        raise RuntimeError("history_provider_rights_denied")
    if not provider.history_url:
        raise RuntimeError("history_provider_url_missing")
    if parser.parser_version.startswith("coingecko-market-chart/"):
        days = max(
            1,
            min(365, int((range_end - range_start).total_seconds() / 86400) + 1),
        )
        params: dict[str, str | int] = {"vs_currency": "usd", "days": str(days)}
    elif parser.parser_version.startswith("nerkhsanj-daily-history/"):
        if range_end - range_start > timedelta(days=366):
            raise ValueError("history_range_exceeds_one_year")
        params = {}
    elif parser.parser_version.startswith("servix-history/"):
        if (range_end.date() - range_start.date()).days > 30:
            raise ValueError("servix_history_maximum_31_calendar_days")
        params = {
            "from": range_start.date().isoformat(),
            "to": range_end.date().isoformat(),
        }
    else:
        params = {
            "symbol": parser.symbol,
            "resolution": "60",
            "from": int(range_start.timestamp()),
            "to": int(range_end.timestamp()),
        }
    history_provider = replace(provider, url=provider.history_url)
    ProviderQuoteCollector._validate_destination(history_provider)
    headers = dict(provider.static_headers)
    if provider.api_key_setting:
        key = getattr(settings, provider.api_key_setting, None)
        if not key or not provider.api_key_header:
            raise RuntimeError("history_provider_key_missing")
        headers[provider.api_key_header] = str(key)
    return params, headers


class PricingBackfillQueue:
    stream_key = "pricing:backfill-jobs"

    def __init__(
        self,
        store: PricingRedisStore = pricing_redis,
        budgets: RedisRequestBudget = pricing_budget,
        locks: DistributedPricingLocks = pricing_locks,
        persistence: PricingPersistence = pricing_persistence,
        operational: OperationalPricingSettings = operational_pricing_settings,
    ) -> None:
        self.store = store
        self.budgets = budgets
        self.locks = locks
        self.persistence = persistence
        self.operational = operational
        self.batch_size = settings.pricing_backfill_batch_size
        self.maximum_length = _positive_int_env("PRICING_BACKFILL_STREAM_MAXLEN", 10_000)
        self.maximum_attempts = _positive_int_env("PRICING_BACKFILL_MAX_ATTEMPTS", 5)
        self.automatic_locks = DistributedPricingLocks(store)

    async def enqueue_automatic(
        self,
        *,
        instrument_id: str,
        range_start: datetime,
        range_end: datetime,
        bucket_seconds: int,
        priority: int = 250,
    ) -> BackfillEnqueueResult:
        """Coalesce chart requests without changing a stored job's actual range."""
        if callable(getattr(type(self.operational), "instruments", None)):
            normalized = get_instrument(instrument_id).instrument_id
            instrument = (await self.operational.instruments((normalized,)))[normalized]
        else:
            instrument = await self.operational.instrument(instrument_id)
        start, end = ensure_utc(range_start), ensure_utc(range_end)
        if start >= end or bucket_seconds <= 0:
            raise ValueError("Automatic backfill range and bucket must be positive")
        raw = f"{instrument.instrument_id}|{int(start.timestamp()) // bucket_seconds}|{int(end.timestamp()) // bucket_seconds}|{bucket_seconds}"
        daily_history = False
        if any(provider.history_only for provider in PROVIDERS_BY_INSTRUMENT.get(instrument.instrument_id, ())):
            history_provider = await self._history_provider(instrument.instrument_id)
            daily_history = bool(history_provider and history_provider.history_only)
        if daily_history:
            # Sparse daily archives cannot fill intraday/holiday gaps. Repeated
            # chart polls share one durable job per Tehran calendar range/day.
            tehran = ZoneInfo("Asia/Tehran")
            raw = f"daily|{instrument.instrument_id}|{start.astimezone(tehran).date()}|{end.astimezone(tehran).date()}|{bucket_seconds}"
        key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if daily_history and end - start < timedelta(days=1):
            return BackfillEnqueueResult("unsupported", key, None, None)
        if not instrument.enabled or not await self.operational.feature_enabled(
            "backfill_enabled", scope_id=instrument.instrument_id
        ):
            return BackfillEnqueueResult("disabled", key, None, None)
        try:
            lease = await self.automatic_locks.acquire(f"pricing:backfill-auto:{key}", 60_000)
        except Exception:
            # No unguarded fallback: a Redis outage must not create a queue storm.
            return BackfillEnqueueResult("deferred", key, None, None)
        if lease is None:
            return BackfillEnqueueResult("coalesced", key, None, None)
        try:
            # The manual path keeps its exact range, policy reads and retry behavior.
            arguments = {"instrument_id": instrument.instrument_id, "range_start": start,
                         "range_end": end, "priority": priority}
            if daily_history:
                arguments["_automatic_day_key"] = key
            result = await self.enqueue(**arguments)
        except BaseException:
            await self.automatic_locks.release(lease)
            raise
        if result.status not in {"queued", "queued_redis"}:
            await self.automatic_locks.release(lease)
        return result

    async def enqueue(
        self,
        *,
        instrument_id: str,
        range_start: datetime,
        range_end: datetime,
        priority: int = 200,
        _automatic_day_key: str | None = None,
    ) -> BackfillEnqueueResult:
        instrument = await self.operational.instrument(instrument_id)
        start = ensure_utc(range_start)
        end = ensure_utc(range_end)
        if start >= end:
            raise ValueError("Backfill range must have a positive duration")
        raw = f"{instrument.instrument_id}|{start.isoformat()}|{end.isoformat()}"
        idempotency_key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if _automatic_day_key is not None:
            if len(_automatic_day_key) != 64 or any(char not in "0123456789abcdef" for char in _automatic_day_key):
                raise ValueError("Automatic daily history key must be a SHA-256 digest")
            idempotency_key = _automatic_day_key
        if not instrument.enabled or not await self.operational.feature_enabled("backfill_enabled", scope_id=instrument.instrument_id):
            return BackfillEnqueueResult("disabled", idempotency_key, None, None)
        if await self._history_provider(instrument.instrument_id) is None:
            return BackfillEnqueueResult("unsupported", idempotency_key, None, None)
        try:
            job_id = await asyncio.to_thread(
                self._insert_job,
                instrument.instrument_id,
                start,
                end,
                priority,
                idempotency_key,
            )
            return BackfillEnqueueResult("queued", idempotency_key, job_id, None)
        except Exception:
            payload = {
                "instrument_id": instrument.instrument_id,
                "range_start": start.isoformat(),
                "range_end": end.isoformat(),
                "priority": priority,
                "idempotency_key": idempotency_key,
                "created_at": utc_now().isoformat(),
            }
            stream_id = await self.store.client().xadd(
                self.stream_key,
                {"payload": canonical_json(payload), "idempotency_key": idempotency_key},
                maxlen=self.maximum_length,
                approximate=True,
            )
            return BackfillEnqueueResult(
                "queued_redis", idempotency_key, None, str(stream_id)
            )

    async def process_jobs(self, maximum_jobs: int = 2) -> dict[str, int]:
        if not await self.store.ping():
            return {"completed": 0, "deferred": 0, "failed": 0}
        await self._drain_redis_jobs(maximum_jobs * 2)
        counts = {"completed": 0, "deferred": 0, "failed": 0}
        eligible_instruments = await self._eligible_instruments()
        if not eligible_instruments:
            return counts
        for _ in range(max(1, min(maximum_jobs, 20))):
            job = await asyncio.to_thread(self._claim_job, eligible_instruments)
            if job is None:
                break
            if not await self.operational.feature_enabled("backfill_enabled", scope_id=job["instrument_id"]):
                await asyncio.to_thread(self._finish_job, job["id"], "deferred", "instrument_backfill_disabled", job["attempt_count"])
                counts["deferred"] += 1
                continue
            instrument = await self.operational.instrument(job["instrument_id"])
            if not instrument.enabled:
                await asyncio.to_thread(self._finish_job, job["id"], "deferred", "instrument_disabled", job["attempt_count"])
                counts["deferred"] += 1
                continue
            provider = await self._history_provider(job["instrument_id"])
            if provider is None:
                await asyncio.to_thread(
                    self._finish_job,
                    job["id"],
                    "deferred",
                    "no_explicit_history_provider",
                    job["attempt_count"],
                )
                counts["deferred"] += 1
                continue
            try:
                current = await self.store.get_canonical(job["instrument_id"])
            except Exception:
                current = None
            if current is None or utc_now() > current.valid_until:
                provider = await self._history_provider(
                    job["instrument_id"], independent_of_live=True
                )
            if provider is None or (
                provider.history_requires_live_quote
                and (current is None or utc_now() > current.valid_until)
            ):
                await asyncio.to_thread(
                    self._finish_job,
                    job["id"],
                    "deferred",
                    "live_refresh_has_priority",
                    job["attempt_count"],
                )
                counts["deferred"] += 1
                continue
            if (provider.source_family == "servix"
                    and (job["range_end"].date() - job["range_start"].date()).days > 30):
                try:
                    status = await asyncio.to_thread(self._schedule_servix_history_windows, job, provider)
                except Exception as exc:
                    await asyncio.to_thread(
                        self._retry_job, job["id"],
                        f"{type(exc).__name__}: history scheduling failed", job["attempt_count"],
                    )
                    counts["failed"] += 1
                else:
                    counts[status] += 1
                continue
            async with self.locks.backfill_lock(job["instrument_id"]) as lease:
                if lease is None:
                    await asyncio.to_thread(
                        self._retry_job, job["id"], "backfill_lock_busy", job["attempt_count"]
                    )
                    counts["failed"] += 1
                    continue
                decision = await self.budgets.consume(provider, RequestPurpose.BACKFILL)
                if not decision.allowed:
                    await asyncio.to_thread(
                        self._finish_job, job["id"], "deferred", decision.reason, job["attempt_count"]
                    )
                    counts["deferred"] += 1
                    continue
                try:
                    point_count = await self._execute_history_job(job, provider)
                except HistoryBudgetDeferred:
                    await asyncio.to_thread(
                        self._finish_job, job["id"], "deferred",
                        "history_page_budget_deferred", job["attempt_count"],
                    )
                    counts["deferred"] += 1
                    continue
                except Exception as exc:
                    await asyncio.to_thread(
                        self._retry_job,
                        job["id"],
                        f"{type(exc).__name__}: history fetch failed",
                        job["attempt_count"],
                    )
                    counts["failed"] += 1
                    continue
                if point_count == 0:
                    await asyncio.to_thread(
                        self._finish_job, job["id"], "deferred", "provider_returned_no_history", job["attempt_count"]
                    )
                    counts["deferred"] += 1
                else:
                    await asyncio.to_thread(self._finish_job, job["id"], "completed", None, job["attempt_count"])
                    counts["completed"] += 1
        return counts

    @staticmethod
    def _schedule_servix_history_windows(job: dict[str, Any], provider: ProviderDefinition) -> str:
        """Resume bounded child jobs; a parent never waits for account quota."""
        windows = _servix_history_windows(job["range_start"], job["range_end"])
        if not _history_rights_allowed(provider):
            PricingBackfillQueue._finish_job(
                job["id"], "deferred", "history_provider_rights_revoked", job["attempt_count"]
            )
            return "deferred"
        db = SessionLocal()
        try:
            parent = db.scalar(select(PricingBackfillJobRecord).where(
                PricingBackfillJobRecord.id == job["id"],
            ).with_for_update())
            if (parent is None or parent.status != "processing"
                    or parent.attempt_count != job["attempt_count"]
                    or parent.instrument_id != job["instrument_id"]
                    or ensure_utc(parent.range_start) != ensure_utc(job["range_start"])
                    or ensure_utc(parent.range_end) != ensure_utc(job["range_end"])):
                raise RuntimeError("backfill_job_no_longer_owned")
            keyed_windows = {
                hashlib.sha256(
                    f"servix-window-v1|{parent.instrument_id}|{start.isoformat()}|{end.isoformat()}".encode()
                ).hexdigest(): (start, end)
                for start, end in windows
            }
            children = {row.idempotency_key: row for row in db.scalars(
                select(PricingBackfillJobRecord).where(
                    PricingBackfillJobRecord.idempotency_key.in_(tuple(keyed_windows)),
                ).order_by(PricingBackfillJobRecord.idempotency_key).with_for_update()
            )}
            now = utc_now()
            for key, (start, end) in keyed_windows.items():
                child = children.get(key)
                if child is None:
                    # Current policy may select a permitted fallback later;
                    # the persisted quote records its actual provider.
                    child = PricingBackfillJobRecord(
                        instrument_id=parent.instrument_id,
                        range_start=start, range_end=end, priority=parent.priority,
                        status="pending", attempt_count=0, idempotency_key=key,
                        created_at=now, updated_at=now,
                    )
                    db.add(child)
                    children[key] = child
                elif (child.instrument_id != parent.instrument_id
                      or ensure_utc(child.range_start) != start
                      or ensure_utc(child.range_end) != end):
                    raise RuntimeError("backfill_window_identity_changed")
            states = {child.status for child in children.values()}
            invalid_completion = any(child.status == "completed" and child.completed_at is None
                                     for child in children.values())
            if invalid_completion or not states <= {"pending", "retrying", "processing", "deferred", "completed"}:
                parent.status = "failed"
                parent.last_error = "servix_history_child_failed_or_invalid"
            elif states == {"completed"}:
                parent.status = "completed"
                parent.last_error = "servix_history_windows_fetched; coverage_requires_observation_check"
            else:
                parent.status = "deferred"
                completed = sum(child.status == "completed" for child in children.values())
                parent.last_error = f"servix_history_windows_pending:{completed}/{len(children)}"
                parent.attempt_count = max(0, parent.attempt_count - 1)
            parent.next_attempt_at = now + timedelta(minutes=5) if parent.status == "deferred" else None
            parent.updated_at = now
            parent.completed_at = now if parent.status == "completed" else None
            db.commit()
            return parent.status
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _eligible_instruments(self) -> tuple[str, ...]:
        # Resolve the finite catalogue once per pass, before touching job rows.
        # Unsupported old jobs retain their state and become eligible again
        # when scoped policy or live availability changes on a later pass.
        candidates = tuple(
            instrument_id for instrument_id, providers in PROVIDERS_BY_INSTRUMENT.items()
            if any(provider.history_url and provider.history_parser_id for provider in providers)
        )

        async def eligible(instrument_id: str) -> str | None:
            instrument = await self.operational.instrument(instrument_id)
            if not instrument.enabled or not await self.operational.feature_enabled(
                "backfill_enabled", scope_id=instrument_id
            ):
                return None
            provider = await self._history_provider(instrument_id)
            if provider is None:
                return None
            if not provider.history_requires_live_quote:
                return instrument_id
            try:
                current = await self.store.get_canonical(instrument_id)
            except Exception:
                current = None
            if current is not None and utc_now() <= current.valid_until:
                return instrument_id
            independent = await self._history_provider(instrument_id, independent_of_live=True)
            return instrument_id if independent is not None else None

        resolved = await asyncio.gather(*(eligible(instrument_id) for instrument_id in candidates))
        return tuple(instrument_id for instrument_id in resolved if instrument_id is not None)

    async def backlog(self) -> dict[str, int | None]:
        database_count = await asyncio.to_thread(self._database_backlog)
        try:
            redis_count = int(await self.store.client().xlen(self.stream_key))
        except Exception:
            redis_count = None
        return {"database": database_count, "redis": redis_count}

    async def _execute_history_job(
        self,
        job: dict[str, Any],
        provider: ProviderDefinition,
    ) -> int:
        if not provider.history_url or not provider.history_parser_id:
            return 0
        if not _history_rights_allowed(provider):
            return 0
        parser = build_history_parser(provider.history_parser_id)
        params, headers = _history_request_options(
            provider, parser, job["range_start"], job["range_end"]
        )
        instrument = await self.operational.instrument(job["instrument_id"])
        points = []
        paginated_udf = parser.parser_version.startswith("nobitex-udf-history/")
        windowed_udf = parser.parser_version.startswith("wallex-udf-history/")
        window_start = job["range_start"]
        # Internal boundaries must coincide with complete hourly candle edges.
        window_end = min((window_start + timedelta(days=7)).replace(minute=0, second=0, microsecond=0), job["range_end"])
        if windowed_udf and job["range_end"] - window_start > timedelta(days=366):
            raise ValueError("history_range_exceeds_one_year")
        page = 1
        seen = {}
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=3.0), follow_redirects=False, trust_env=False
        ) as client:
            while True:
                if not _history_rights_allowed(provider):
                    raise RuntimeError("history_provider_rights_revoked")
                if page > 1:
                    # Each page is a real request. Preserve the provider reserve,
                    # live refresh interval and the database claim while waiting.
                    await asyncio.sleep(max(1, provider.budget.minimum_interval_seconds))
                    if not await asyncio.to_thread(self._renew_job, job["id"], job.get("attempt_count")):
                        raise RuntimeError("backfill_job_no_longer_owned")
                    budget = await self.budgets.consume(provider, RequestPurpose.BACKFILL)
                    if not budget.allowed:
                        raise HistoryBudgetDeferred("history_page_budget_deferred")
                request_params = {**params, "page": page} if paginated_udf else params
                if windowed_udf:
                    request_params = {**params, "from": int(window_start.timestamp()), "to": int(window_end.timestamp())}
                async with asyncio.timeout(15):
                    if not _history_rights_allowed(provider):
                        raise RuntimeError("history_provider_rights_revoked")
                    if parser.parser_version.startswith("nerkhsanj-daily-history/"):
                        async with client.stream("GET", provider.history_url, params=request_params, headers=headers) as response:
                            response.raise_for_status()
                            if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                                raise ValueError("history_response_content_type")
                            limit = min(provider.maximum_payload_bytes, 8_388_608)
                            length = response.headers.get("content-length", "")
                            if length.isdigit() and int(length) > limit:
                                raise ValueError("history_payload_too_large")
                            body = bytearray()
                            async for chunk in response.aiter_bytes(chunk_size=65_536):
                                if len(body) + len(chunk) > limit:
                                    raise ValueError("history_payload_too_large")
                                body.extend(chunk)
                            payload = json.loads(body)
                        if not _history_rights_allowed(provider):
                            raise RuntimeError("history_provider_rights_revoked")
                        points = parser.parse(payload, instrument, job["range_start"], job["range_end"])
                        break
                    response = await client.get(provider.history_url, params=request_params, headers=headers)
                if response.status_code == 429:
                    await self.budgets.record_rate_limit(provider)
                    raise RuntimeError("history_provider_rate_limited")
                response.raise_for_status()
                if len(response.content) > min(provider.maximum_payload_bytes * 4, 4_194_304):
                    raise ValueError("history_payload_too_large")
                payload = response.json()
                parse_start = window_start if windowed_udf else job["range_start"]
                parse_end = window_end if windowed_udf else job["range_end"]
                page_points = parser.parse(payload, instrument, parse_start, parse_end)
                if not paginated_udf and not windowed_udf:
                    points = page_points
                    break
                added = 0
                for point in page_points:
                    previous = seen.get(point.observed_at)
                    if previous is not None and (previous.price != point.price or previous.volume != point.volume):
                        raise ValueError("history_conflicting_page_boundary")
                    if previous is None:
                        seen[point.observed_at] = point
                        added += 1
                if windowed_udf:
                    if window_end >= job["range_end"]:
                        points = sorted(seen.values(), key=lambda point: point.observed_at)
                        break
                    window_start = window_end
                    window_end = min(window_start + timedelta(days=7), job["range_end"])
                    page += 1
                    if page > 54 or len(seen) > 20_000:
                        raise ValueError("history_window_limit_exceeded")
                    continue
                raw_count = len(payload.get("t", []))
                if raw_count < 500:
                    points = sorted(seen.values(), key=lambda point: point.observed_at)
                    break
                if not added:
                    raise ValueError("history_pagination_did_not_advance")
                if len(seen) > 20_000 or page >= 41:
                    raise ValueError("history_pagination_limit_exceeded")
                page += 1
        # Process the whole requested range; the batch bound controls yielding.
        last_renewed = time.monotonic()
        for index, point in enumerate(points):
            if not _history_rights_allowed(provider):
                raise RuntimeError("history_provider_rights_revoked")
            if index and (index % max(1, self.batch_size) == 0 or time.monotonic()-last_renewed >= 60):
                if not await asyncio.to_thread(self._renew_job, job["id"], job.get("attempt_count")):
                    raise RuntimeError("backfill_job_no_longer_owned")
                last_renewed = time.monotonic()
                await asyncio.sleep(0)
            if not _history_rights_allowed(provider):
                raise RuntimeError("history_provider_rights_revoked")
            quote = ProviderQuote.create(
                instrument_id=instrument.instrument_id,
                provider_id=provider.provider_id,
                source_type=SourceType.HTTP,
                price=point.price,
                currency=instrument.quote_currency,
                weight_unit=instrument.weight_unit,
                purity=instrument.purity,
                volume=point.volume,
                observed_at=point.observed_at,
                received_at=utc_now(),
                parser_version=parser.parser_version,
                validation_status=ValidationStatus.ACCEPTED,
                confidence_score=provider.trust_score,
                is_direct=True,
                is_derived=False,
                source_semantic=provider.source_semantic,
                source_family=provider.source_family,
                venue=provider.venue,
                last=(
                    point.price
                    if provider.selected_price_semantic is PriceSemantic.LAST
                    else None
                ),
                selected_price_semantic=provider.selected_price_semantic,
                original_currency=instrument.quote_currency.value,
                original_value=point.price,
                conversion_factor=1,
                route_id=f"{provider.route_id}:history",
                metadata={
                    "quote_role": "backfill",
                    "provider_role": provider.role.value,
                    "history_symbol": getattr(parser, "symbol", getattr(parser, "asset_id", "unknown")),
                    "history_point_kind": "hourly_candle_close" if windowed_udf else "provider_observation",
                    **point.metadata,
                },
                persistence_status=PersistenceStatus.UNPERSISTED,
            )
            stored = await self.persistence.persist_provider_quote(quote)
            if not stored.persisted:
                raise RuntimeError("backfill_provider_persistence_unavailable")
            canonical = CanonicalQuote.create(
                instrument_id=instrument.instrument_id,
                price=point.price,
                status=CanonicalStatus.CONFIRMED,
                primary_quote_id=quote.id,
                verification_quote_ids=[],
                source_summary={
                    "primary_provider_id": provider.provider_id,
                    "provider_ids": [provider.provider_id],
                    "source_count": 1,
                    "direct_source_count": 1,
                    "derived": False,
                    "historical_backfill": True,
                    **point.metadata,
                },
                observed_at=point.observed_at,
                canonical_at=point.observed_at,
                valid_until=point.observed_at
                + timedelta(seconds=instrument.operational_ttl_seconds),
                stale_at=point.observed_at
                + timedelta(seconds=instrument.stale_after_seconds),
                expires_at=point.observed_at
                + timedelta(seconds=instrument.expire_after_seconds),
                is_persisted=False,
                decision_reason="historical_primary_provider_backfill",
                verification_status=VerificationStatus.NOT_REQUIRED,
            )
            stored = await self.persistence.persist_canonical(canonical)
            if not stored.persisted:
                raise RuntimeError("backfill_canonical_persistence_unavailable")
        return len(points)

    async def _drain_redis_jobs(self, maximum: int) -> None:
        rows = await self.store.client().xrange(
            self.stream_key, min="-", max="+", count=max(1, maximum)
        )
        for stream_id, fields in rows:
            try:
                payload = json.loads(fields["payload"])
                await asyncio.to_thread(
                    self._insert_job,
                    str(payload["instrument_id"]),
                    parse_datetime(payload["range_start"]),
                    parse_datetime(payload["range_end"]),
                    int(payload.get("priority", 200)),
                    str(payload["idempotency_key"]),
                )
            except Exception:
                break
            await self.store.client().xdel(self.stream_key, stream_id)

    async def _history_provider(
        self,
        instrument_id: str,
        *,
        independent_of_live: bool = False,
    ) -> ProviderDefinition | None:
        return next(
            (
                provider
                for provider in sorted(
                    await self.operational.providers_for(instrument_id),
                    key=lambda item: (item.history_priority, item.priority, item.provider_id),
                )
                if provider.enabled
                and _history_rights_allowed(provider)
                and provider.configured(settings)
                and provider.history_url
                and provider.history_parser_id
                and (
                    not independent_of_live
                    or not provider.history_requires_live_quote
                )
            ),
            None,
        )

    @staticmethod
    def _insert_job(
        instrument_id: str,
        start: datetime,
        end: datetime,
        priority: int,
        idempotency_key: str,
    ) -> int:
        db = SessionLocal()
        try:
            existing = db.scalar(
                select(PricingBackfillJobRecord).where(
                    PricingBackfillJobRecord.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing.id
            record = PricingBackfillJobRecord(
                instrument_id=instrument_id,
                range_start=start,
                range_end=end,
                priority=max(1, min(priority, 1000)),
                status="pending",
                idempotency_key=idempotency_key,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _claim_job(eligible_instrument_ids: tuple[str, ...]) -> dict[str, Any] | None:
        if not eligible_instrument_ids:
            return None
        db = SessionLocal()
        try:
            now = utc_now()
            abandoned_before = now - timedelta(minutes=10)
            record = db.scalar(
                select(PricingBackfillJobRecord)
                .where(
                    PricingBackfillJobRecord.instrument_id.in_(eligible_instrument_ids),
                    or_(
                        and_(
                            PricingBackfillJobRecord.status.in_(("pending", "retrying", "deferred")),
                            or_(
                                PricingBackfillJobRecord.next_attempt_at.is_(None),
                                PricingBackfillJobRecord.next_attempt_at <= now,
                            ),
                        ),
                        and_(
                            PricingBackfillJobRecord.status == "processing",
                            PricingBackfillJobRecord.updated_at < abandoned_before,
                        ),
                    ),
                )
                .order_by(
                    PricingBackfillJobRecord.priority.asc(),
                    PricingBackfillJobRecord.created_at.asc(),
                    PricingBackfillJobRecord.id.asc(),
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            record.status = "processing"
            record.attempt_count += 1
            record.updated_at = now
            payload = {
                "id": record.id,
                "instrument_id": record.instrument_id,
                "range_start": ensure_utc(record.range_start),
                "range_end": ensure_utc(record.range_end),
                "attempt_count": record.attempt_count,
            }
            db.commit()
            return payload
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _retry_job(self, job_id: int, error: str, attempt_count: int) -> None:
        status = "failed" if attempt_count >= self.maximum_attempts else "retrying"
        db = SessionLocal()
        try:
            record = db.scalar(select(PricingBackfillJobRecord).where(PricingBackfillJobRecord.id == job_id).with_for_update())
            if record is not None and record.status == "processing" and (attempt_count is None or record.attempt_count == attempt_count):
                record.status = status
                record.last_error = error[:500]
                record.next_attempt_at = (
                    None if status == "failed" else utc_now() + timedelta(minutes=15)
                )
                record.updated_at = utc_now()
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _finish_job(job_id: int, status: str, note: str | None, attempt_count: int | None = None) -> None:
        db = SessionLocal()
        try:
            record = db.scalar(select(PricingBackfillJobRecord).where(PricingBackfillJobRecord.id == job_id).with_for_update())
            if record is not None and record.status == "processing" and (attempt_count is None or record.attempt_count == attempt_count):
                record.status = status
                record.last_error = note
                record.next_attempt_at = utc_now() + timedelta(minutes=5) if status == "deferred" else None
                record.updated_at = utc_now()
                record.completed_at = utc_now() if status == "completed" else None
                if status == "deferred":
                    record.attempt_count = max(0, record.attempt_count - 1)
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _renew_job(job_id: int, attempt_count: int | None = None) -> bool:
        db = SessionLocal()
        try:
            record = db.scalar(select(PricingBackfillJobRecord).where(
                PricingBackfillJobRecord.id == job_id,
                PricingBackfillJobRecord.status == "processing",
            ).with_for_update())
            if record is None or (attempt_count is not None and record.attempt_count != attempt_count):
                return False
            record.updated_at = utc_now()
            db.commit()
            return True
        finally:
            db.close()

    @staticmethod
    def _database_backlog() -> int | None:
        db = SessionLocal()
        try:
            return int(
                db.scalar(
                    select(func.count()).select_from(PricingBackfillJobRecord).where(
                        PricingBackfillJobRecord.status.in_(("pending", "retrying", "processing", "deferred"))
                    )
                )
                or 0
            )
        except Exception:
            return None
        finally:
            db.close()


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


backfill_queue = PricingBackfillQueue()
