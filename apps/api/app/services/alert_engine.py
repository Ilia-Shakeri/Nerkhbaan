from __future__ import annotations

import asyncio
import ast
import hashlib
import ipaddress
import json
import logging
import math
import re
import socket
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Alert as AlertModel,
    AlertDeliveryJob,
    AlertTriggerEvent,
    NotificationPreference,
    PushSubscription,
    UserNotification,
)
from ..db import SessionLocal

logger = logging.getLogger(__name__)

MAX_FORMULA_NODES = 40
FORMULA_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SOURCE_NAME_PATTERN = re.compile(r"[^a-z0-9]+")


class FormulaValidationError(ValueError):
    pass


class PermanentDeliveryError(RuntimeError):
    pass


def validate_webhook_url(url: str, *, resolve_dns: bool = False) -> None:
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Webhook URL must use HTTPS and include a host")
    if parsed.username or parsed.password:
        raise ValueError("Webhook URL credentials are not allowed")

    hosts: set[str] = {parsed.hostname}
    if resolve_dns:
        try:
            hosts = {
                item[4][0]
                for item in socket.getaddrinfo(
                    parsed.hostname,
                    parsed.port or 443,
                    type=socket.SOCK_STREAM,
                )
            }
        except socket.gaierror as exc:
            raise ValueError("Webhook host cannot be resolved") from exc

    for host in hosts:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if resolve_dns:
                raise ValueError("Webhook host returned an invalid address")
            continue
        if not address.is_global:
            raise ValueError("Webhook host must resolve to a public address")


def _parse_formula(formula: str) -> ast.Expression:
    if len(formula) > 200:
        raise FormulaValidationError("Formula is too long")
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaValidationError("Formula syntax is invalid") from exc

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_FORMULA_NODES:
        raise FormulaValidationError("Formula is too complex")

    allowed = (
        ast.Expression,
        ast.Compare,
        ast.BinOp,
        ast.UnaryOp,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.UAdd,
        ast.USub,
        ast.Gt,
        ast.GtE,
        ast.Lt,
        ast.LtE,
    )
    if any(not isinstance(node, allowed) for node in nodes):
        raise FormulaValidationError("Formula contains an unsupported operation")
    if not isinstance(tree.body, ast.Compare) or len(tree.body.ops) != 1:
        raise FormulaValidationError("Formula must contain one comparison")
    for node in nodes:
        if isinstance(node, ast.Name) and not FORMULA_NAME_PATTERN.fullmatch(node.id.lower()):
            raise FormulaValidationError("Formula contains an invalid market name")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
        ):
            raise FormulaValidationError("Formula constants must be numbers")
    return tree


def validate_formula(formula: str) -> None:
    _parse_formula(formula)


def _formula_value(node: ast.AST, values: dict[str, float]) -> float | bool:
    if isinstance(node, ast.Constant):
        value = float(node.value)
        if not math.isfinite(value):
            raise FormulaValidationError("Formula number is not finite")
        return value
    if isinstance(node, ast.Name):
        name = node.id.lower()
        if name not in values:
            raise FormulaValidationError(f"Market value is unavailable: {name}")
        return values[name]
    if isinstance(node, ast.UnaryOp):
        value = float(_formula_value(node.operand, values))
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = float(_formula_value(node.left, values))
        right = float(_formula_value(node.right, values))
        if isinstance(node.op, ast.Add):
            result = left + right
        elif isinstance(node.op, ast.Sub):
            result = left - right
        elif isinstance(node.op, ast.Mult):
            result = left * right
        else:
            if right == 0:
                raise FormulaValidationError("Formula divides by zero")
            result = left / right
        if not math.isfinite(result):
            raise FormulaValidationError("Formula result is not finite")
        return result
    if isinstance(node, ast.Compare):
        left = float(_formula_value(node.left, values))
        right = float(_formula_value(node.comparators[0], values))
        operator = node.ops[0]
        if isinstance(operator, ast.Gt):
            return left > right
        if isinstance(operator, ast.GtE):
            return left >= right
        if isinstance(operator, ast.Lt):
            return left < right
        return left <= right
    raise FormulaValidationError("Formula node is not supported")


