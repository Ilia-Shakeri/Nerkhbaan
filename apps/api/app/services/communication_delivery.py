from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update

from ..admin.communication_storage import (
    decrypt_value, encryption_ready, lock_setting, normalize_phone, read_policy, read_provider, read_secret, setting_key,
)
from ..admin.models import CommunicationEvent, CommunicationRecipient
from ..db import SessionLocal
from ..models import Alert, AlertDeliveryJob, AlertTriggerEvent, NotificationPreference, User
from .communication_transport import TransportResult, send_transport
from .alert_delivery_state import finalize_trigger_event, lock_trigger_event

PAID_CHANNELS = frozenset({"sms", "voip"})
_RESERVED = ("sending", "accepted", "unknown", "delivered")


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _clock(value):
    try:
        return _utc(datetime.fromisoformat(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _phone(preferences, channel):
    if not (preferences and preferences.sms_verified and preferences.sms_phone):
        return None
    if not preferences.sms_enabled:
        return None
    try:
        return normalize_phone(preferences.sms_phone)
    except Exception:
        return None


def destination_reference(owner: int, channel: str, phone: str) -> str:
    return f"user:{owner}:{channel}:" + hashlib.sha256(phone.encode()).hexdigest()[:24]


def queued_channels(db, alert, preferences) -> list[tuple[str, str]]:
    channels = []
    for channel, flag in (("sms", "notify_sms"), ("voip", "notify_voip")):
        phone = _phone(preferences, channel)
        if not getattr(alert, flag, False) or not phone:
            continue
        provider = read_provider(db, channel)
        if not provider.get("ready") or not encryption_ready():
            continue
        if channel == "voip":
            policy = read_policy(db)
            if not policy.get("enabled") or (policy.get("critical_only", True) and getattr(alert, "priority", "normal") != "critical"):
                continue
        channels.append((channel, destination_reference(alert.user_id, channel, phone)))
    return channels


def quiet_now(policy: dict, now: datetime, *, critical: bool) -> bool:
    hours = policy.get("quiet_hours", {})
    if not hours.get("enabled") or (critical and hours.get("critical_bypass") is True):
        return False
    local = _utc(now).astimezone(ZoneInfo(hours.get("timezone", "Asia/Tehran")))
    start = datetime.strptime(hours["start"], "%H:%M").time()
    end = datetime.strptime(hours["end"], "%H:%M").time()
    current = local.time().replace(tzinfo=None)
    return start == end or (start <= current < end if start < end else current >= start or current < end)


def _policy_reason(db, owner: int, policy: dict, now: datetime, *, critical: bool,
                   current_job=None, current_event=None) -> str | None:
    if policy.get("enabled") is not True:
        return "call_policy_disabled"
    for key, minimum, maximum in (("max_attempts", 1, 1), ("persist_seconds", 0, 3600),
                                  ("cooldown_seconds", 30, 86400), ("max_calls_per_day", 1, 100)):
        value = policy.get(key)
        if type(value) is not int or not minimum <= value <= maximum:
            return "call_policy_invalid"
    try:
        if quiet_now(policy, now, critical=critical):
            return "quiet_hours"
        local = now.astimezone(ZoneInfo(policy.get("quiet_hours", {}).get("timezone", "Asia/Tehran")))
    except (ValueError, TypeError, KeyError, AttributeError):
        return "call_policy_invalid"
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    cutoff = min(start, now - timedelta(seconds=policy["cooldown_seconds"]))
    jobs = db.scalars(select(AlertDeliveryJob).join(Alert, Alert.id == AlertDeliveryJob.alert_id).where(
        Alert.user_id == owner, AlertDeliveryJob.channel == "voip", AlertDeliveryJob.status.in_(_RESERVED),
        AlertDeliveryJob.updated_at >= cutoff - timedelta(days=1))).all()
    events = db.scalars(select(CommunicationEvent).where(
        CommunicationEvent.owner_user_id == owner, CommunicationEvent.channel == "voip",
        CommunicationEvent.status.in_(_RESERVED), CommunicationEvent.dry_run.is_(False),
        CommunicationEvent.updated_at >= cutoff - timedelta(days=1))).all()
    times = []
    for item in [*jobs, *events]:
        if (isinstance(item, AlertDeliveryJob) and item.id == current_job) or (
                isinstance(item, CommunicationEvent) and item.id == current_event):
            continue
        summary = item.provider_response_summary or {}
        times.append(_clock(summary.get("send_started_at")) or _utc(item.updated_at))
    if sum(stamp >= start for stamp in times) >= policy["max_calls_per_day"]:
        return "daily_call_cap"
    if times and (now - max(times)).total_seconds() < policy["cooldown_seconds"]:
        return "call_cooldown"
    return None


def _summary(result: TransportResult, previous: dict) -> dict:
    return {**previous, **result.summary}


def _close_alert(db, job, status: str, code: str):
    event = lock_trigger_event(db, job.trigger_event_id)
    job.status, job.last_error, job.updated_at = status, code, datetime.now(UTC)
    job.next_retry_at = None
    job.provider_response_summary = {**(job.provider_response_summary or {}), "status": status,
                                     "error_code": code, "delivered": False, "answered": False}
    finalize_trigger_event(db, event)
    db.commit()
    return {"skipped": True, "channel": job.channel, "status": status, "error_code": code}


async def read_fresh_prices() -> dict:
    from ..pricing.compatibility import LegacyPricingAdapter, legacy_pricing_adapter
    from ..pricing.instruments import get_instrument
    from ..pricing.service import instrument_pricing_service
    prices = await legacy_pricing_adapter.get_prices()
    snapshots = await instrument_pricing_service.get_all_canonical()
    assets = list(prices.get("assets", []))
    for instrument_id, quote in snapshots.items():
        currency = get_instrument(instrument_id).quote_currency.value.lower()
        assets.append({"asset": instrument_id, f"price_{currency}": float(quote.price),
                       f"{currency}_status": quote.effective_status().value,
                       **LegacyPricingAdapter._quote_policy_fields(currency, quote)})
    return {**prices, "assets": assets}


async def dispatch_alert_job(engine, job_id: int, expected_attempt: int | None = None) -> dict:
    # Price reads fetch canonical cache/database state, not a provider refresh.
    try:
        fresh = await asyncio.wait_for(read_fresh_prices(), timeout=10)
    except Exception:
        fresh = None
    db = SessionLocal()
    try:
        channel = db.scalar(select(AlertDeliveryJob.channel).where(AlertDeliveryJob.id == job_id))
        if channel not in PAID_CHANNELS:
            return {"skipped": True, "channel": channel or "unknown"}
        lock_setting(db, setting_key(channel))
        if channel == "voip":
            lock_setting(db, "communications.call_policy")
        job = db.scalar(select(AlertDeliveryJob).where(AlertDeliveryJob.id == job_id).with_for_update())
        if not job or job.status != "processing" or (expected_attempt is not None and job.attempt_count != expected_attempt):
            return {"skipped": True, "channel": job.channel if job else "unknown"}
        alert = db.get(Alert, job.alert_id)
        owner = db.scalar(select(User).where(User.id == alert.user_id).with_for_update()) if alert else None
        event = db.get(AlertTriggerEvent, job.trigger_event_id)
        if not alert or not event or not owner or not owner.is_active:
            return _close_alert(db, job, "cancelled", "owner_or_alert_unavailable")
        flag = "notify_sms" if job.channel == "sms" else "notify_voip"
        if not getattr(alert, flag, False) or (alert.mode == "recurring" and not alert.is_active):
            return _close_alert(db, job, "cancelled", "channel_revoked")
        preferences = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == owner.id).with_for_update())
        phone = _phone(preferences, job.channel)
        if not phone or destination_reference(owner.id, job.channel, phone) != job.destination_reference:
            return _close_alert(db, job, "cancelled", "recipient_revoked_or_changed")
        provider = read_provider(db, job.channel)
        if not provider.get("ready") or not encryption_ready():
            return _close_alert(db, job, "cancelled", "provider_disabled")
        from .alert_engine import source_rights_snapshot_allowed
        original = event.condition_snapshot or {}
        context = original.get("delivery_alert") or {}
        current = vars(engine._delivery_alert(alert))
        condition_keys = ("asset_id", "target_price", "condition", "currency", "alert_type", "formula", "price_source_mode", "priority")
        if any(context.get(key, "normal" if key == "priority" else None) != current.get(key) for key in condition_keys):
            return _close_alert(db, job, "cancelled", "alert_condition_changed")
        if fresh:
            fresh = {**fresh, "assets": engine._relevant_assets(alert, fresh), "delivery_alert": current}
        if not fresh or not source_rights_snapshot_allowed(original) or not source_rights_snapshot_allowed(fresh):
            return _close_alert(db, job, "cancelled", "price_or_source_unavailable")
        if not engine._should_trigger_model(alert, fresh):
            return _close_alert(db, job, "cancelled", "condition_cleared_or_price_stale")
        now = datetime.now(UTC)
        previous = dict(job.provider_response_summary or {})
        if job.channel == "voip":
            policy = read_policy(db)
            critical = getattr(alert, "priority", "normal") == "critical"
            if policy.get("critical_only", True) and not critical:
                return _close_alert(db, job, "cancelled", "critical_alert_required")
            reason = _policy_reason(db, owner.id, policy, now, critical=critical, current_job=job.id)
            if reason:
                return _close_alert(db, job, "cancelled", reason)
            if previous.get("paid_attempt_count", 0) >= policy["max_attempts"]:
                return _close_alert(db, job, "cancelled", "call_attempt_cap")
            observed = _clock(previous.get("condition_last_seen"))
            since = _clock(previous.get("condition_since"))
            if not observed or not since or (now - observed).total_seconds() > 15 or since > now:
                since = now
            previous.update(condition_since=since.isoformat(), condition_last_seen=now.isoformat())
            remaining = policy["persist_seconds"] - (now - since).total_seconds()
            if remaining > 0:
                job.status, job.updated_at = "pending", now
                job.next_retry_at = now + timedelta(seconds=min(5, remaining))
                job.provider_response_summary = previous
                db.commit()
                return {"skipped": True, "channel": job.channel, "status": "persisting"}
        secret = read_secret(db, job.channel)
        title, body = engine._alert_summary(engine._delivery_alert(alert), fresh)
        previous.update(send_started_at=now.isoformat(), paid_attempt_count=previous.get("paid_attempt_count", 0) + 1)
        job.provider_response_summary, job.status, job.updated_at = previous, "sending", now
        channel, key = job.channel, job.idempotency_key
        attempt = job.attempt_count
        db.commit()
    finally:
        db.close()
    try:
        result = await asyncio.to_thread(send_transport, channel, provider, secret,
                                        phone=phone, message=f"{title}\n{body}"[:1000], delivery_key=key)
    except Exception:
        result = TransportResult("unknown", error_code="provider_result_unknown", provider_id=provider["provider_id"])
    # The standard worker owns finalization; a crash leaves 'sending' which expires to unknown.
    return {**_summary(result, previous), "channel": channel, "attempt": attempt}


