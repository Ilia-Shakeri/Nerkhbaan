from __future__ import annotations

import asyncio
import ast
import ipaddress
import json
import logging
import math
import re
import socket
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Alert as AlertModel, PushSubscription, User
from ..db import SessionLocal

logger = logging.getLogger(__name__)

MAX_FORMULA_NODES = 40
FORMULA_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SOURCE_NAME_PATTERN = re.compile(r"[^a-z0-9]+")


class FormulaValidationError(ValueError):
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
                alert_type=row.alert_type,
                formula=row.formula,
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
        if alert.alert_type == "formula":
            if not alert.formula:
                return False
            try:
                return evaluate_formula(alert.formula, self._formula_values(alert, current_prices))
            except FormulaValidationError as exc:
                logger.warning("Formula alert %s skipped: %s", alert.id, exc)
                return False

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

    def _formula_values(self, alert: Alert, current_prices: dict[str, Any]) -> dict[str, float]:
        price_key = "price_usd" if alert.currency == "usd" else "price_toman"
        source_key = "source_usd" if alert.currency == "usd" else "source_toman"
        values: dict[str, float] = {}
        for asset in current_prices.get("assets", []):
            asset_id = str(asset.get("asset", "")).lower()
            value = asset.get(price_key)
            if not asset_id or not isinstance(value, (int, float)) or not math.isfinite(value):
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
                response.raise_for_status()
                logger.info("Webhook delivered for alert_id=%s", alert.id)
        except Exception as e:
            logger.error("Webhook failed for alert_id=%s: %s", alert.id, e)
            raise