def evaluate_formula(formula: str, values: dict[str, float]) -> bool:
    return bool(_formula_value(_parse_formula(formula).body, values))


class Alert:
    def __init__(
        self,
        id: int,
        user_id: int,
        asset_id: str,
        target_price: float,
        condition: str,
        currency: str,
        active: bool,
        in_app_enabled: bool,
        email_enabled: bool,
        webhook_enabled: bool,
        webhook_url: str | None,
        alert_type: str = "price",
        formula: str | None = None,
    ):
        self.id = id
        self.user_id = user_id
        self.asset_id = asset_id
        self.target_price = target_price
        self.condition = condition
        self.currency = currency
        self.active = active
        self.in_app_enabled = in_app_enabled
        self.email_enabled = email_enabled
        self.webhook_enabled = webhook_enabled
        self.webhook_url = webhook_url
        self.alert_type = alert_type
        self.formula = formula


class AlertEngine:
    async def evaluate_alerts(self, current_prices: dict[str, Any]) -> None:
        await asyncio.to_thread(self._evaluate_and_enqueue, current_prices)

    def _evaluate_and_enqueue(self, current_prices: dict[str, Any]) -> None:
        db: Session = SessionLocal()
        try:
            rows = db.scalars(
                select(AlertModel)
                .where(AlertModel.is_active.is_(True))
                .with_for_update(skip_locked=True)
            ).all()
            user_ids = {row.user_id for row in rows}
            preferences_by_user = (
                {
                    preference.user_id: preference
                    for preference in db.scalars(
                        select(NotificationPreference).where(
                            NotificationPreference.user_id.in_(user_ids)
                        )
                    ).all()
                }
                if user_ids
                else {}
            )
            push_users = (
                set(
                    db.scalars(
                        select(PushSubscription.user_id).where(
                            PushSubscription.user_id.in_(user_ids)
                        )
                    ).all()
                )
                if user_ids
                else set()
            )
            now = datetime.now(UTC)
            for row in rows:
                preferences = preferences_by_user.get(row.user_id)
                recurring_enabled = bool(
                    row.mode == "recurring"
                    or (preferences and preferences.aggressive_alerts)
                )
                condition_met = self._should_trigger_model(row, current_prices)
                if not condition_met:
                    if row.last_condition_state:
                        row.last_condition_state = False
                    continue

                if not recurring_enabled and row.triggered_at is not None:
                    continue
                if recurring_enabled and row.last_condition_state:
                    continue
                if row.next_eligible_trigger_at and row.next_eligible_trigger_at > now:
                    continue

                if row.notification_day != now.date():
                    row.notification_day = now.date()
                    row.notifications_today = 0
                if row.notifications_today >= row.max_notifications_per_day:
                    continue

                self._queue_trigger(
                    db,
                    row,
                    current_prices,
                    now,
                    preferences=preferences,
                    push_available=row.user_id in push_users,
                )
                row.last_condition_state = True
                row.triggered_at = now
                row.notifications_today += 1
                if recurring_enabled:
                    row.next_eligible_trigger_at = now + timedelta(seconds=row.cooldown_seconds)
                else:
                    row.is_active = False
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _delivery_alert(row: AlertModel) -> Alert:
        return Alert(
            id=row.id,
            user_id=row.user_id,
            asset_id=row.asset,
            target_price=row.target_price,
            condition=row.condition,
            currency=row.currency_mode,
            active=row.is_active,
            in_app_enabled=row.notify_app,
            email_enabled=row.notify_email,
            webhook_enabled=row.notify_webhook,
            webhook_url=row.webhook_url,
            alert_type=row.alert_type,
            formula=row.formula,
        )

    @staticmethod
    def _asset_status(asset: dict[str, Any], currency: str) -> str:
        return str(
            asset.get("status")
            or asset.get("usd_status" if currency == "usd" else "toman_status")
            or "unavailable"
        ).lower()

    def _asset_is_operational(self, asset: dict[str, Any], currency: str) -> bool:
        return self._asset_status(asset, currency) in {
            "live",
            "confirmed",
            "fresh_cache",
            "derived_fallback",
            "unpersisted",
        }

    def _should_trigger_model(self, alert: AlertModel, current_prices: dict[str, Any]) -> bool:
        wrapper = self._delivery_alert(alert)
        if alert.alert_type == "formula":
            if not alert.formula:
                return False
            try:
                return evaluate_formula(alert.formula, self._formula_values(wrapper, current_prices))
            except FormulaValidationError as exc:
                logger.warning("Formula alert %s skipped: %s", alert.id, exc)
                return False

        assets = current_prices.get("assets", [])
        asset_data = next((a for a in assets if a["asset"] == alert.asset), None)
        if not asset_data:
            return False

        if not self._asset_is_operational(asset_data, alert.currency_mode):
            return False
        if alert.currency_mode == "usd":
            price = asset_data.get("price_usd")
        else:
            price = asset_data.get("price_toman")
        if not isinstance(price, (int, float)) or not math.isfinite(price) or alert.target_price is None:
            return False
        if alert.condition == "above":
            return price >= alert.target_price
        if alert.condition == "below":
            return price <= alert.target_price
        return False

    def _queue_trigger(
        self,
        db: Session,
        alert: AlertModel,
        current_prices: dict[str, Any],
        now: datetime,
        *,
        preferences: NotificationPreference | None,
        push_available: bool,
    ) -> None:
        snapshot = {
            "refreshed_at": current_prices.get("refreshed_at"),
            "assets": current_prices.get("assets", []),
        }
        seed = f"{alert.id}|{now.isoformat()}|{alert.notifications_today}"
        event_key = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        current_price = self._current_price(self._delivery_alert(alert), snapshot)
        event = AlertTriggerEvent(
            alert_id=alert.id,
            instrument_id=alert.instrument_id,
            price=current_price,
            condition_snapshot=snapshot,
            status="pending",
            idempotency_key=event_key,
        )
        db.add(event)
        db.flush()

        channels: list[tuple[str, str]] = []
        in_app_delivered = bool(
            alert.notify_app
            and self._push_is_enabled(preferences)
        )
        if in_app_delivered:
            title, body = self._alert_summary(self._delivery_alert(alert), snapshot)
            db.add(
                UserNotification(
                    user_id=alert.user_id,
                    title=title,
                    message=body,
                    severity="warning",
                    resource_type="alert",
                    resource_id=str(alert.id),
                )
            )
            if (
                push_available
                and settings.vapid_private_key
                and settings.vapid_public_key
            ):
                channels.append(("push", f"user:{alert.user_id}:push"))
        if (
            alert.notify_email
            and settings.smtp_host
            and self._email_destination(preferences)
        ):
            channels.append(("email", f"user:{alert.user_id}:email"))
        if alert.notify_webhook and alert.webhook_url:
            channels.append(("webhook", f"alert:{alert.id}:webhook"))
        if (
            alert.notify_telegram
            and settings.telegram_alert_delivery_enabled
            and settings.telegram_bot_token
            and self._telegram_destination(preferences)
        ):
            channels.append(("telegram", f"user:{alert.user_id}:telegram"))

        for channel, destination in channels:
            db.add(
                AlertDeliveryJob(
                    alert_id=alert.id,
                    trigger_event_id=event.id,
                    channel=channel,
                    destination_reference=destination,
                    status="pending",
                    next_retry_at=now,
                    idempotency_key=f"{event_key}:{channel}",
                )
            )
        event.status = "queued" if channels else (
            "delivered" if in_app_delivered else "no_delivery_channel"
        )

    @staticmethod
    def _push_is_enabled(preferences: NotificationPreference | None) -> bool:
        # A missing row keeps the model's backwards-compatible default.
        return preferences is None or preferences.push_app

    @staticmethod
    def _email_destination(preferences: NotificationPreference | None) -> str | None:
        if not (
            preferences
            and preferences.email_enabled
            and preferences.email_verified
            and preferences.email_address
        ):
            return None
        return preferences.email_address.strip().lower() or None

    @staticmethod
    def _telegram_destination(preferences: NotificationPreference | None) -> str | None:
        if not (
            preferences
            and preferences.telegram_enabled
            and preferences.telegram_verified
            and preferences.telegram_id
        ):
            return None
        return preferences.telegram_id.strip() or None

    def _formula_values(self, alert: Alert, current_prices: dict[str, Any]) -> dict[str, float]:
        price_key = "price_usd" if alert.currency == "usd" else "price_toman"
        source_key = "source_usd" if alert.currency == "usd" else "source_toman"
        values: dict[str, float] = {}
        for asset in current_prices.get("assets", []):
            asset_id = str(asset.get("asset", "")).lower()
            value = asset.get(price_key)
            if (
                not asset_id
                or not self._asset_is_operational(asset, alert.currency)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                continue
            values[asset_id] = float(value)
            source = SOURCE_NAME_PATTERN.sub("_", str(asset.get(source_key, "")).lower()).strip("_")
            if source:
                values[f"{asset_id}_{source}"] = float(value)

        if "usd" in values:
            values.setdefault("dollar", values["usd"])
        if alert.target_price is not None:
            values["x"] = float(alert.target_price)
        return values

    async def deliver_job(self, job_id: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            job = db.get(AlertDeliveryJob, job_id)
            if not job:
                raise PermanentDeliveryError("Delivery job no longer exists")
            event = db.get(AlertTriggerEvent, job.trigger_event_id)
            row = db.get(AlertModel, job.alert_id)
            if not event or not row:
                raise PermanentDeliveryError("Alert trigger context no longer exists")
            alert = self._delivery_alert(row)
            snapshot = event.condition_snapshot
            channel = job.channel
        finally:
            db.close()

        if channel == "push":
            await self._send_push_notification(alert, snapshot)
        elif channel == "email":
            await self._send_email(alert, snapshot)
        elif channel == "webhook":
            await self._send_webhook(alert, snapshot)
        elif channel == "telegram":
            await self._send_telegram(alert, snapshot)
        else:
            raise PermanentDeliveryError("Unsupported delivery channel")
        return {"channel": channel, "accepted": True}

    def _current_price(self, alert: Alert, current_prices: dict[str, Any]) -> float | None:
        asset_data = next(
            (a for a in current_prices.get("assets", []) if a["asset"] == alert.asset_id),
            None,
        )
        if not asset_data:
            return None
        return asset_data.get("price_usd") if alert.currency == "usd" else asset_data.get("price_toman")

    def _alert_summary(self, alert: Alert, current_prices: dict[str, Any]) -> tuple[str, str]:
        if alert.alert_type == "formula":
            title = "Nerkhbaan formula alert"
            return title, f"Formula condition met: {alert.formula}"
        price = self._current_price(alert, current_prices)
        price_text = f"{price:,.2f}" if isinstance(price, (int, float)) else "-"
        unit = alert.currency.upper()
        title = f"Nerkhbaan alert: {alert.asset_id.upper()}"
        body = (
            f"{alert.asset_id.upper()} is now {price_text} {unit} "
            f"({alert.condition} target {alert.target_price:,.2f} {unit})."
        )
        return title, body

    async def _send_push_notification(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        if not (settings.vapid_private_key and settings.vapid_public_key):
            raise PermanentDeliveryError("Push delivery is not configured")
        if alert.user_id is None:
            raise PermanentDeliveryError("Alert has no user")

        db: Session = SessionLocal()
        try:
            preferences = db.scalar(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == alert.user_id
                )
            )
            if not self._push_is_enabled(preferences):
                raise PermanentDeliveryError("Push delivery is disabled by the user")
            silent_mode = bool(preferences and preferences.silent_mode)
            subscriptions = db.scalars(
                select(PushSubscription).where(PushSubscription.user_id == alert.user_id)
            ).all()
            targets = [
                (sub.endpoint, sub.p256dh, sub.auth) for sub in subscriptions
            ]
        finally:
            db.close()

        if not targets:
            raise PermanentDeliveryError("User has no push subscription")

        try:
            from pywebpush import WebPushException, webpush  # noqa: WPS433
        except ImportError:
            logger.error("pywebpush is not installed; cannot deliver web push notifications.")
            raise

        title, body = self._alert_summary(alert, current_prices)
        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "asset": alert.asset_id,
                "silent": silent_mode,
            }
        )
        expired_endpoints: list[str] = []

        def _push(endpoint: str, p256dh: str, auth: str) -> None:
            webpush(
                subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                timeout=10,
            )

        delivered = 0
        for endpoint, p256dh, auth in targets:
            try:
                await asyncio.to_thread(_push, endpoint, p256dh, auth)
                delivered += 1
            except WebPushException as exc:
                status_code = getattr(exc.response, "status_code", None)
                # 404/410 mean the browser dropped the subscription; prune it.
                if status_code in (404, 410):
                    expired_endpoints.append(endpoint)
                else:
                    logger.error("Web push failed for alert_id=%s: %s", alert.id, exc)

        if expired_endpoints:
            self._prune_subscriptions(expired_endpoints)

        if delivered == 0:
            if expired_endpoints:
                raise PermanentDeliveryError("All push subscriptions expired")
            raise RuntimeError("No push subscription accepted the notification")
        logger.info("Push delivered for alert_id=%s to %s endpoint(s)", alert.id, delivered)

    def _prune_subscriptions(self, endpoints: list[str]) -> None:
        db: Session = SessionLocal()
        try:
            rows = db.scalars(
                select(PushSubscription).where(PushSubscription.endpoint.in_(endpoints))
            ).all()
            for row in rows:
                db.delete(row)
            db.commit()
        finally:
            db.close()

    async def _send_email(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        if not settings.smtp_host:
            raise PermanentDeliveryError("Email delivery is not configured")

        db: Session = SessionLocal()
        try:
            preferences = db.scalar(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == alert.user_id
                )
            )
            recipient = self._email_destination(preferences)
        finally:
            db.close()

        if not recipient:
            raise PermanentDeliveryError("User has no enabled verified email destination")

        title, body = self._alert_summary(alert, current_prices)
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = title
        message.set_content(body)

        def _smtp_send() -> None:
            if settings.smtp_use_tls:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    server.starttls(context=ssl.create_default_context())
                    if settings.smtp_username and settings.smtp_password:
                        server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(message)
            else:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    if settings.smtp_username and settings.smtp_password:
                        server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(message)

        await asyncio.to_thread(_smtp_send)
        logger.info("Email sent for alert_id=%s", alert.id)

    async def _send_webhook(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        if not alert.webhook_url:
            return
        
        try:
            await asyncio.to_thread(validate_webhook_url, alert.webhook_url, resolve_dns=True)
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                payload = {
                    "alert_id": alert.id,
                    "asset": alert.asset_id,
                    "target_price": alert.target_price,
                    "condition": alert.condition,
                    "currency": alert.currency,
                    "triggered_at": datetime.now(UTC).isoformat(),
                    "current_prices": current_prices
                }
                response = await client.post(alert.webhook_url, json=payload)
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    raise PermanentDeliveryError(f"Webhook rejected request with status {response.status_code}")
                response.raise_for_status()
                logger.info("Webhook delivered for alert_id=%s", alert.id)
        except PermanentDeliveryError:
            raise
        except Exception as e:
            logger.error("Webhook failed for alert_id=%s: %s", alert.id, e)
            raise

    async def _send_telegram(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        if not settings.telegram_alert_delivery_enabled or not settings.telegram_bot_token:
            raise PermanentDeliveryError("Telegram alert delivery is not configured")
        db = SessionLocal()
        try:
            prefs = db.scalar(
                select(NotificationPreference).where(NotificationPreference.user_id == alert.user_id)
            )
            destination = self._telegram_destination(prefs)
            silent_mode = bool(prefs and prefs.silent_mode)
        finally:
            db.close()
        if not destination:
            raise PermanentDeliveryError("User has no verified Telegram destination")
        title, body = self._alert_summary(alert, current_prices)
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
                response = await client.post(
                    url,
                    json={
                        "chat_id": destination,
                        "text": f"{title}\n{body}",
                        "disable_notification": silent_mode,
                    },
                )
            if 400 <= response.status_code < 500 and response.status_code != 429:
                raise PermanentDeliveryError("Telegram destination rejected the alert")
            response.raise_for_status()
        except PermanentDeliveryError:
            raise
        except Exception as exc:
            raise RuntimeError("Telegram delivery failed") from exc
