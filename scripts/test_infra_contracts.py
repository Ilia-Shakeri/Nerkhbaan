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
        mirror = ROOT / "apps/api/app/telegram_price_parser.py"
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
    def test_history_never_contacts_source_or_changes_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)/"state.json"
            state.write_text('{"old":{"last_timestamp":123}}')
            before=state.read_bytes()
            with patch.object(worker,"STATE_FILE",state),patch.object(worker,"get_json") as get,patch.object(worker,"send") as send:
                self.assertEqual(worker.backfill()["status"],"unavailable")
            get.assert_not_called()
            send.assert_not_called()
            self.assertEqual(state.read_bytes(),before)

    def test_live_preserves_source_time_and_uses_exact_approved_routes(self):
        stamp=datetime.now(UTC)-timedelta(seconds=120)
        prices={"XAU":4000,"XAG":50,"BTC":90000}
        def get(url):
            symbol=url.rsplit("/",1)[1]
            return {"symbol":symbol,"currency":"USD","price":prices[symbol],"updatedAt":stamp.isoformat()}
        with patch.object(worker,"get_json",side_effect=get),patch.object(worker,"send") as send:
            worker.live()
        self.assertEqual(len(send.call_args.args[0]),3)
        self.assertTrue(all(datetime.fromisoformat(q["observed_at"])==stamp for q in send.call_args.args[0]))

    def test_stale_live_is_not_sent(self):
        stale=(datetime.now(UTC)-timedelta(hours=1)).isoformat()
        with patch.object(worker,"get_json",side_effect=lambda url:{"symbol":url.rsplit("/",1)[1],"currency":"USD","price":4000,"updatedAt":stale}),patch.object(worker,"send") as send:
            with self.assertRaises(RuntimeError):
                worker.live()
        send.assert_not_called()

    def test_live_run_has_no_hidden_historical_request(self):
        with patch.object(worker,"live") as live,patch.object(worker,"backfill") as history:
            worker.run()
        live.assert_called_once()
        history.assert_not_called()

    def test_send_requires_actual_published_acknowledgement(self):
        quote=worker.gold_quote({"symbol":"BTC","currency":"USD","price":90000,"updatedAt":datetime.now(UTC).isoformat()},"gold_api_free_btc")
        response=MagicMock()
        response.__enter__.return_value=response
        response.status=202
        response.geturl.return_value="https://fixture.invalid/worker/ingest"
        response.read.return_value=json.dumps({"accepted":1,"published":0,"ignored":1}).encode()
        opener=MagicMock()
        opener.open.return_value=response
        with patch.object(worker,"ENDPOINT","https://fixture.invalid/worker"),patch.object(worker,"SECRET","x"*48),patch.object(worker,"build_opener",return_value=opener):
            with self.assertRaisesRegex(RuntimeError,"publish every"):
                worker.send([quote])
            response.read.return_value=json.dumps({"accepted":1,"published":1}).encode()
            worker.send([quote])


class PublicFeedTests(unittest.TestCase):
    def test_source_time_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            feed._time("2026-10-11T00:00:00", "fixture", datetime(2026, 10, 11, tzinfo=UTC), timedelta(seconds=600))
    def test_ten_minute_bound(self):
        now = datetime(2026, 10, 11, tzinfo=UTC)
        metals = {"symbol": "XAG", "currency": "USD", "price": 30, "updatedAt": (now - timedelta(seconds=601)).isoformat()}
        crypto = {"symbol": "BTC", "currency": "USD", "price": 60000, "updatedAt": now.isoformat()}
        gold = {"symbol": "XAU", "currency": "USD", "price": 4000, "updatedAt": now.isoformat()}
        with self.assertRaises(ValueError):
            feed.build_feed(metals, crypto, now, gold=gold)
        metals["updatedAt"] = (now - timedelta(seconds=600)).isoformat()
        self.assertEqual(len(feed.build_feed(metals, crypto, now, gold=gold)["quotes"]), 3)


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
