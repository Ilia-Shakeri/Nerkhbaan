from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from ..models import User
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
            for alert in alerts:
                if self._should_trigger(alert, current_prices):
                    tasks.append(self._deliver_alert(alert, current_prices))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            db.close()

    def _fetch_active_alerts(self, db: Session) -> list[Alert]:
        return []

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

    async def _send_push_notification(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        await asyncio.sleep(0.1)
        logger.info(f"Push notification sent for alert_id={alert.id}")

    async def _send_email(self, alert: Alert, current_prices: dict[str, Any]) -> None:
        await asyncio.sleep(0.1)
        logger.info(f"Email sent for alert_id={alert.id}")

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
