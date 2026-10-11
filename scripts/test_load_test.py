import asyncio
from pathlib import Path
import sys
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_test import measure, percentile


class LoadHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_contract_failure_is_not_success(self):
        def response(request):
            return httpx.Response(200, json={"ready": True} if request.url.path.endswith("ready") else {"assets": "invalid"})
        result = await measure("http://fixture", 4, 2, transport=httpx.MockTransport(response))
        self.assertEqual(result["requests"], 4)
        self.assertEqual(result["failures"], 4)
        self.assertFalse(result["passed"])

    async def test_http_failure_report_keeps_status(self):
        def response(request):
            return httpx.Response(200, json={"ready": True}) if request.url.path.endswith("ready") else httpx.Response(429, json={})
        result = await measure("http://fixture", 3, 2, transport=httpx.MockTransport(response))
        self.assertEqual(result["http_statuses"], {"429": 3})
        self.assertEqual(result["failures"], 3)
        self.assertFalse(result["passed"])

    async def test_duration_rate_and_worker_bound(self):
        active = maximum = 0
        async def response(request):
            nonlocal active, maximum
            if request.url.path.endswith("ready"):
                return httpx.Response(200, json={"ready": True})
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.03)
            active -= 1
            return httpx.Response(200, json={"assets": []})
        result = await measure("http://fixture", 1000000, 2, duration_seconds=0.55,
                               requests_per_second=10, transport=httpx.MockTransport(response))
        self.assertGreaterEqual(result["requests"], 5)
        self.assertLessEqual(result["requests"], 6)
        self.assertLessEqual(maximum, 2)
        self.assertTrue(result["passed"])

    def test_tail_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile(list(range(1, 11)), 0.95), 10)
        self.assertEqual(percentile([], 0.95), 0)

    async def test_slow_target_cannot_pass_requested_rate(self):
        async def response(request):
            if request.url.path.endswith("ready"):
                return httpx.Response(200, json={"ready": True})
            await asyncio.sleep(0.07)
            return httpx.Response(200, json={"assets": []})
        result = await measure("http://fixture", 1000, 1, duration_seconds=0.22,
                               requests_per_second=100, transport=httpx.MockTransport(response))
        self.assertEqual(result["failures"], 0)
        self.assertFalse(result["rate_passed"])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
