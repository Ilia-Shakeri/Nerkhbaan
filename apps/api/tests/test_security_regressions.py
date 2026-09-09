"""Regression tests for the security defects found in the production audit.

Each test names the behaviour that was wrong and asserts the corrected one, so
a future refactor cannot quietly restore it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from app.migrations.state import migration_checksum, migrations_root
from app.security import resolve_client_ip


class ClientAddressTests(unittest.TestCase):
    """X-Forwarded-For is caller-controlled on its left side.

    Taking the first entry let anyone choose the address used for rate limits,
    the admin IP allowlist, and the hashed IP in the audit trail.
    """

    trusted = "127.0.0.1,::1,172.28.0.0/24"

    def test_forged_leading_entry_is_ignored(self) -> None:
        # A client sends "X-Forwarded-For: 10.0.0.5"; nginx appends the peer.
        resolved = resolve_client_ip(
            peer="172.28.0.7",
            forwarded_header="10.0.0.5, 203.0.113.9",
            trusted_raw=self.trusted,
        )
        self.assertEqual(resolved, "203.0.113.9")

    def test_header_is_ignored_when_the_peer_is_not_a_trusted_proxy(self) -> None:
        resolved = resolve_client_ip(
            peer="198.51.100.4",
            forwarded_header="10.0.0.5",
            trusted_raw=self.trusted,
        )
        self.assertEqual(resolved, "198.51.100.4")

    def test_cidr_ranges_are_honoured(self) -> None:
        # The public path previously compared trusted proxies as exact strings,
        # so a CIDR entry silently never matched.
        resolved = resolve_client_ip(
            peer="172.28.0.31",
            forwarded_header="203.0.113.9",
            trusted_raw="172.28.0.0/24",
        )
        self.assertEqual(resolved, "203.0.113.9")

    def test_a_chain_of_only_trusted_hops_falls_back_to_the_peer(self) -> None:
        resolved = resolve_client_ip(
            peer="172.28.0.7",
            forwarded_header="172.28.0.9, 172.28.0.8",
            trusted_raw=self.trusted,
        )
        self.assertEqual(resolved, "172.28.0.7")

    def test_garbage_in_the_header_does_not_leak_through(self) -> None:
        resolved = resolve_client_ip(
            peer="127.0.0.1",
            forwarded_header="not-an-address",
            trusted_raw=self.trusted,
        )
        self.assertEqual(resolved, "127.0.0.1")


class MigrationChecksumTests(unittest.TestCase):
    """The applier and the verifier must agree on what a migration hashes to.

    They previously hashed different byte streams - decoded text versus raw
    bytes - so any CRLF checkout made applied migrations look modified and the
    API refused to start.
    """

    def test_checksum_ignores_line_ending_style(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            lf = Path(directory) / "lf.sql"
            crlf = Path(directory) / "crlf.sql"
            lf.write_bytes(b"SELECT 1;\nSELECT 2;\n")
            crlf.write_bytes(b"SELECT 1;\r\nSELECT 2;\r\n")
            self.assertEqual(migration_checksum(lf), migration_checksum(crlf))

    def test_checksum_still_changes_when_the_sql_changes(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.sql"
            second = Path(directory) / "b.sql"
            first.write_text("SELECT 1;\n", encoding="utf-8")
            second.write_text("SELECT 2;\n", encoding="utf-8")
            self.assertNotEqual(migration_checksum(first), migration_checksum(second))

    def test_repository_migrations_are_all_readable(self) -> None:
        files = sorted(migrations_root().glob("*.sql"))
        self.assertGreater(len(files), 0)
        for path in files:
            self.assertEqual(len(migration_checksum(path)), 64)


class WebhookTargetTests(unittest.TestCase):
    def test_private_targets_are_refused(self) -> None:
        from app.services.alert_engine import validate_webhook_url

        for url in (
            "http://example.com/hook",           # not HTTPS
            "https://user:pass@example.com/hook",  # credentials
            "https://127.0.0.1/hook",            # loopback
            "https://10.0.0.5/hook",             # private
            "https://169.254.169.254/latest",    # link-local metadata
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_webhook_url(url)

    def test_resolution_returns_the_addresses_it_vetted(self) -> None:
        # The caller needs these to detect a host that changes address between
        # validation and the request.
        from app.services.alert_engine import validate_webhook_url

        self.assertEqual(validate_webhook_url("https://example.com/hook"), set())


class AlertSnapshotTests(unittest.TestCase):
    """Trigger snapshots must stay small.

    Storing every asset with its full history array made each row hundreds of
    kilobytes, re-read on every delivery retry.
    """

    def test_snapshot_keeps_only_the_referenced_asset_and_drops_history(self) -> None:
        from app.models import Alert as AlertModel
        from app.services.alert_engine import AlertEngine

        alert = AlertModel(
            id=1, user_id=1, asset="gold", alert_type="price",
            target_price=100.0, condition="above", currency_mode="usd",
        )
        prices = {
            "assets": [
                {"asset": "gold", "price_usd": 1.0, "history": [{"t": 1}] * 48},
                {"asset": "btc", "price_usd": 2.0, "history": [{"t": 1}] * 48},
            ]
        }
        trimmed = AlertEngine._relevant_assets(alert, prices)
        self.assertEqual([row["asset"] for row in trimmed], ["gold"])
        self.assertNotIn("history", trimmed[0])

    def test_formula_alerts_keep_every_asset_they_reference(self) -> None:
        from app.models import Alert as AlertModel
        from app.services.alert_engine import AlertEngine

        alert = AlertModel(
            id=2, user_id=1, asset="formula", alert_type="formula",
            formula="gold > btc", condition="above", currency_mode="usd",
        )
        prices = {
            "assets": [
                {"asset": "gold", "price_usd": 1.0, "history": []},
                {"asset": "btc", "price_usd": 2.0, "history": []},
                {"asset": "usdt", "price_usd": 1.0, "history": []},
            ]
        }
        trimmed = AlertEngine._relevant_assets(alert, prices)
        self.assertEqual(sorted(row["asset"] for row in trimmed), ["btc", "gold"])


class SpreadEligibilityTests(unittest.TestCase):
    """The alert spread gate was dead: nothing ever populated its bound."""

    def test_instruments_declare_a_maximum_spread(self) -> None:
        from app.pricing.instruments import INSTRUMENTS

        for instrument_id, instrument in INSTRUMENTS.items():
            with self.subTest(instrument=instrument_id):
                self.assertGreater(instrument.maximum_spread_bps, 0)

    def test_canonical_quotes_carry_the_bound(self) -> None:
        from datetime import UTC, datetime
        from decimal import Decimal

        from app.pricing.canonical import CanonicalPricePolicy
        from app.pricing.instruments import get_instrument
        from app.pricing.models import VerificationStatus

        now = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
        quote = CanonicalPricePolicy._from_price(
            instrument=get_instrument("USDT_TOMAN"),
            price=Decimal("60000"),
            observed_at=now,
            current=now,
            status=__import__(
                "app.pricing.models", fromlist=["CanonicalStatus"]
            ).CanonicalStatus.LIVE,
            primary_quote_id=1,
            verification_quote_ids=[],
            verification_status=VerificationStatus.NOT_REQUIRED,
            reason="test",
            source_summary={},
        )
        self.assertIn("maximum_spread_bps", quote.source_summary)
        self.assertIsNotNone(quote.source_summary["maximum_spread_bps"])


if __name__ == "__main__":
    unittest.main()
