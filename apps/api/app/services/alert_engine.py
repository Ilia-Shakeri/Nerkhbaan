from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert as AlertModel, PushSubscription, User
from ..db import SessionLocal

logger = logging.getLogger(__name__)


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


class AlertEngine:
    def __init__(self, dlq_callback=None):
        self.dlq_callback = dlq_callback

    async def evaluate_alerts(self, current_prices: dict[str, Any]) -> None:
        db: Session = SessionLocal()
        try:
            alerts = self._fetch_active_alerts(db)

            tasks = []
            triggered_ids: list[int] = []
            for alert in alerts:
                if self._should_trigger(alert, current_prices):
                    tasks.append(self._deliver_alert(alert, current_prices))
                    triggered_ids.append(alert.id)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                # Mark as triggered once dispatched so the same alert does not
                # re-fire on every evaluation cycle. Retries are owned by the DLQ.
                self._mark_triggered(db, triggered_ids)
        finally:
            db.close()

    def _fetch_active_alerts(self, db: Session) -> list[Alert]:
        rows = db.scalars(
            select(AlertModel).where(
                AlertModel.is_active.is_(True),
                AlertModel.triggered_at.is_(None),
            )
        ).all()
        return [
            Alert(
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
            )
            for row in rows
        ]

    def _mark_triggered(self, db: Session, alert_ids: list[int]) -> None:
        if not alert_ids:
            return
        now = datetime.now(UTC)
        rows = db.scalars(
            select(AlertModel).where(AlertModel.id.in_(alert_ids))
        ).all()
        for row in rows:
            row.triggered_at = now
        db.commit()

    def _should_trigger(self, alert: Alert, current_prices: dict[str, Any]) -> bool:
        assets = current_prices.get("assets", [])
        
        asset_data = next((a for a in assets if a["asset"] == alert.asset_id), None)
        if not asset_data:
            return False
        
        if alert.currency == "usd":
            price = asset_data.get("price_usd")
        else:
            price = asset_data.get("price_toman")
        
        if price is None:
            return False
        
        if alert.condition == "above":
            return price >= alert.target_price
        elif alert.condition == "below":
            return price <= alert.target_price
        
        return False

    async def _deliver_alert(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        tasks = []
        
        if alert.in_app_enabled:
            tasks.append(self._send_push_notification(alert, current_prices))
        
        if alert.email_enabled:
            tasks.append(self._send_email(alert, current_prices))
        
        if alert.webhook_enabled and alert.webhook_url:
            tasks.append(self._send_webhook(alert, current_prices))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Alert delivery failed for alert_id={alert.id}, method={i}: {result}")
                if self.dlq_callback:
                    await self.dlq_callback(alert, i, result)

    def _current_price(self, alert: Alert, current_prices: dict[str, Any]) -> float | None:
        asset_data = next(
            (a for a in current_prices.get("assets", []) if a["asset"] == alert.asset_id),
            None,
        )
        if not asset_data:
            return None
        return asset_data.get("price_usd") if alert.currency == "usd" else asset_data.get("price_toman")

    def _alert_summary(self, alert: Alert, current_prices: dict[str, Any]) -> tuple[str, str]:
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
            logger.warning(
                "Push requested for alert_id=%s but VAPID keys are not configured; skipping.",
                alert.id,
            )
            return
        if alert.user_id is None:
            return

        try:
            from pywebpush import WebPushException, webpush  # noqa: WPS433
        except ImportError:
            logger.error("pywebpush is not installed; cannot deliver web push notifications.")
            raise

        db: Session = SessionLocal()
        try:
            subscriptions = db.scalars(
                select(PushSubscription).where(PushSubscription.user_id == alert.user_id)
            ).all()
            targets = [
                (sub.endpoint, sub.p256dh, sub.auth) for sub in subscriptions
            ]
        finally:
            db.close()

        if not targets:
            return

        title, body = self._alert_summary(alert, current_prices)
        payload = json.dumps({"title": title, "body": body, "asset": alert.asset_id})
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

        if delivered == 0 and not expired_endpoints:
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
        if not (settings.smtp_host and settings.smtp_username and settings.smtp_password):
            logger.warning(
                "Email requested for alert_id=%s but SMTP is not configured; skipping.",
                alert.id,
            )
            return

        db: Session = SessionLocal()
        try:
            recipient = db.scalar(select(User.email).where(User.id == alert.user_id))
        finally:
            db.close()

        if not recipient:
            logger.error("No email on file for alert_id=%s user_id=%s", alert.id, alert.user_id)
            return

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
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(message)
            else:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(message)

        await asyncio.to_thread(_smtp_send)
        logger.info("Email sent for alert_id=%s", alert.id)

    async def _send_webhook(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        if not alert.webhook_url:
            return
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
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
                response.raise_for_status()
                logger.info(f"Webhook delivered for alert_id={alert.id} to {alert.webhook_url}")
        except Exception as e:
            logger.error(f"Webhook failed for alert_id={alert.id}: {e}")
            raise
