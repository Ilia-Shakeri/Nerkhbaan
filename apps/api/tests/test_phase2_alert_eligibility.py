from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime

os.environ["DEBUG"] = "false"

from app.schemas import AlertCreate
from app.models import Alert as AlertModel, AlertTriggerEvent
from app.services.alert_engine import Alert, AlertEngine


def _asset(**overrides):
    value = {
        "status": "live",
        "is_persisted": True,
        "persistence_status": "persisted",
        "live_eligible": True,
        "is_suspicious": False,
        "expired": False,
        "source_semantic": "exchange_trade",
        "derivation_depth": 0,
        "spread_bps": 10,
        "maximum_spread_bps": 100,
    }
    value.update(overrides)
    return value


class DefaultAlertEligibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = AlertEngine()

    def test_clean_direct_persisted_quote_is_operational(self) -> None:
        self.assertTrue(self.engine._asset_is_operational(_asset(), "usd"))

    def test_default_policy_rejects_derived_quote(self) -> None:
        self.assertFalse(
            self.engine._asset_is_operational(
                _asset(status="derived_fallback", derivation_depth=1),
                "usd",
            )
        )

    def test_reference_quote_needs_explicit_reference_mode(self) -> None:
        reference = _asset(source_semantic="reference_rate")

        self.assertFalse(self.engine._asset_is_operational(reference, "usd"))
        self.assertTrue(
            self.engine._asset_is_operational(reference, "usd", "reference")
        )

    def test_derived_quote_needs_explicit_derived_mode(self) -> None:
        derived = _asset(
            status="derived_fallback",
            source_semantic="derived",
            derivation_depth=1,
        )

        self.assertFalse(self.engine._asset_is_operational(derived, "usd"))
        self.assertTrue(self.engine._asset_is_operational(derived, "usd", "derived"))

    def test_existing_alert_request_defaults_to_ordinary_mode(self) -> None:
        alert = AlertCreate(asset="btc", target_price=100)

        self.assertEqual(alert.price_source_mode, "ordinary")

    def test_default_policy_rejects_suspicious_quote(self) -> None:
        self.assertFalse(
            self.engine._asset_is_operational(
                _asset(is_suspicious=True),
                "usd",
            )
        )

    def test_default_policy_rejects_expired_quote(self) -> None:
        self.assertFalse(
            self.engine._asset_is_operational(
                _asset(expired=True),
                "usd",
            )
        )

    def test_default_policy_rejects_unpersisted_quote(self) -> None:
        self.assertFalse(
            self.engine._asset_is_operational(
                _asset(
                    status="unpersisted",
                    is_persisted=False,
                    persistence_status="unpersisted",
                ),
                "usd",
            )
        )

    def test_default_policy_rejects_missing_persistence_and_risk_proof(self) -> None:
        complete = _asset()
        for key in (
            "is_persisted",
            "persistence_status",
            "is_suspicious",
            "expired",
            "live_eligible",
        ):
            with self.subTest(key=key):
                incomplete = {name: value for name, value in complete.items() if name != key}
                self.assertFalse(
                    self.engine._asset_is_operational(incomplete, "usd")
                )

    def test_default_policy_rejects_malformed_boolean_flags(self) -> None:
        for key, value in (
            ("is_persisted", "false"),
            ("is_suspicious", "false"),
            ("expired", "false"),
        ):
            with self.subTest(key=key):
                self.assertFalse(
                    self.engine._asset_is_operational(_asset(**{key: value}), "usd")
                )

    def test_default_policy_rejects_high_spread_quote(self) -> None:
        self.assertFalse(
            self.engine._asset_is_operational(
                _asset(spread_bps=250, maximum_spread_bps=100),
                "usd",
            )
        )

    def test_notification_summary_names_status_and_source(self) -> None:
        alert = Alert(
            id=1,
            user_id=1,
            asset_id="btc",
            target_price=100,
            condition="above",
            currency="usd",
            active=True,
            in_app_enabled=True,
            email_enabled=False,
            webhook_enabled=False,
            webhook_url=None,
            price_source_mode="reference",
        )
        current_prices = {
            "assets": [
                {
                    "asset": "btc",
                    "price_usd": 101,
                    "usd_status": "confirmed",
                    "usd_source_semantic": "reference_rate",
                    "usd_source_summary": {"source_family": "goldapi"},
                }
            ]
        }

        _title, body = self.engine._alert_summary(alert, current_prices)
        context = self.engine._selected_price_context(alert, current_prices)

        self.assertIn("status=confirmed", body)
        self.assertIn("source=reference_rate", body)
        self.assertEqual(context["status"], "confirmed")
        self.assertEqual(context["source_semantic"], "reference_rate")
        self.assertEqual(context["source_summary"], {"source_family": "goldapi"})

    def test_queued_trigger_snapshot_keeps_selected_source_context(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.rows = []

            def add(self, row) -> None:
                self.rows.append(row)

            def flush(self) -> None:
                for row in self.rows:
                    if isinstance(row, AlertTriggerEvent):
                        row.id = 1

        alert = AlertModel(
            id=1,
            user_id=1,
            asset="btc",
            target_price=100,
            alert_type="price",
            formula=None,
            currency_mode="usd",
            price_source_mode="reference",
            condition="above",
            notify_app=False,
            notify_email=False,
            notify_webhook=False,
            notify_telegram=False,
            notify_sms=False,
            webhook_url=None,
            enable_dlq=False,
            instrument_id="BTC_USD",
            mode="one_time",
            cooldown_seconds=900,
            max_notifications_per_day=10,
            notifications_today=0,
            is_active=True,
        )
        current_prices = {
            "refreshed_at": "2026-08-02T12:00:00+00:00",
            "assets": [
                {
                    "asset": "btc",
                    "price_usd": 101,
                    "usd_status": "confirmed",
                    "usd_source_semantic": "reference_rate",
                    "usd_source_summary": {"source_family": "goldapi"},
                }
            ],
        }
        db = FakeSession()

        self.engine._queue_trigger(
            db,
            alert,
            current_prices,
            datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            preferences=None,
            push_available=False,
        )

        event = next(row for row in db.rows if isinstance(row, AlertTriggerEvent))
        self.assertEqual(
            event.condition_snapshot["selected_price_context"],
            {
                "status": "confirmed",
                "source_semantic": "reference_rate",
                "source_summary": {"source_family": "goldapi"},
                "price_source_mode": "reference",
            },
        )

    def test_formula_summary_and_context_name_each_used_source(self) -> None:
        alert = Alert(
            id=2,
            user_id=1,
            asset_id="formula",
            target_price=100,
            condition="above",
            currency="usd",
            active=True,
            in_app_enabled=True,
            email_enabled=False,
            webhook_enabled=False,
            webhook_url=None,
            alert_type="formula",
            formula="btc + eth > x",
            price_source_mode="ordinary",
        )
        current_prices = {
            "assets": [
                {
                    "asset": "btc",
                    "price_usd": 60,
                    "usd_status": "live",
                    "usd_source_semantic": "exchange_trade",
                    "usd_source_summary": {"source_family": "venue_a"},
                    **_asset(),
                },
                {
                    "asset": "eth",
                    "price_usd": 50,
                    "usd_status": "confirmed",
                    "usd_source_semantic": "exchange_orderbook",
                    "usd_source_summary": {"source_family": "venue_b"},
                    **_asset(),
                },
                {
                    "asset": "gold",
                    "price_usd": 2000,
                    **_asset(),
                },
            ]
        }

        _title, body = self.engine._alert_summary(alert, current_prices)
        contexts = self.engine._formula_price_contexts(alert, current_prices)

        self.assertIn("BTC(status=live, source=exchange_trade)", body)
        self.assertIn("ETH(status=confirmed, source=exchange_orderbook)", body)
        self.assertNotIn("GOLD", body)
        self.assertEqual([context["asset"] for context in contexts], ["btc", "eth"])
        self.assertEqual(
            contexts[0]["source_summary"],
            {"source_family": "venue_a"},
        )


if __name__ == "__main__":
    unittest.main()
