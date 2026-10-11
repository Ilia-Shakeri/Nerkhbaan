from __future__ import annotations

import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "build-price-feed.py"
SPEC = importlib.util.spec_from_file_location("build_price_feed", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Price feed builder could not be loaded")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PriceFeedBuilderTests(unittest.TestCase):
    def test_partial_feed_preserves_crypto_when_silver_stale(self):
        now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
        source_time = int((now-timedelta(seconds=50)).timestamp())
        crypto = {"bitcoin": {"usd": 77000, "last_updated_at": source_time},
                  "tether": {"usd": 1, "last_updated_at": source_time}}
        feed = MODULE.build_partial_feed({"symbol": "XAG", "currency": "USD", "price": 50,
                                          "updatedAt": (now-timedelta(hours=2)).isoformat()}, crypto, now)
        self.assertEqual(feed["feed_version"], 2)
        self.assertEqual([row["instrument_id"] for row in feed["quotes"]], ["BTC_USD", "USDT_USD"])
        self.assertTrue(all(datetime.fromisoformat(row["observed_at"]).timestamp() == source_time
                            for row in feed["quotes"]))
        self.assertEqual(feed["omitted"][0]["instrument_id"], "XAG_USD_OZ")

    def test_partial_feed_one_missing_crypto_does_not_drop_other(self):
        now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
        feed = MODULE.build_partial_feed(None, {"bitcoin": {"usd": 77000,
                                             "last_updated_at": int(now.timestamp())}}, now)
        self.assertEqual([row["instrument_id"] for row in feed["quotes"]], ["BTC_USD"])

    def test_partial_feed_no_valid_quotes_fails_instead_of_fresh_empty(self):
        with self.assertRaisesRegex(ValueError, "No validated fresh"):
            MODULE.build_partial_feed(None, None)

    def test_partial_gold_is_separate_usd_ounce_route_no_karat(self):
        now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
        observed = now-timedelta(seconds=22)
        feed = MODULE.build_partial_feed(None, None, now, gold={"symbol": "XAU", "currency": "USD",
                                           "price": 4000, "updatedAt": observed.isoformat()})
        self.assertEqual(len(feed["quotes"]), 1)
        self.assertEqual(feed["quotes"][0]["instrument_id"], "XAU_USD_OZ")
        self.assertEqual(feed["quotes"][0]["observed_at"], observed.isoformat())
        self.assertEqual(feed["quotes"][0]["price"], "4000")

    def test_partial_gold_wrong_currency_symbol_or_time_is_omitted(self):
        now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
        for wrong in ({"symbol": "XAG"}, {"currency": "EUR"}, {"updatedAt": None},
                      {"updatedAt": (now-timedelta(minutes=11)).isoformat()}):
            gold = {"symbol": "XAU", "currency": "USD", "price": 4000, "updatedAt": now.isoformat(), **wrong}
            with self.assertRaises(ValueError):
                MODULE.build_partial_feed(None, None, now, gold=gold)

    def test_builds_exact_three_route_feed(self) -> None:
        now = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
        feed = MODULE.build_feed(
            {
                "symbol": "XAG",
                "currency": "USD",
                "price": 64.6,
                "updatedAt": (now - timedelta(seconds=20)).isoformat(),
            },
            {
                "bitcoin": {"usd": 77000, "last_updated_at": int(now.timestamp())},
                "tether": {"usd": 0.999, "last_updated_at": int(now.timestamp())},
            },
            now,
        )

        self.assertEqual(feed["feed_version"], 1)
        self.assertEqual(
            [item["provider_id"] for item in feed["quotes"]],
            ["gold_api_free_xag", "coingecko_btc", "coingecko_usdt"],
        )

    def test_rejects_stale_or_wrong_unit_silver(self) -> None:
        now = datetime(2026, 9, 13, 8, 0, tzinfo=UTC)
        crypto = {
            "bitcoin": {"usd": 77000, "last_updated_at": int(now.timestamp())},
            "tether": {"usd": 0.999, "last_updated_at": int(now.timestamp())},
        }
        with self.assertRaisesRegex(ValueError, "currency changed"):
            MODULE.build_feed(
                {
                    "symbol": "XAG",
                    "currency": "EUR",
                    "price": 64.6,
                    "updatedAt": now.isoformat(),
                },
                crypto,
                now,
            )
        with self.assertRaisesRegex(ValueError, "safe time window"):
            MODULE.build_feed(
                {
                    "symbol": "XAG",
                    "currency": "USD",
                    "price": 64.6,
                    "updatedAt": (now - timedelta(hours=1)).isoformat(),
                },
                crypto,
                now,
            )

    def test_builds_fresh_xaus_silver_fallback(self) -> None:
        now = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
        feed = MODULE.build_feed(
            {
                "silver_usd_oz": 66.37,
                "data_state": {
                    "status": "fresh",
                    "as_of": (now - timedelta(seconds=10)).isoformat(),
                },
            },
            {
                "bitcoin": {"usd": 77000, "last_updated_at": int(now.timestamp())},
                "tether": {"usd": 0.999, "last_updated_at": int(now.timestamp())},
            },
            now,
            silver_provider="xaus_xag",
        )
        self.assertEqual(feed["quotes"][0]["provider_id"], "xaus_xag")
        self.assertEqual(feed["quotes"][0]["price"], "66.37")


if __name__ == "__main__":
    unittest.main()
