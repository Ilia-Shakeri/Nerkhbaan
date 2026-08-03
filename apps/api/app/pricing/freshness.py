from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


DEFAULT_FUTURE_CLOCK_SKEW_SECONDS = 30


class FreshnessStatus(StrEnum):
    LIVE = "live"
    STALE = "stale"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    maximum_source_age_seconds: int
    provider_live_ttl_seconds: int
    instrument_operational_ttl_seconds: int
    instrument_stale_after_seconds: int
    instrument_expire_after_seconds: int
    future_clock_skew_seconds: int = DEFAULT_FUTURE_CLOCK_SKEW_SECONDS

    def __post_init__(self) -> None:
        if min(
            self.maximum_source_age_seconds,
            self.provider_live_ttl_seconds,
            self.instrument_operational_ttl_seconds,
            self.instrument_stale_after_seconds,
            self.instrument_expire_after_seconds,
        ) <= 0:
            raise ValueError("Freshness durations must be positive")
        if not (
            self.instrument_operational_ttl_seconds
            <= self.instrument_stale_after_seconds
            <= self.instrument_expire_after_seconds
        ):
            raise ValueError("Instrument freshness windows are invalid")
        if self.future_clock_skew_seconds < 0:
            raise ValueError("Future clock skew allowance cannot be negative")


@dataclass(frozen=True, slots=True)
class FreshnessBoundaries:
    cache_retention_until: datetime
    live_eligible_until: datetime
    stale_display_until: datetime
    expired_after: datetime

    def status_at(self, now: datetime) -> FreshnessStatus:
        current = _ensure_utc(now)
        if current <= self.live_eligible_until:
            return FreshnessStatus.LIVE
        if current <= self.expired_after:
            return FreshnessStatus.STALE
        return FreshnessStatus.EXPIRED

    def is_retained_at(self, now: datetime) -> bool:
        return _ensure_utc(now) <= self.cache_retention_until

    def is_stale_displayable_at(self, now: datetime) -> bool:
        current = _ensure_utc(now)
        return self.live_eligible_until < current <= self.stale_display_until


def live_eligible_until(
    source_timestamp: datetime,
    receive_timestamp: datetime,
    policy: FreshnessPolicy,
) -> datetime:
    anchor, _received = _freshness_anchor(source_timestamp, receive_timestamp, policy)
    live_seconds = min(
        policy.maximum_source_age_seconds,
        policy.provider_live_ttl_seconds,
        policy.instrument_operational_ttl_seconds,
        policy.instrument_expire_after_seconds,
    )
    return anchor + timedelta(seconds=live_seconds)


def stale_display_until(
    source_timestamp: datetime,
    receive_timestamp: datetime,
    policy: FreshnessPolicy,
) -> datetime:
    anchor, _received = _freshness_anchor(source_timestamp, receive_timestamp, policy)
    return anchor + timedelta(seconds=policy.instrument_stale_after_seconds)


def expired_after(
    source_timestamp: datetime,
    receive_timestamp: datetime,
    policy: FreshnessPolicy,
) -> datetime:
    anchor, _received = _freshness_anchor(source_timestamp, receive_timestamp, policy)
    return anchor + timedelta(seconds=policy.instrument_expire_after_seconds)


def cache_retention_until(
    source_timestamp: datetime,
    receive_timestamp: datetime,
    policy: FreshnessPolicy,
) -> datetime:
    _anchor, received = _freshness_anchor(source_timestamp, receive_timestamp, policy)
    logical_expiry = expired_after(source_timestamp, receive_timestamp, policy)
    storage_expiry = received + timedelta(
        seconds=policy.instrument_expire_after_seconds
    )
    return max(logical_expiry, storage_expiry)


def freshness_boundaries(
    source_timestamp: datetime,
    receive_timestamp: datetime,
    policy: FreshnessPolicy,
) -> FreshnessBoundaries:
    return FreshnessBoundaries(
        cache_retention_until=cache_retention_until(
            source_timestamp, receive_timestamp, policy
        ),
        live_eligible_until=live_eligible_until(
            source_timestamp, receive_timestamp, policy
        ),
        stale_display_until=stale_display_until(
            source_timestamp, receive_timestamp, policy
        ),
        expired_after=expired_after(source_timestamp, receive_timestamp, policy),
    )


def _freshness_anchor(
    source_timestamp: datetime,
    receive_timestamp: datetime,
    policy: FreshnessPolicy,
) -> tuple[datetime, datetime]:
    source = _ensure_utc(source_timestamp)
    received = _ensure_utc(receive_timestamp)
    if source > received + timedelta(seconds=policy.future_clock_skew_seconds):
        raise ValueError("Source timestamp exceeds future clock skew allowance")
    return min(source, received), received


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
