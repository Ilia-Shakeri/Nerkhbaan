"""Portable behavior checks; no external network, accounts, or databases."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parser = load("telegram_price_parser", "apps/telegram_worker/app/parser.py")
worker = load("external_price_worker", "infra/price-worker/worker.py")
feed = load("public_price_feed", "scripts/build-price-feed.py")
delivery = load("source_delivery", "scripts/build_delivery_archive.py")


class TelegramParserTests(unittest.TestCase):
    def test_api_preview_matches_worker(self):
        mirror = ROOT / "apps/api/app/admin/telegram_parser.py"
        self.assertTrue(mirror.is_file(), "Admin preview must ship the worker parser")
        self.assertEqual(mirror.read_bytes(), (ROOT / "apps/telegram_worker/app/parser.py").read_bytes())
    def parse(self, text, parser_type="strict_explicit"):
        return parser.parse_message(text, allowed_instruments={"GOLD_18K_TOMAN_GRAM", "USDT_TOMAN"}, parser_type=parser_type, minimum_confidence=Decimal("0.8"))[0]

    def test_rial_converts_once(self):
        quote = self.parse("طلای ۱۸ عیار هر گرم 9000000 ریال")
        self.assertEqual(quote.price, Decimal("900000"))
        self.assertEqual(quote.currency, "TOMAN")

    def test_decimal_preserved(self):
        self.assertEqual(self.parse("USDT 100000.5 تومان").price, Decimal("100000.5"))
        self.assertEqual(self.parse("USDT ۱۰۰٬۰۰۰٫۵ تومان").price, Decimal("100000.5"))

    def test_missing_or_mixed_unit_rejected(self):
        for text in ("USDT 100000", "USDT 100000 ریال تومان"):
            self.assertEqual(self.parse(text).validation_status, "rejected")

    def test_hashtag_required(self):
        self.assertEqual(self.parse("USDT 100000 تومان", "strict_hashtag").validation_status, "rejected")
        self.assertEqual(self.parse("#USDT 100000 تومان", "strict_hashtag").validation_status, "accepted")

    def test_ambiguous_quote_rejected(self):
        self.assertEqual(self.parse("USDT 100000 200000 تومان").rejection_reason, "ambiguous_price")

    def test_channel_identity(self):
        self.assertEqual(parser.normalize_channel_id(12345), "-10012345")
        self.assertEqual(parser.normalize_channel_id("-10012345"), "-10012345")
        with self.assertRaises(ValueError):
            parser.normalize_channel_id("-12345")


class ExternalWorkerTests(unittest.TestCase):
    def test_history_does_not_ack_ignored_quotes(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 202
        response.read.return_value = json.dumps({"accepted": 1, "history_persisted": 0, "ignored": 1}).encode()
        with patch.object(worker, "ENDPOINT", "https://fixture.invalid/worker"), patch.object(worker, "urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "persist every historical"):
                worker.send([{"historical": True}])
        response.read.return_value = json.dumps({"accepted": 1, "history_persisted": 1, "ignored": 0}).encode()
        with patch.object(worker, "ENDPOINT", "https://fixture.invalid/worker"), patch.object(worker, "urlopen", return_value=response):
            worker.send([{"historical": True}])

    def test_live_preserves_source_time(self):
        source_time = int(datetime.now(UTC).timestamp()) - 120
        data = {asset: {"usd": 1, "last_updated_at": source_time} for asset, _, _ in worker.ASSETS}
        with patch.object(worker, "get_json", return_value=data), patch.object(worker, "send") as send:
            worker.live()
        self.assertTrue(all(datetime.fromisoformat(q["observed_at"]).timestamp() == source_time for q in send.call_args.args[0]))

    def test_stale_live_is_not_sent(self):
        data = {asset: {"usd": 1, "last_updated_at": 1} for asset, _, _ in worker.ASSETS}
        with patch.object(worker, "get_json", return_value=data), patch.object(worker, "send") as send:
            with self.assertRaises(RuntimeError):
                worker.live()
        send.assert_not_called()

    def test_live_runs_before_failed_history(self):
        order = []
        with patch.object(worker, "live", side_effect=lambda: order.append("live")), patch.object(worker, "backfill", side_effect=RuntimeError("fixture")):
            with self.assertRaises(RuntimeError):
                worker.run()
        self.assertEqual(order, ["live"])

    def test_history_continues_next_asset_and_keeps_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def get(url):
                calls.append(url)
                if "bitcoin" in url:
                    raise RuntimeError("fixture")
                return {"prices": [[1700000000000, 1]]}
            with patch.object(worker, "STATE_FILE", Path(directory) / "state.json"), patch.object(worker, "get_json", side_effect=get), patch.object(worker, "send") as send:
                with self.assertRaises(RuntimeError):
                    worker.backfill()
                self.assertTrue((Path(directory) / "state.json").exists())
                self.assertEqual(send.call_count, 1)
                self.assertEqual(len(calls), 2)


class PublicFeedTests(unittest.TestCase):
    def test_source_time_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            feed._time("2026-10-11T00:00:00", "fixture", datetime(2026, 10, 11, tzinfo=UTC), timedelta(seconds=600))
    def test_ten_minute_bound(self):
        now = datetime(2026, 10, 11, tzinfo=UTC)
        metals = {"symbol": "XAG", "currency": "USD", "price": 30, "updatedAt": (now - timedelta(seconds=601)).isoformat()}
        crypto = {asset: {"usd": value, "last_updated_at": now.timestamp()} for asset, value in (("bitcoin", 60000), ("tether", 1))}
        with self.assertRaises(ValueError):
            feed.build_feed(metals, crypto, now)
        metals["updatedAt"] = (now - timedelta(seconds=600)).isoformat()
        self.assertEqual(len(feed.build_feed(metals, crypto, now)["quotes"]), 3)


class DeliveryExclusionTests(unittest.TestCase):
    def test_required_database_source_ships_without_allowing_sql_dumps(self):
        required_init = Path("apps/api/db/init/001_timescale_market_prices.sql")
        self.assertTrue((ROOT / required_init).is_file())
        for filename in (required_init, Path("apps/api/db/init/init.sql"), Path("apps/api/db/migrations/20261011_001_delivery_hardening.sql")):
            self.assertTrue(delivery.allowed(filename), str(filename))
        for filename in ("backup.sql", "init.sql", "private/init.sql", "apps/api/db/init/backup.sql", "private/migrations/20261011_dump.sql", "apps/api/db/migrations/dump.sql"):
            self.assertFalse(delivery.allowed(Path(filename)), filename)

    def test_secret_scan_blocks_keys_and_unknown_driver_dsns(self):
        self.assertFalse(delivery.safe_content(b"postgresql+psycopg" + b"://operator:unexpected-real-value@localhost/runtime"))
        self.assertFalse(delivery.safe_content(b"-----BEGIN " + b"PRIVATE KEY-----"))
        self.assertTrue(delivery.safe_content(b"postgresql+psycopg://test:test@localhost/test"))
        self.assertTrue(delivery.safe_content(b"redis://default:${REDIS_PASSWORD}@redis/0"))

    def test_private_state_is_never_eligible(self):
        for filename in (".env", ".env.production", ".local-keys/key.txt", "customers.csv", "backup.sql", "backup.sql.gz", "customers.dump.xz", "local.db", "session.txt", "node_modules/package.json", "backups/last.sql.gz", "runtime.exe", "wheel.whl", "operator-gates.evidence.json"):
            self.assertFalse(delivery.allowed(Path(filename)), filename)
        for filename in (".env.example", "README.md", "apps/api/db/migrations/20261011_001_delivery_hardening.sql", "docs/api-contracts.json"):
            self.assertTrue(delivery.allowed(Path(filename)), filename)


class RestoreGuardTests(unittest.TestCase):
    def test_existing_restore_database_is_never_dropped(self):
        bash = Path("C:/Program Files/Git/bin/bash.exe") if sys.platform == "win32" else Path(shutil.which("bash") or "")
        if not bash.is_file():
            self.skipTest("POSIX bash required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "psql").write_text("#!/bin/bash\ncase \"$*\" in *datname*) printf '1\\n';; *COPY*) printf '{}\\n';; *) printf 'fixture\\n';; esac\n")
            (root / "python3").write_text("#!/bin/bash\nprintf 'fixture 1 digest\\n'\n")
            for name in ("createdb", "dropdb"):
                (root / name).write_text("#!/bin/bash\nprintf 'called' > \"$UNSAFE_CALL_MARKER\"\nexit 1\n")
            for name in ("psql", "python3", "createdb", "dropdb"):
                (root / name).chmod(0o755)
            marker = root / "unsafe-call"
            environment = {**os.environ, "PATH": str(root) + os.pathsep + os.environ.get("PATH", ""),
                           "PGHOST": "127.0.0.1", "PGPORT": "5432", "PGUSER": "fixture", "PGPASSWORD": "test",
                           "SOURCE_DATABASE": "fixture_source", "RESTORE_DATABASE": "fixture_restore", "UNSAFE_CALL_MARKER": str(marker)}
            result = subprocess.run([str(bash), str(ROOT / "scripts/ci-restore-drill.sh")], env=environment, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Restore target already exists", result.stderr)
            self.assertFalse(marker.exists(), "An existing database must not be created over or dropped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
