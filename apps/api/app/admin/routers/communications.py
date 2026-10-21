from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import AlertDeliveryJob, User
from ...services.communication_transport import TransportConfigurationError, validate_provider_config
from ..audit import add_audit_event
from ..communication_schemas import CallPolicyUpdate, ChannelUpdate, TestEventCreate, TestRecipientCreate
from ..communication_storage import (PROVIDER_CATALOG, check_version, credentials_valid, encrypt_value,
    encryption_ready, lock_setting, mask_phone, normalize_phone, read_policy, read_provider,
    read_secret, save_setting, secret_key, setting_key)
from ..deps import AdminPrincipal, require_confirmation, require_permission, require_recent_reauthentication
from ..models import AdminSecret, CommunicationEvent, CommunicationRecipient
from ..permissions import AdminPermissionKey

class CommunicationsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def protected(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Missing-field errors can otherwise include the entire credential-bearing body.
                raise HTTPException(422, "Communications request is invalid") from None

        return protected


router = APIRouter(prefix="/communications", tags=["admin-communications"], route_class=CommunicationsRoute)


def _recipient(row: CommunicationRecipient) -> dict:
    return {"id": row.id, "label": row.label, "phone_masked": row.phone_masked,
            "consented": row.consented, "created_at": row.created_at}


def _owned_recipient(db: Session, identifier: int, owner: int) -> CommunicationRecipient:
    row = db.scalar(select(CommunicationRecipient).where(CommunicationRecipient.id == identifier,
        CommunicationRecipient.owner_user_id == owner).with_for_update())
    if row is None:
        raise HTTPException(404, "Test recipient not found")
    return row


@router.get("")
def snapshot(principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_READ)), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(CommunicationRecipient).where(CommunicationRecipient.owner_user_id == principal.user.id).order_by(CommunicationRecipient.id)).all()
    return {"version": 1, "encryption_ready": encryption_ready(),
            "channels": {channel: read_provider(db, channel) for channel in ("sms", "voip")},
            "call_policy": read_policy(db), "provider_catalog": deepcopy(PROVIDER_CATALOG),
            "test_recipients": [_recipient(row) for row in rows]}


@router.put("/channels/{channel}")
def update_channel(channel: str, payload: ChannelUpdate, request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    key = setting_key(channel)
    row = lock_setting(db, key)
    check_version(row, payload.expected_version)
    before = read_provider(db, channel)
    try:
        config = validate_provider_config(channel, payload.provider_id, payload.config)
    except TransportConfigurationError as exc:
        raise HTTPException(422, "Provider configuration is invalid") from exc
    values = payload.secret_value
    action = payload.secret_action
    # Empty form controls preserve an existing credential.
    if action == "replace" and (values is None or values == {} or
        isinstance(values, dict) and all(isinstance(value, str) and not value.strip() for value in values.values())):
        action = "keep"
    only_disable = (not payload.enabled and payload.provider_id == before["provider_id"] and
                    config == before["config"] and action == "keep")
    if not only_disable:
        require_recent_reauthentication(principal)
    if payload.enabled and not before["enabled"]:
        require_confirmation(payload.confirmation, "ENABLE " + channel.upper())
    secret = db.scalar(select(AdminSecret).where(AdminSecret.key == secret_key(channel)).with_for_update())
    if action == "clear":
        require_confirmation(payload.confirmation, "CLEAR " + channel.upper() + " SECRET")
        if payload.enabled:
            raise HTTPException(422, "Disable the channel before clearing its secret")
        if secret is not None:
            db.delete(secret)
        values = {}
    elif action == "replace":
        if not isinstance(values, dict) or not credentials_valid(payload.provider_id, values):
            raise HTTPException(422, "Provider credentials are invalid")
        ciphertext = encrypt_value(json.dumps(values, separators=(",", ":")))
        if secret is None:
            secret = AdminSecret(key=secret_key(channel), ciphertext=ciphertext, updated_by=principal.user.id)
            db.add(secret)
        else:
            secret.ciphertext = ciphertext
            secret.updated_by = principal.user.id
    else:
        values = read_secret(db, channel) if secret is not None and payload.enabled else {}
        if before["provider_id"] != payload.provider_id and secret is not None:
            raise HTTPException(422, "Replace or clear credentials when changing provider")
    if payload.enabled and (not encryption_ready() or not credentials_valid(payload.provider_id, values)):
        raise HTTPException(422, "Provider credentials are required before enabling")
    save_setting(db, key, {"provider_id": payload.provider_id, "enabled": payload.enabled, "config": config}, principal.user.id, row)
    if not payload.enabled:
        for event in db.scalars(select(CommunicationEvent).where(CommunicationEvent.channel == channel,
            CommunicationEvent.status.in_(("queued", "processing"))).with_for_update()).all():
            event.status, event.error_code = "cancelled", "provider_disabled"
        for job in db.scalars(select(AlertDeliveryJob).where(AlertDeliveryJob.channel == channel,
            AlertDeliveryJob.status.in_(("pending", "processing", "retrying"))).with_for_update()).all():
            job.status, job.last_error = "cancelled", "provider_disabled"
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.communications.channel_updated",
        resource_type="communications", resource_id=channel,
        before={"enabled": before["enabled"], "provider_id": before["provider_id"], "version": before["version"]},
        after={"enabled": payload.enabled, "provider_id": payload.provider_id, "credential_action": action})
    db.commit()
    return read_provider(db, channel)


