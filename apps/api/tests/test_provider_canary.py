from __future__ import annotations

import os
import io
import json
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-that-is-long-enough")
os.environ["DEBUG"] = "false"

from app.pricing.providers import ProviderCallFailure, ProviderQuoteCollector
from app.pricing.registry import ProviderDefinition
from scripts.provider_canary import main, probe_provider


class _ClientContext:
    async def __aenter__(self) -> "_ClientContext":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class ProviderCanaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_only_skips_before_configuration_or_client_creation(self) -> None:
        with patch.object(ProviderDefinition, "configured", side_effect=AssertionError("history is not a live capability")), \
             patch("scripts.provider_canary.httpx.AsyncClient") as client, \
             patch.object(ProviderQuoteCollector, "_request_payload", AsyncMock()) as request:
            row = await probe_provider("nerkhsanj_silver999_history")
        self.assertEqual((row["status"], row["reason"]), ("skipped", "history_only"))
        self.assertIs(row["history_only"], True)
        client.assert_not_called()
        request.assert_not_awaited()

    async def test_history_only_selection_does_not_fail_live_canary_exit_code(self) -> None:
        output = io.StringIO()
        with patch("scripts.provider_canary.sys.argv", ["provider_canary.py", "nerkhsanj_silver999_history"]), \
             patch("scripts.provider_canary.httpx.AsyncClient") as client, \
             patch("sys.stdout", output):
            result = await main()
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["providers"][0]["status"], "skipped")
        client.assert_not_called()

    async def test_unknown_provider_still_fails_without_network(self) -> None:
        output = io.StringIO()
        with patch("scripts.provider_canary.sys.argv", ["provider_canary.py", "unknown_fixture_provider"]), \
             patch("scripts.provider_canary.httpx.AsyncClient") as client, \
             patch("sys.stdout", output):
            result = await main()
        self.assertEqual(result, 1)
        row = json.loads(output.getvalue())["providers"][0]
        self.assertEqual((row["status"], row["reason"]), ("failed", "unknown_provider"))
        client.assert_not_called()

    async def test_canary_requires_successful_parse(self) -> None:
        request = AsyncMock(return_value=({"price": "100000"}, "application/json", 200))
        with patch.object(ProviderQuoteCollector, "_request_payload", request), patch(
            "scripts.provider_canary.httpx.AsyncClient", return_value=_ClientContext()
        ):
            row = await probe_provider("coinbase_btc_usd")

        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["http_status"], 200)
        self.assertNotIn("price", row)

    async def test_canary_fails_auth_response(self) -> None:
        request = AsyncMock(
            side_effect=ProviderCallFailure("http_error", "bad auth", http_status=401)
        )
        with patch.object(ProviderQuoteCollector, "_request_payload", request), patch(
            "scripts.provider_canary.httpx.AsyncClient", return_value=_ClientContext()
        ):
            row = await probe_provider("coinbase_btc_usd")

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["reason"], "http_error")


class ProviderPeerImpactTests(unittest.TestCase):
    def test_archive_cannot_hide_absence_of_live_peer_when_disabling_provider(self):
        from app.admin.routers.providers import _impact_preview

        live = {"provider_id": "owned_live", "asset": "silver", "region": "iran",
                "enabled": True, "role": "primary"}
        archive = {"provider_id": "owned_archive", "asset": "silver", "region": "iran",
                   "enabled": True, "history_only": True}
        warning = "No enabled peer provider is known for this market path"
        self.assertIn(warning, _impact_preview([live, archive], live, {"enabled": False})["warnings"])
        peer = {"provider_id": "owned_live_peer", "asset": "silver", "region": "iran", "enabled": True}
        self.assertNotIn(warning, _impact_preview([live, archive, peer], live, {"enabled": False})["warnings"])
