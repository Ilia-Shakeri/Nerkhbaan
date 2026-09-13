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


if __name__ == "__main__":
    unittest.main()