def _claim_manual(limit: int) -> list[tuple[int, int]]:
    db = SessionLocal()
    now = datetime.now(UTC)
    try:
        db.execute(update(CommunicationEvent).where(
            CommunicationEvent.status == "sending", CommunicationEvent.updated_at < now - timedelta(minutes=5)
        ).values(status="unknown", error_code="worker_completion_unknown", updated_at=now))
        db.execute(update(CommunicationEvent).where(
            CommunicationEvent.status == "processing", CommunicationEvent.updated_at < now - timedelta(minutes=5)
        ).values(status="queued", updated_at=now))
        rows = db.scalars(select(CommunicationEvent).where(
            CommunicationEvent.status == "queued", or_(CommunicationEvent.next_retry_at.is_(None), CommunicationEvent.next_retry_at <= now)
        ).order_by(CommunicationEvent.created_at).limit(limit).with_for_update(skip_locked=True)).all()
        for row in rows:
            row.status, row.updated_at = "processing", now
            row.attempt_count += 1
        db.commit()
        return [(row.id, row.attempt_count) for row in rows]
    finally:
        db.close()


async def dispatch_manual_events(limit: int = 10) -> None:
    for event_id, attempt in await asyncio.to_thread(_claim_manual, limit):
        await dispatch_manual_event(event_id, attempt)


