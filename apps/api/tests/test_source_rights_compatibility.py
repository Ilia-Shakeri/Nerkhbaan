from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "compatibility-rights-test-secret-not-for-runtime-0000")

from app.pricing import rights
from app.pricing.compatibility import LegacyPricingAdapter
from app.pricing.models import CanonicalQuote, CanonicalStatus
from app.schemas import PriceHistoryResponse, PricesResponse


USD_SOURCE = "gold_api_free_xau"
LOCAL_SOURCE = "reviewed_local_fixture"


def _grant(label, *permissions):
    now = datetime.now(UTC)
    return {"checked_at": (now - timedelta(days=1)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "permissions": list(permissions or ("display", "history", "store")),
            "evidence_ref": "https://terms.fixture.invalid/",
            "attribution": {"label": label, "url": f"https://{label.lower()}.fixture.invalid/"}}


class SourceRightsCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(patch.object(rights.settings, "pricing_rights_enforced", True))
        self.grants = {USD_SOURCE: _grant("Global"), LOCAL_SOURCE: _grant("Local")}
        self.enterContext(patch.object(rights, "grants", side_effect=lambda: self.grants))
        self.service = SimpleNamespace(get_all_canonical=AsyncMock(return_value={}),
                                       canonical_history=AsyncMock(), store=SimpleNamespace(recent_canonical=AsyncMock(return_value=[])))
        self.adapter = LegacyPricingAdapter(self.service)

    @staticmethod
    def quote(provider=USD_SOURCE, instrument="XAU_USD_OZ", price=2080):
        now = datetime.now(UTC)
        return CanonicalQuote.create(instrument_id=instrument, price=price, status=CanonicalStatus.LIVE,
            primary_quote_id=1, verification_quote_ids=[],
            source_summary={"primary_provider_id": provider, "provider_ids": [provider], "derived": False},
            observed_at=now, canonical_at=now, valid_until=now + timedelta(seconds=60),
            stale_at=now + timedelta(seconds=120), expires_at=now + timedelta(seconds=240),
            is_persisted=True, decision_reason="fixture")

    def histories(self):
        return {asset: [] for asset in ("gold", "silver", "usdt", "btc")}

    async def test_short_history_requires_history_right_and_current_candidate_proof(self):
        allowed = self.quote()
        display_only = self.quote(LOCAL_SOURCE, price=3000)
        self.grants[LOCAL_SOURCE] = _grant("Local", "display")
        bad_candidate = self.quote(price=4000)
        bad_candidate.candidate_provider_id, bad_candidate.candidate_price = "unreviewed_source", 9999
        self.service.store.recent_canonical.side_effect = [[bad_candidate, display_only, allowed], []]
        points = await self.adapter._short_history("XAU_USD_OZ", "GOLD_18K_TOMAN_GRAM")
        self.assertEqual([point["value_usd"] for point in points], [2080])
        self.assertTrue(all(point["value_toman"] is None for point in points))

    async def test_revocation_during_input_loading_clears_all_already_read_history(self):
        self.adapter._short_history = AsyncMock(return_value=[{"timestamp": "2026-10-17T00:00:00Z", "value_usd": 2080}])

        async def current():
            self.grants.clear()
            return {}

        self.service.get_all_canonical.side_effect = current
        _quotes, histories = await self.adapter._load_price_inputs()
        self.assertTrue(all(not points for points in histories.values()))

    async def test_coalesced_snapshot_is_rechecked_after_permission_withdrawal(self):
        quote = self.quote()
        self.grants.clear()
        result = await self.adapter._build_prices({quote.instrument_id: quote}, self.histories())
        gold = next(asset for asset in result["assets"] if asset["asset"] == "gold")
        self.assertIsNone(gold["price_usd"])
        self.assertEqual(result["rights_revision"], rights.revision())

    async def test_history_loaded_before_revocation_cannot_leak_through_coalesced_response(self):
        quote = self.quote()
        histories = self.histories()
        histories["gold"] = [{"timestamp": "2026-10-17T00:00:00Z", "value_usd": 2080, "value_toman": None}]
        self.grants.clear()
        result = await self.adapter._build_prices({quote.instrument_id: quote}, histories)
        gold = next(asset for asset in result["assets"] if asset["asset"] == "gold")
        self.assertEqual(gold["history"], [])

    async def test_paired_history_revision_change_discards_values_and_all_credits(self):
        source = SimpleNamespace(points=[{"timestamp": "2026-10-17T00:00:00Z", "value": 2080}],
                                 status="complete", attributions=[{"label": "Global", "url": "https://global.fixture.invalid/"}])

        async def pair(*_args):
            self.grants.clear()
            return source, source

        self.adapter._paired_history = pair
        result = await self.adapter.get_history("gold", "24h")
        self.assertEqual(result["points"], [])
        self.assertEqual(result["usd_attributions"], [])
        self.assertEqual(result["toman_attributions"], [])
        self.assertEqual(result["attributions"], [])
        self.assertEqual(result["status"], "partial")

    async def test_history_response_preserves_distinct_leg_credits_and_actual_union(self):
        global_credit = {"label": "Global", "url": "https://global.fixture.invalid/"}
        local_credit = {"label": "Local", "url": "https://local.fixture.invalid/"}
        usd = SimpleNamespace(points=[{"timestamp": "2026-10-17T00:00:00Z", "value": 2080}],
                              status="complete", attributions=[global_credit])
        toman = SimpleNamespace(points=[{"timestamp": "2026-10-17T00:00:00Z", "value": 10000000}],
                                status="complete", attributions=[local_credit, global_credit])
        self.adapter._paired_history = AsyncMock(return_value=(usd, toman))
        raw = await self.adapter.get_history("gold", "24h")
        result = PriceHistoryResponse.model_validate(raw).model_dump()
        self.assertEqual(result["usd_attributions"], [global_credit])
        self.assertEqual(result["toman_attributions"], [local_credit, global_credit])
        self.assertEqual({(item["label"], item["url"]) for item in result["attributions"]},
                         {("Global", global_credit["url"]), ("Local", local_credit["url"])})
        self.assertEqual(result["points"][0]["value_toman"], 10000000)

    async def test_internal_proof_is_copied_for_alerts_and_never_exported_as_public_price_fields(self):
        quote = self.quote()
        raw = await self.adapter._build_prices({quote.instrument_id: quote}, self.histories())
        gold = next(asset for asset in raw["assets"] if asset["asset"] == "gold")
        self.assertEqual(gold["_usd_rights_source_summary"], quote.source_summary)
        quote.source_summary["provider_ids"].append("later_mutation")
        self.assertEqual(gold["_usd_rights_source_summary"]["provider_ids"], [USD_SOURCE])
        public = PricesResponse.model_validate(raw).model_dump()
        public_gold = next(asset for asset in public["assets"] if asset["asset"] == "gold")
        self.assertNotIn("_usd_rights_source_summary", public_gold)
        self.assertEqual(public_gold["usd_attributions"][0]["label"], "Global")


if __name__ == "__main__":
    unittest.main()