@router.put("/call-policy")
def update_call_policy(payload: CallPolicyUpdate, request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    lock_setting(db, setting_key("voip"))
    row = lock_setting(db, "communications.call_policy")
    check_version(row, payload.expected_version)
    require_recent_reauthentication(principal)
    if payload.enabled:
        require_confirmation(payload.confirmation, "ENABLE VOIP POLICY")
        if not read_provider(db, "voip")["ready"]:
            raise HTTPException(422, "A ready VoIP provider is required")
    value = payload.model_dump(exclude={"expected_version", "confirmation"})
    save_setting(db, "communications.call_policy", value, principal.user.id, row)
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.communications.policy_updated",
        resource_type="communications", resource_id="call-policy", after=value)
    db.commit()
    return read_policy(db)


@router.get("/test-recipients")
def list_recipients(principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_READ)), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(CommunicationRecipient).where(CommunicationRecipient.owner_user_id == principal.user.id).order_by(CommunicationRecipient.id)).all()
    return {"items": [_recipient(row) for row in rows]}


@router.post("/test-recipients", status_code=201)
def create_recipient(payload: TestRecipientCreate, request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    require_recent_reauthentication(principal)
    if not payload.consent_confirmed:
        raise HTTPException(422, "Recipient consent is required")
    if not isinstance(payload.phone, str):
        raise HTTPException(422, "A valid Iranian mobile number is required")
    phone = normalize_phone(payload.phone)
    label = payload.label.strip()
    if not label or any(ord(char) < 32 for char in label):
        raise HTTPException(422, "Recipient label is invalid")
    # A global row lock also serializes an initially empty recipient list.
    lock_setting(db, "communications.recipient-owner." + str(principal.user.id))
    count = db.scalar(select(func.count()).select_from(CommunicationRecipient).where(CommunicationRecipient.owner_user_id == principal.user.id))
    if int(count or 0) >= 10:
        raise HTTPException(409, "At most ten test recipients are allowed")
    row = CommunicationRecipient(owner_user_id=principal.user.id, label=label,
        phone_ciphertext=encrypt_value(phone), phone_masked=mask_phone(phone), consented=True)
    db.add(row)
    db.flush()
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.communications.recipient_created",
        resource_type="communication-recipient", resource_id=row.id, after={"consented": True})
    db.commit()
    return _recipient(row)


