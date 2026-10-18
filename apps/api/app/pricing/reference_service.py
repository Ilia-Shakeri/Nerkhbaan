"""Explicit reference valuations outside native quote and alert pipelines."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

import httpx

from ..config import settings
from . import rights
from .budgets import RedisRequestBudget
from .cache import PricingRedisStore, pricing_redis
from .history import TIMEFRAMES
from .models import RequestPurpose, utc_now
from .parsers.base import ParserError
from .providers import ProviderQuoteCollector
from .reference_rates import (
    HISTORY_PROVIDER_ID,
    REFERENCE_IDS,
    SNAPSHOT_PROVIDER_ID,
    build_reference_history,
    build_reference_snapshot,
    reference_definitions,
    validate_reference_record,
)
from .reference_repository import reference_allowed
from .registry import PROVIDERS, ProviderDefinition
from .source_snapshots import SharedSourceSnapshots, SourceSnapshotUnavailable


class ReferenceFetchUnavailable(RuntimeError):
    def __init__(self, code: str, *, http_status: int | None = None):
        super().__init__(code)
        self.code, self.http_status = code, http_status


class ReferenceRightsUnavailable(RuntimeError):
    pass


def _aware(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Reference timestamps need explicit timezones")
    return parsed.astimezone(UTC)


def _transports() -> tuple[ProviderDefinition, ProviderDefinition]:
    # These remain transport descriptors for the common parent files. They are
    # never registered as native quotes or assigned a native reference identity.
    common = {"method": "GET", "api_key_setting": None, "api_key_header": None,
              "api_key_query_parameter": None, "requires_https": True}
    return (
        replace(PROVIDERS["nerkhsanj_usd_toman"], provider_id=SNAPSHOT_PROVIDER_ID,
                display_name="Nerkhsanj Reference Snapshot", maximum_payload_bytes=262_144,
                history_url=None, history_only=False, **common),
        replace(PROVIDERS["nerkhsanj_usd_toman_history"], provider_id=HISTORY_PROVIDER_ID,
                display_name="Nerkhsanj Reference Archive", maximum_payload_bytes=8_388_608,
                history_only=True, **common),
    )


class IranianReferenceService:
    def __init__(self, *, store: PricingRedisStore = pricing_redis,
                 budgets: RedisRequestBudget | None = None, repository=None) -> None:
        self.store = store
        self.budgets = budgets if budgets is not None else RedisRequestBudget(store)
        self.source_snapshots = SharedSourceSnapshots(store, self.budgets)
        self.repository = repository

    def _repository(self):
        if self.repository is None:
            from .reference_repository import ReferenceRateRepository
            self.repository = ReferenceRateRepository()
        return self.repository

    @staticmethod
    def _require_revision(revision: str) -> None:
        if rights.revision() != revision:
            raise ReferenceRightsUnavailable("rights_revision_changed")

    @staticmethod
    def _collection_access(provider: ProviderDefinition, revision: str) -> None:
        IranianReferenceService._require_revision(revision)
        kind = "history" if provider.provider_id == HISTORY_PROVIDER_ID else "snapshot"
        if not any(reference_allowed(reference_id, kind) for reference_id in REFERENCE_IDS):
            raise ReferenceFetchUnavailable("reference_output_rights_denied")
        if not all(rights.provider_allowed(provider.provider_id, action) for action in ("collect", "store")):
            raise ReferenceFetchUnavailable("reference_collection_disabled")
        SharedSourceSnapshots._access(provider, provider.url)

    async def _load(self, client: httpx.AsyncClient, provider: ProviderDefinition,
                    revision: str,
                    range_start: datetime, range_end: datetime, fixed_now: datetime | None):
        self._collection_access(provider, revision)

        async def loader():
            self._collection_access(provider, revision)
            async with client.stream("GET", provider.url, headers=dict(provider.static_headers),
                                     follow_redirects=False) as response:
                if response.status_code == 429:
                    await self.budgets.record_rate_limit(
                        provider, source_url=provider.url,
                        retry_after_seconds=ProviderQuoteCollector._parse_retry_after(
                            response.headers.get("retry-after")),
                    )
                    raise ReferenceFetchUnavailable("rate_limited", http_status=429)
                if response.status_code != 200:
                    raise ReferenceFetchUnavailable("http_error", http_status=response.status_code)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json":
                    raise ReferenceFetchUnavailable("response_content_type")
                limit = provider.maximum_payload_bytes
                length = response.headers.get("content-length", "")
                if length.isdigit() and (len(length) > 9 or int(length) > limit):
                    raise ReferenceFetchUnavailable("payload_too_large")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65_536):
                    if len(body) + len(chunk) > limit:
                        raise ReferenceFetchUnavailable("payload_too_large")
                    body.extend(chunk)
                self._collection_access(provider, revision)
                try:
                    def reject_nonfinite(_value):
                        raise ValueError("Nonfinite JSON number")
                    payload = json.loads(body, parse_constant=reject_nonfinite)
                except (ValueError, UnicodeError) as exc:
                    raise ReferenceFetchUnavailable("invalid_json") from exc
                # Validate before publishing a new common-file snapshot. A cache
                # hit is validated again below against its original receipt.
                current = fixed_now or utc_now()
                if provider.provider_id == SNAPSHOT_PROVIDER_ID:
                    build_reference_snapshot(payload, received_at=current, now=current)
                else:
                    build_reference_history(payload, range_start=range_start, range_end=range_end)
                self._collection_access(provider, revision)
                return payload, content_type, response.status_code

        return await self.source_snapshots.get(
            provider, provider.url, loader,
            RequestPurpose.BACKFILL if provider.provider_id == HISTORY_PROVIDER_ID else RequestPurpose.NORMAL,
        )

    @staticmethod
    def _failure(exc: Exception) -> tuple[str, bool]:
        cause = exc.cause if isinstance(exc, SourceSnapshotUnavailable) and exc.cause else exc
        code = getattr(cause, "code", getattr(exc, "code", "reference_source_unavailable"))
        if isinstance(cause, ReferenceRightsUnavailable):
            return str(cause), False
        http_status = getattr(cause, "http_status", None)
        transient = (
            isinstance(cause, (httpx.HTTPError, OSError, TimeoutError))
            or (isinstance(http_status, int) and (http_status in {408, 429} or http_status >= 500))
            or str(code).startswith(("budget_", "minimum_interval"))
            or code in {"provider_cooldown", "provider_budget_disabled", "snapshot_locked",
                        "snapshot_cache_unavailable", "snapshot_lease_lost", "source_clock_unavailable",
                        "reference_collection_disabled", "snapshot_provider_not_supported",
                        "provider_host_not_allowed", "provider_rights_denied"}
        )
        return str(code), transient

    @staticmethod
    def _empty(definition: dict, reason: str) -> dict:
        return {**deepcopy(definition), "price": None, "price_decimal": None,
                "status": "unavailable_reference", "observed_at": None,
                "received_at": None, "age_seconds": None, "inputs": [],
                "unavailable_reason": reason, "persistence_status": "unavailable"}

    @staticmethod
    def _stored_current(value: object, definition: dict, now: datetime) -> dict | None:
        if not isinstance(value, dict) or value.get("instrument_id") != definition["instrument_id"]:
            return None
        try:
            validate_reference_record(value, "snapshot", now=now)
            observed = _aware(value["observed_at"])
            age = max(0.0, (now - observed).total_seconds())
            if age > definition["maximum_reference_age_seconds"]:
                return None
        except (ValueError, TypeError, KeyError, OverflowError):
            return None
        result = {**deepcopy(value), **deepcopy(definition)}
        result.update(age_seconds=age,
                      status="fresh_reference" if age <= definition["freshness_limit_seconds"] else "delayed_reference",
                      unavailable_reason=None, persistence_status="persisted", storage_fallback=True)
        return result

    async def _recover(self, definitions: list[dict], range_start: datetime, range_end: datetime,
                       checked_at: datetime, revision: str, *, snapshots: bool, history: bool) -> tuple[dict, dict]:
        self._require_revision(revision)
        kinds = (("snapshot",) if snapshots else ()) + (("history",) if history else ())
        if not any(reference_allowed(item["instrument_id"], kind) for item in definitions for kind in kinds):
            return {}, {}
        stored = await self._repository().load(range_start=range_start, range_end=range_end)
        self._require_revision(revision)
        current, histories = {}, {}
        if snapshots:
            by_id = {item.get("instrument_id"): item for item in stored.get("snapshots", []) if isinstance(item, dict)}
            for definition in definitions:
                reference_id = definition["instrument_id"]
                if reference_allowed(reference_id, "snapshot"):
                    recovered = self._stored_current(by_id.get(reference_id), definition, checked_at)
                    if recovered is not None:
                        current[reference_id] = recovered
        if history:
            for key, values in stored.get("histories", {}).items():
                if key not in REFERENCE_IDS or not isinstance(values, list) or not reference_allowed(key, "history"):
                    continue
                histories[key] = []
                for value in values:
                    try:
                        validate_reference_record(value, "history", now=checked_at)
                        stamp = _aware(value["timestamp"])
                        if value["instrument_id"] != key or not range_start <= stamp <= range_end:
                            continue
                    except (ValueError, TypeError, KeyError, OverflowError):
                        continue
                    histories[key].append(deepcopy(value))
        return current, histories

    @staticmethod
    def _prune(current: dict, histories: dict) -> tuple[dict, dict]:
        return ({key: value for key, value in current.items() if reference_allowed(key, "snapshot")},
                {key: value for key, value in histories.items() if reference_allowed(key, "history")})

    @staticmethod
    def _merge_history(stored: dict, incoming: dict) -> tuple[dict, set[str]]:
        merged, partial = {}, set()
        for reference_id in REFERENCE_IDS:
            if not reference_allowed(reference_id, "history"):
                continue
            old = {point["source_date"]: point for point in stored.get(reference_id, [])}
            new = {point["source_date"]: point for point in incoming.get(reference_id, [])}
            if old.keys() - new.keys():
                partial.add(reference_id)
            # Only existing published dates join. New valid source data wins
            # for that same date; no missing day is invented or carried forward.
            merged[reference_id] = sorted({**old, **new}.values(), key=lambda point: _aware(point["timestamp"]))
        return merged, partial

    @staticmethod
    def _attributions(current: dict, histories: dict) -> list[dict]:
        result = []
        for provider_id, values in ((SNAPSHOT_PROVIDER_ID, current), (HISTORY_PROVIDER_ID, histories)):
            has_values = (any(item.get("price") is not None for item in values.values())
                          if provider_id == SNAPSHOT_PROVIDER_ID else any(values.values()))
            if has_values:
                for attribution in rights.attribution({"provider_ids": [provider_id], "derived": False}):
                    if attribution not in result:
                        result.append(attribution)
        return result

    @staticmethod
    def _response(definitions: list[dict], current: dict, histories: dict,
                  *, revision: str, checked_at: datetime, timeframe: str,
                  attributions: list[dict], errors: list[dict], fallback_history: bool = False) -> dict:
        references = []
        for definition in definitions:
            instrument_id = definition["instrument_id"]
            item = current.get(instrument_id) or IranianReferenceService._empty(definition, "source_unavailable")
            if item.get("price") is not None:
                aged = IranianReferenceService._stored_current(item, definition, checked_at)
                if aged is None:
                    item = IranianReferenceService._empty(definition, "reference_clock_or_value_unavailable")
                else:
                    aged["persistence_status"] = item.get("persistence_status", "unavailable")
                    if not item.get("storage_fallback"):
                        aged.pop("storage_fallback", None)
                    item = aged
            points = histories.get(instrument_id, [])
            references.append({
                **deepcopy(definition), "status": item["status"], "current": item,
                "history": points,
                "history_status": "partial" if fallback_history or not points else "complete",
                "history_time_info": {"timestamp_precision": "day", "timestamp_role": "day_bucket_start",
                                      "source_timezone": "Asia/Tehran", "source_calendar": "jalali",
                                      "source_observation_time_known": False},
            })
        return {"rights_revision": revision, "checked_at": checked_at.isoformat(),
                "timeframe": timeframe, "attributions": attributions,
                "references": references, "errors": errors}

    async def get(self, timeframe: str = "30d", *, client: httpx.AsyncClient | None = None,
                  now: datetime | None = None) -> dict:
        if timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported reference timeframe")
        fixed_now = _aware(now) if now is not None else None
        range_end = fixed_now or utc_now()
        range_start = range_end - TIMEFRAMES[timeframe].duration
        providers, definitions = _transports(), reference_definitions()
        revision = rights.revision()
        current, histories, errors = {}, {}, []
        fallback_current = fallback_history = False
        owns_client = client is None
        request_client = client
        try:
            self._require_revision(revision)
            if request_client is None:
                request_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(float(settings.pricing_provider_request_timeout_seconds),
                                          connect=float(settings.pricing_provider_connect_timeout_seconds)),
                    follow_redirects=False, trust_env=False,
                )
            fetched = await asyncio.gather(*(
                self._load(request_client, provider, revision, range_start, range_end, fixed_now)
                for provider in providers
            ), return_exceptions=True)
            self._require_revision(revision)
            checked_at = fixed_now or utc_now()
            for index, result in enumerate(fetched):
                stage = "current" if index == 0 else "history"
                if isinstance(result, BaseException):
                    if not isinstance(result, Exception):
                        raise result
                    if isinstance(result, ReferenceRightsUnavailable):
                        raise result
                    if isinstance(result, SourceSnapshotUnavailable) and isinstance(result.cause, ReferenceRightsUnavailable):
                        raise result.cause
                    code, transient = self._failure(result)
                    errors.append({"stage": stage, "code": code})
                    if index == 0:
                        fallback_current = transient
                    else:
                        fallback_history = transient
                    continue
                self._require_revision(revision)
                try:
                    if index == 0:
                        values = build_reference_snapshot(result.payload, received_at=result.fetched_at, now=checked_at)
                        current = {item["instrument_id"]: item for item in values
                                   if reference_allowed(item["instrument_id"], "snapshot")}
                    else:
                        histories = build_reference_history(result.payload, range_start=range_start, range_end=range_end)
                        histories = {key: value for key, value in histories.items() if reference_allowed(key, "history")}
                except (ParserError, ValueError, TypeError, KeyError, OverflowError) as exc:
                    errors.append({"stage": stage, "code": getattr(exc, "code", "reference_invalid_payload")})
                    continue
                self._require_revision(revision)
                try:
                    repository = self._repository()
                    if index == 0:
                        await repository.save_snapshot(list(current.values()), received_at=result.fetched_at)
                        for item in current.values():
                            item["persistence_status"] = "persisted" if item.get("price") is not None else "unavailable"
                    else:
                        await repository.save_history(histories, received_at=result.fetched_at)
                except Exception:
                    errors.append({"stage": "persistence_" + stage, "code": "reference_persistence_unavailable"})
                    if index == 0:
                        for item in current.values():
                            item["persistence_status"] = "unpersisted" if item.get("price") is not None else "unavailable"
                self._require_revision(revision)
            self._require_revision(revision)
            try:
                stored_current, stored_history = await self._recover(
                    definitions, range_start, range_end, checked_at, revision,
                    snapshots=fallback_current, history=True,
                )
                if fallback_current:
                    current.update(stored_current)
                histories, restored_dates = self._merge_history(stored_history, histories)
                fallback_history = fallback_history or bool(restored_dates)
            except ReferenceRightsUnavailable:
                raise
            except Exception:
                errors.append({"stage": "storage", "code": "reference_storage_unavailable"})
                fallback_history = True
            self._require_revision(revision)
            current, histories = self._prune(current, histories)
            attributions = self._attributions(current, histories)
            checked_at = fixed_now or utc_now()
            response = self._response(definitions, current, histories, revision=revision, checked_at=checked_at,
                                      timeframe=timeframe, attributions=attributions, errors=errors,
                                      fallback_history=fallback_history)
            self._require_revision(revision)
            return response
        except ReferenceRightsUnavailable as exc:
            # Re-read only durable rows under the new grant. Stopping collection
            # does not revoke display; removing display/derive/history does.
            revision, checked_at = rights.revision(), fixed_now or utc_now()
            try:
                current, histories = await self._recover(definitions, range_start, range_end, checked_at,
                                                         revision, snapshots=True, history=True)
                self._require_revision(revision)
                current, histories = self._prune(current, histories)
                attributions = self._attributions(current, histories)
                self._require_revision(revision)
            except Exception:
                current, histories, attributions = {}, {}, []
                revision = rights.revision()
            checked_at = fixed_now or utc_now()
            response = self._response(definitions, current, histories, revision=revision, checked_at=checked_at,
                                      timeframe=timeframe, attributions=attributions, fallback_history=True,
                                      errors=[{"stage": "access", "code": str(exc)}])
            if rights.revision() != revision:
                return self._response(definitions, {}, {}, revision=rights.revision(), checked_at=checked_at,
                                      timeframe=timeframe, attributions=[],
                                      errors=[{"stage": "access", "code": "rights_revision_changed"}])
            return response
        finally:
            if owns_client and request_client is not None:
                await request_client.aclose()


iranian_reference_service = IranianReferenceService()
