from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from ..config import settings
from . import rights
from .cache import PricingRedisStore, pricing_redis
from .freshness import DEFAULT_FUTURE_CLOCK_SKEW_SECONDS
from .models import RequestPurpose, utc_now
from .parsers.base import ParserError
from .parsers.nerkhsanj_markets import parse_source_timestamp
from .registry import ProviderDefinition

_SOURCE_HOST = "nerkh.jahankhahan.shop"
_SOURCE_PATHS = frozenset(f"/data/{name}.json" for name in ("live", "intraday", "rates", "rates-usd"))
_CACHE_SECONDS = 60
_LOCK_MILLISECONDS = 20_000
_FETCH_SECONDS = 15
_PUBLISH = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('set', KEYS[2], ARGV[2], 'PX', ARGV[3])
redis.call('del', KEYS[1])
return 1
"""
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class SourceSnapshotUnavailable(RuntimeError):
    def __init__(self, code: str, *, network_called: bool = False, cause: Exception | None = None):
        super().__init__(code)
        self.code = code
        self.network_called = network_called
        self.cause = cause


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    payload: object
    content_type: str
    http_status: int
    fetched_at: datetime
    network_called: bool


def canonical_source_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != _SOURCE_HOST
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in _SOURCE_PATHS):
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise SourceSnapshotUnavailable("snapshot_endpoint_not_allowed") from exc
    return f"https://{_SOURCE_HOST}{parsed.path}"


def source_url_digest(url: str) -> str:
    return hashlib.sha256(canonical_source_url(url).encode("utf-8")).hexdigest()


class SharedSourceSnapshots:
    def __init__(self, store: PricingRedisStore = pricing_redis, budgets=None) -> None:
        self.store = store
        self.budgets = budgets

    @staticmethod
    def cache_key(url: str) -> str:
        return f"pricing:source-snapshot:nerkhsanj:{source_url_digest(url)}"

    @staticmethod
    def _access(provider: ProviderDefinition, url: str) -> str:
        canonical = canonical_source_url(url)
        if (provider.source_family != "nerkhsanj" or provider.method != "GET" or not provider.enabled
                or provider.api_key_setting is not None
                or any(name.lower() in {"authorization", "cookie", "x-api-key"}
                       for name, _value in provider.static_headers)):
            raise SourceSnapshotUnavailable("snapshot_provider_not_supported")
        hosts = {host.strip().lower() for host in settings.pricing_provider_allowed_hosts.split(",")}
        if _SOURCE_HOST not in hosts:
            raise SourceSnapshotUnavailable("provider_host_not_allowed")
        actions = ("collect", "store") if canonical.endswith("/live.json") else ("collect", "store", "history")
        if (not rights.endpoint_allowed(provider.provider_id, canonical)
                or not all(rights.provider_allowed(provider.provider_id, action) for action in actions)):
            raise SourceSnapshotUnavailable("provider_rights_denied")
        return canonical

    @staticmethod
    def _maximum_bytes(provider: ProviderDefinition, url: str) -> int:
        maximum = 8_388_608 if url.endswith(("/rates.json", "/rates-usd.json")) else 262_144
        return min(provider.maximum_payload_bytes, maximum)

    @staticmethod
    def _source_clock(payload: object, url: str, fetched_at: datetime) -> None:
        if not isinstance(payload, dict):
            raise SourceSnapshotUnavailable("snapshot_invalid_payload")
        if url.endswith(("/live.json", "/intraday.json")):
            if url.endswith("/intraday.json") and payload.get("time") in (None, ""):
                # Each archive point keeps its own dated clock. A closed-market
                # publication need not have a current quote timestamp.
                return
            try:
                published = parse_source_timestamp(payload)
            except ParserError as exc:
                raise SourceSnapshotUnavailable(exc.code) from exc
            if published > fetched_at + timedelta(seconds=DEFAULT_FUTURE_CLOCK_SKEW_SECONDS):
                raise SourceSnapshotUnavailable("future_timestamp")

    def _decode(self, raw: object, provider: ProviderDefinition, url: str) -> SourceSnapshot | None:
        maximum = self._maximum_bytes(provider, url)
        if not isinstance(raw, (str, bytes)) or len(raw) > maximum + 4096:
            raise SourceSnapshotUnavailable("snapshot_invalid_cache")
        try:
            encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
            if len(encoded) > maximum + 4096:
                raise ValueError
            envelope = json.loads(encoded)
            if (not isinstance(envelope, dict) or type(envelope.get("schema_version")) is not int
                    or envelope["schema_version"] != 1 or envelope.get("source_url") != url
                    or envelope.get("content_type") != "application/json"
                    or type(envelope.get("http_status")) is not int or envelope["http_status"] != 200
                    or not isinstance(envelope.get("fetched_at"), str)):
                raise ValueError
            fetched_at = datetime.fromisoformat(envelope["fetched_at"])
            if fetched_at.tzinfo is None:
                raise ValueError
            fetched_at = fetched_at.astimezone(UTC)
            age = (utc_now() - fetched_at).total_seconds()
            if age < 0:
                raise ValueError
            if age >= _CACHE_SECONDS:
                return None
            payload = envelope["payload"]
            payload_bytes = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(payload_bytes) > maximum:
                raise ValueError
            self._source_clock(payload, url, fetched_at)
            return SourceSnapshot(payload, "application/json", 200, fetched_at, False)
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeError, RecursionError) as exc:
            raise SourceSnapshotUnavailable("snapshot_invalid_cache") from exc

    async def get(
        self,
        provider: ProviderDefinition,
        url: str,
        loader: Callable[[], Awaitable[tuple[object, str | None, int]]],
        purpose: RequestPurpose = RequestPurpose.NORMAL,
    ) -> SourceSnapshot:
        canonical = self._access(provider, url)
        cache_key = self.cache_key(canonical)
        lock_key = cache_key + ":lock"
        owner = uuid.uuid4().hex
        deadline = asyncio.get_running_loop().time() + _FETCH_SECONDS + 1
        while True:
            self._access(provider, canonical)
            try:
                redis = self.store.client()
                raw = await redis.get(cache_key)
                if raw is not None:
                    snapshot = self._decode(raw, provider, canonical)
                    if snapshot is not None:
                        ttl = int(await redis.pttl(cache_key))
                        if ttl > _CACHE_SECONDS * 1000 or ttl == -1:
                            raise SourceSnapshotUnavailable("snapshot_invalid_cache_ttl")
                        if ttl > 0:
                            self._access(provider, canonical)
                            return snapshot
                acquired = await redis.set(lock_key, owner, nx=True, px=_LOCK_MILLISECONDS)
            except SourceSnapshotUnavailable:
                raise
            except Exception as exc:
                raise SourceSnapshotUnavailable("snapshot_cache_unavailable") from exc
            if acquired:
                return await self._load(provider, canonical, loader, purpose, redis, cache_key, lock_key, owner)
            if asyncio.get_running_loop().time() >= deadline:
                raise SourceSnapshotUnavailable("snapshot_locked")
            await asyncio.sleep(0.1)

    async def _load(self, provider, url, loader, purpose, redis, cache_key, lock_key, owner) -> SourceSnapshot:
        published = False
        network_called = False
        try:
            # Another owner may have published between this reader's GET and SET NX.
            raw = await redis.get(cache_key)
            if raw is not None:
                snapshot = self._decode(raw, provider, url)
                if snapshot is not None:
                    ttl = int(await redis.pttl(cache_key))
                    if ttl > _CACHE_SECONDS * 1000 or ttl == -1:
                        raise SourceSnapshotUnavailable("snapshot_invalid_cache_ttl")
                    if ttl > 0:
                        self._access(provider, url)
                        return snapshot
            self._access(provider, url)
            budgets = self.budgets
            if budgets is None:
                from .budgets import pricing_budget
                budgets = pricing_budget
            decision = await budgets.consume(provider, purpose, source_url=url)
            if not decision.allowed:
                raise SourceSnapshotUnavailable(decision.reason)
            self._access(provider, url)
            network_called = True
            try:
                async with asyncio.timeout(_FETCH_SECONDS):
                    payload, content_type, status = await loader()
            except Exception as exc:
                raise SourceSnapshotUnavailable("snapshot_fetch_failed", network_called=True, cause=exc) from exc
            fetched_at = utc_now()
            self._access(provider, url)
            if content_type != "application/json" or status != 200:
                raise SourceSnapshotUnavailable("snapshot_invalid_response", network_called=True)
            self._source_clock(payload, url, fetched_at)
            maximum = self._maximum_bytes(provider, url)
            payload_bytes = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(payload_bytes) > maximum:
                raise SourceSnapshotUnavailable("payload_too_large", network_called=True)
            envelope = json.dumps({
                "schema_version": 1, "source_url": url, "content_type": content_type,
                "http_status": status, "fetched_at": fetched_at.isoformat(), "payload": payload,
            }, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            if len(envelope) > maximum + 4096:
                raise SourceSnapshotUnavailable("payload_too_large", network_called=True)
            self._access(provider, url)
            published = bool(await redis.eval(_PUBLISH, 2, lock_key, cache_key, owner, envelope, 60_000))
            if not published:
                raise SourceSnapshotUnavailable("snapshot_lease_lost", network_called=True)
            return SourceSnapshot(payload, content_type, status, fetched_at, True)
        except SourceSnapshotUnavailable as exc:
            exc.network_called = exc.network_called or network_called
            raise
        except Exception as exc:
            raise SourceSnapshotUnavailable("snapshot_cache_unavailable", network_called=network_called) from exc
        finally:
            if not published:
                with contextlib.suppress(Exception):
                    await redis.eval(_RELEASE, 1, lock_key, owner)
