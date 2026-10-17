from __future__ import annotations

import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3]/"scripts/build-price-feed.py"
SPEC = importlib.util.spec_from_file_location("build_price_feed", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Price feed builder could not be loaded")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def observation(asset, now, **overrides):
    return {"symbol":asset,"currency":"USD","price":{"XAU":4000,"XAG":50,"BTC":90000}[asset],"updatedAt":now.isoformat(),**overrides}


class PriceFeedBuilderTests(unittest.TestCase):
    def test_partial_feed_preserves_real_bitcoin_when_silver_is_stale(self):
        now=datetime(2026,10,17,12,tzinfo=UTC);source_time=now-timedelta(seconds=50)
        value=MODULE.build_partial_feed(observation("XAG",now-timedelta(hours=2)),observation("BTC",source_time),now)
        self.assertEqual(value["feed_version"],3)
        self.assertEqual([row["instrument_id"] for row in value["quotes"]],["BTC_USD"])
        self.assertEqual(value["quotes"][0]["observed_at"],source_time.isoformat())
        self.assertNotIn("USDT_USD",[row["instrument_id"] for row in value["quotes"]])

    def test_missing_bitcoin_does_not_drop_healthy_silver(self):
        now=datetime(2026,10,17,12,tzinfo=UTC)
        value=MODULE.build_partial_feed(observation("XAG",now),None,now)
        self.assertEqual([row["instrument_id"] for row in value["quotes"]],["XAG_USD_OZ"])

    def test_no_valid_quotes_preserves_previous_feed(self):
        with self.assertRaisesRegex(ValueError,"No validated fresh"):
            MODULE.build_partial_feed(None,None)

    def test_gold_remains_ounce_observation_with_its_own_time(self):
        now=datetime(2026,10,17,12,tzinfo=UTC);observed=now-timedelta(seconds=22)
        value=MODULE.build_partial_feed(None,None,now,gold=observation("XAU",observed))
        self.assertEqual(len(value["quotes"]),1)
        quote=value["quotes"][0]
        self.assertEqual((quote["instrument_id"],quote["weight_unit"],quote["price"]),("XAU_USD_OZ","troy_ounce","4000"))
        self.assertEqual(quote["observed_at"],observed.isoformat())

    def test_wrong_currency_symbol_timestamp_and_nonfinite_price_are_omitted(self):
        now=datetime(2026,10,17,12,tzinfo=UTC)
        for wrong in ({"symbol":"XAG"},{"currency":"EUR"},{"currency":None},{"updatedAt":None},{"updatedAt":(now-timedelta(minutes=11)).isoformat()},{"updatedAt":now.replace(tzinfo=None).isoformat()},{"price":"NaN"},{"price":"Infinity"},{"price":True}):
            with self.subTest(wrong=wrong),self.assertRaises(ValueError):
                MODULE.build_partial_feed(None,None,now,gold=observation("XAU",now,**wrong))

    def test_complete_feed_has_exact_three_approved_routes_and_attribution(self):
        now=datetime(2026,10,17,12,tzinfo=UTC)
        value=MODULE.build_feed(observation("XAG",now),observation("BTC",now),now,gold=observation("XAU",now))
        self.assertEqual([quote["provider_id"] for quote in value["quotes"]],["gold_api_free_xag","gold_api_free_btc","gold_api_free_xau"])
        self.assertEqual(value["attributions"],[{"label":"Gold API","url":"https://gold-api.com/"}])
        self.assertEqual(value["audience"],"nerkhbaan-own-app")

    def test_complete_feed_requires_each_real_observation(self):
        now=datetime(2026,10,17,12,tzinfo=UTC)
        with self.assertRaisesRegex(ValueError,"three approved"):
            MODULE.build_feed(observation("XAG",now),observation("BTC",now),now)

    def test_unapproved_silver_fallback_is_rejected(self):
        now=datetime(2026,10,17,12,tzinfo=UTC)
        with self.assertRaisesRegex(ValueError,"not allowed"):
            MODULE.build_partial_feed(observation("XAG",now),observation("BTC",now),now,silver_provider="xaus_xag")


if __name__=="__main__":
    unittest.main()