async def dispatch_manual_event(event_id: int, expected_attempt: int | None = None) -> dict:
    db = SessionLocal()
    try:
        channel = db.scalar(select(CommunicationEvent.channel).where(CommunicationEvent.id == event_id))
        if channel not in PAID_CHANNELS:
            return {"skipped": True}
        lock_setting(db, setting_key(channel))
        if channel == "voip":
            lock_setting(db, "communications.call_policy")
        event = db.scalar(select(CommunicationEvent).where(CommunicationEvent.id == event_id).with_for_update())
        if not event or event.status not in {"queued", "processing"} or (
                expected_attempt is not None and event.attempt_count != expected_attempt):
            return {"skipped": True}
        if event.status == "queued":
            event.attempt_count += 1
        now = datetime.now(UTC)
        owner = db.scalar(select(User).where(User.id == event.owner_user_id).with_for_update())
        recipient = db.scalar(select(CommunicationRecipient).where(CommunicationRecipient.id == event.recipient_id).with_for_update()) if event.recipient_id else None
        reason = None
        if not owner or not owner.is_active or not recipient or recipient.owner_user_id != event.owner_user_id or not recipient.consented:
            reason = "recipient_or_consent_unavailable"
        provider = read_provider(db, event.channel)
        if not reason and (not provider.get("ready") or not encryption_ready()):
            reason = "provider_disabled"
        if not reason and event.channel == "voip":
            # Operator tests have no market condition; quiet hours and owner caps still apply.
            reason = _policy_reason(db, event.owner_user_id, read_policy(db), now, critical=False, current_event=event.id)
        if event.dry_run:
            event.status, event.updated_at, event.error_code = "dry_run", now, reason
            event.provider_response_summary = {**(event.provider_response_summary or {}), "status": "dry_run", "network_called": False,
                                               "eligible": reason is None, "error_code": reason}
            db.commit()
            return event.provider_response_summary
        if reason:
            event.status, event.updated_at, event.error_code = "cancelled", now, reason
            db.commit()
            return {"status": "cancelled", "error_code": reason}
        phone = normalize_phone(decrypt_value(recipient.phone_ciphertext))
        secret = read_secret(db, event.channel)
        key, channel, attempt = event.delivery_key, event.channel, event.attempt_count
        previous = {**(event.provider_response_summary or {}), "send_started_at": now.isoformat()}
        event.status, event.updated_at, event.provider_response_summary = "sending", now, previous
        db.commit()
    except Exception:
        db.rollback()
        failed = db.scalar(select(CommunicationEvent).where(CommunicationEvent.id == event_id).with_for_update())
        if failed and failed.status in {"queued", "processing"} and (
                expected_attempt is None or failed.attempt_count == expected_attempt):
            failed.status, failed.error_code, failed.updated_at = "failed", "delivery_preflight_failed", datetime.now(UTC)
            db.commit()
        return {"status": "failed", "error_code": "delivery_preflight_failed"}
    finally:
        db.close()
    try:
        result = await asyncio.to_thread(send_transport, channel, provider, secret, phone=phone,
                                        message="Nerkhbaan: owned communications delivery test.", delivery_key=key)
    except Exception:
        result = TransportResult("unknown", error_code="provider_result_unknown", provider_id=provider["provider_id"])
    db = SessionLocal()
    try:
        event = db.scalar(select(CommunicationEvent).where(CommunicationEvent.id == event_id).with_for_update())
        if event and event.status == "sending" and event.attempt_count == attempt:
            event.status, event.updated_at = result.status, datetime.now(UTC)
            event.provider_reference, event.error_code = result.provider_reference, result.error_code
            event.provider_response_summary = _summary(result, previous)
            db.commit()
        return result.summary
    finally:
        db.close()