@router.delete("/test-recipients/{recipient_id}")
def delete_recipient(recipient_id: int, request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.SETTINGS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    for channel in ("sms", "voip"):
        lock_setting(db, setting_key(channel))
    row = _owned_recipient(db, recipient_id, principal.user.id)
    row.consented = False
    pending = db.scalars(select(CommunicationEvent).where(CommunicationEvent.recipient_id == row.id,
        CommunicationEvent.status.in_(("queued", "processing"))).with_for_update()).all()
    for event in pending:
        event.status = "cancelled"
        event.error_code = "recipient_removed"
    # Keep a masked receipt while erasing the destination.
    row.phone_ciphertext = ""
    db.delete(row)
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.communications.recipient_deleted",
        resource_type="communication-recipient", resource_id=recipient_id)
    db.commit()
    return {"deleted": True}


@router.post("/test-events", status_code=201)
def create_test_event(payload: TestEventCreate, request: Request,
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ALERTS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    lock_setting(db, setting_key(payload.channel))
    identifier = str(payload.client_request_id)
    lock_setting(db, "communications.event-owner." + str(principal.user.id))
    existing = db.scalar(select(CommunicationEvent).where(CommunicationEvent.owner_user_id == principal.user.id,
        CommunicationEvent.client_request_id == identifier))
    if existing is not None:
        if existing.channel != payload.channel or existing.recipient_id != payload.recipient_id or existing.dry_run != (payload.mode == "dry_run"):
            raise HTTPException(409, "Request identifier already used for another test")
        return {"event_id": existing.id, "status": existing.status, "dry_run": existing.dry_run,
                "blocked_reasons": (existing.provider_response_summary or {}).get("blocked_reasons", [])}
    # Both paid channels share an owner and may share a recipient. Match the
    # worker's owner-before-recipient order before an insert takes its FK lock.
    owner = db.scalar(select(User).where(User.id == principal.user.id).with_for_update()
        .execution_options(populate_existing=True))
    if owner is None or not owner.is_active:
        raise HTTPException(401, "Account is not active")
    recipient = _owned_recipient(db, payload.recipient_id, principal.user.id)
    if not recipient.consented:
        raise HTTPException(422, "Recipient consent is required")
    dry_run = payload.mode == "dry_run"
    blocked_reasons = []
    if dry_run:
        if not read_provider(db, payload.channel)["ready"]:
            blocked_reasons.append("provider_not_ready")
        if payload.channel == "voip" and not read_policy(db)["enabled"]:
            blocked_reasons.append("call_policy_disabled")
    if not dry_run:
        require_recent_reauthentication(principal)
        require_confirmation(payload.confirmation, "SEND TEST")
        if not read_provider(db, payload.channel)["ready"]:
            raise HTTPException(422, "Communications provider is not ready")
        if payload.channel == "voip" and not read_policy(db)["enabled"]:
            raise HTTPException(422, "VoIP policy is disabled")
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        recent = select(func.count()).select_from(CommunicationEvent).where(CommunicationEvent.channel == payload.channel,
            CommunicationEvent.dry_run.is_(False), CommunicationEvent.created_at >= cutoff)
        owner_count = db.scalar(recent.where(CommunicationEvent.owner_user_id == principal.user.id))
        global_count = db.scalar(recent)
        if int(owner_count or 0) >= 5 or int(global_count or 0) >= 100:
            raise HTTPException(429, "Hourly communications test budget reached", headers={"Retry-After": "3600"})
        count = db.scalar(select(func.count()).select_from(CommunicationEvent).where(
            CommunicationEvent.owner_user_id == principal.user.id, CommunicationEvent.status.in_(("queued", "processing", "sending"))))
        if int(count or 0) >= 3:
            raise HTTPException(429, "Pending test limit reached", headers={"Retry-After": "60"})
    event = CommunicationEvent(owner_user_id=principal.user.id, recipient_id=recipient.id, channel=payload.channel,
        dry_run=dry_run, status="dry_run" if dry_run else "queued", client_request_id=identifier,
        delivery_key=f"communication-test:{principal.user.id}:{identifier}",
        provider_response_summary={"recipient_label": recipient.label, "phone_masked": recipient.phone_masked,
            "blocked_reasons": blocked_reasons, "network_called": False})
    db.add(event)
    db.flush()
    add_audit_event(db, request, actor_admin_id=principal.user.id, action="admin.communications.test_created",
        resource_type="communication-event", resource_id=event.id, after={"channel": event.channel, "dry_run": dry_run})
    db.commit()
    return {"event_id": event.id, "status": event.status, "dry_run": dry_run, "blocked_reasons": blocked_reasons}


def _manual_event(row: CommunicationEvent) -> dict:
    summary = row.provider_response_summary or {}
    return {"id": f"manual:{row.id}", "channel": row.channel, "status": row.status,
        "recipient_label": summary.get("recipient_label", "Test recipient"), "phone_masked": summary.get("phone_masked", "***"),
        "created_at": row.created_at, "error_code": row.error_code, "provider_reference": row.provider_reference,
        "blocked_reasons": summary.get("blocked_reasons", [])}


def _alert_event(row: AlertDeliveryJob) -> dict:
    statuses = {"pending": "queued", "retrying": "queued", "dead": "failed"}
    summary = row.provider_response_summary or {}
    return {"id": f"alert:{row.id}", "channel": row.channel, "status": statuses.get(row.status, row.status),
        "recipient_label": f"Alert {row.alert_id}", "phone_masked": "***", "created_at": row.created_at,
        "error_code": row.last_error or summary.get("error_code"), "provider_reference": summary.get("reference_hash")}


@router.get("/deliveries")
def list_deliveries(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0, le=2147483647),
    principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ALERTS_READ)), db: Session = Depends(get_db)) -> dict:
    history = union_all(
        select(literal("manual").label("kind"), CommunicationEvent.id.label("id"), CommunicationEvent.created_at.label("created_at"))
            .where(CommunicationEvent.owner_user_id == principal.user.id),
        select(literal("alert"), AlertDeliveryJob.id, AlertDeliveryJob.created_at)
            .where(AlertDeliveryJob.channel.in_(("sms", "voip"))),
    ).subquery("communication_history")
    # Page scalar identities in the database before loading any receipt bodies.
    page = db.execute(select(history).order_by(history.c.created_at.desc(), history.c.kind.asc(), history.c.id.desc())
        .offset(offset).limit(limit)).mappings().all()
    manual_ids = [row["id"] for row in page if row["kind"] == "manual"]
    alert_ids = [row["id"] for row in page if row["kind"] == "alert"]
    records = {}
    if manual_ids:
        for row in db.scalars(select(CommunicationEvent).where(CommunicationEvent.id.in_(manual_ids),
            CommunicationEvent.owner_user_id == principal.user.id)).all():
            records[("manual", row.id)] = _manual_event(row)
    if alert_ids:
        for job in db.scalars(select(AlertDeliveryJob).where(AlertDeliveryJob.id.in_(alert_ids),
            AlertDeliveryJob.channel.in_(("sms", "voip")))).all():
            records[("alert", job.id)] = _alert_event(job)
    total = int(db.scalar(select(func.count()).select_from(history)) or 0)
    return {"items": [records[(row["kind"], row["id"])] for row in page if (row["kind"], row["id"]) in records], "total": total}


@router.get("/deliveries/{delivery_id}")
def delivery_detail(delivery_id: str, principal: AdminPrincipal = Depends(require_permission(AdminPermissionKey.ALERTS_READ)), db: Session = Depends(get_db)) -> dict:
    kind, separator, identifier = delivery_id.partition(":")
    if not separator or not identifier.isascii() or not identifier.isdigit():
        raise HTTPException(404, "Delivery not found")
    if kind == "manual":
        row = db.scalar(select(CommunicationEvent).where(CommunicationEvent.id == int(identifier), CommunicationEvent.owner_user_id == principal.user.id))
        if row is not None:
            return _manual_event(row)
    elif kind == "alert":
        job = db.scalar(select(AlertDeliveryJob).where(AlertDeliveryJob.id == int(identifier), AlertDeliveryJob.channel.in_(("sms", "voip"))))
        if job is not None:
            return _alert_event(job)
    raise HTTPException(404, "Delivery not found")
