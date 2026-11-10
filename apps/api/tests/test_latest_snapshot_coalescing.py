from __future__ import annotations

import asyncio
import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "snapshot-sharing-test-not-runtime-000000000000000")

from app.pricing.history import InternalPriceHistory


class LatestSnapshotSharingTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_readers_share_work_but_not_results_or_completed_prices(self):
        history = InternalPriceHistory()
        started, release = threading.Event(), threading.Event()
        calls = []

        def query():
            calls.append(len(calls) + 1)
            started.set()
            if not release.wait(3):
                raise RuntimeError("Test release missing")
            return {"BTC_USD": {"id": len(calls), "source_summary": {"provider_ids": ["approved"]}}}

        with patch.object(history, "_query_latest_all", side_effect=query), patch(
            "app.pricing.history.rights.revision", return_value="same-permissions"
        ):
            tasks = [asyncio.create_task(history.latest_all()) for _ in range(100)]
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                tasks[0].cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await tasks[0]
                release.set()
                results = await asyncio.gather(*tasks[1:])
                self.assertEqual(calls, [1])
                results[0]["BTC_USD"]["source_summary"]["provider_ids"].clear()
                self.assertEqual(results[1]["BTC_USD"]["source_summary"]["provider_ids"], ["approved"])
                self.assertEqual((await history.latest_all())["BTC_USD"]["id"], 2)
                self.assertEqual(calls, [1, 2])
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
        self.assertFalse(history._latest_reads)

    async def test_changed_permissions_do_not_join_or_publish_an_old_read(self):
        history = InternalPriceHistory()
        started, release = threading.Event(), threading.Event()
        revision = ["before"]
        calls = []

        def query():
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise RuntimeError("Test release missing")
                return {"old": {"id": 1}}
            return {"new": {"id": 2}}

        with patch.object(history, "_query_latest_all", side_effect=query), patch(
            "app.pricing.history.rights.revision", side_effect=lambda: revision[0]
        ):
            old = asyncio.create_task(history.latest_all())
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                revision[0] = "after"
                self.assertEqual(await history.latest_all(), {"new": {"id": 2}})
                release.set()
                self.assertEqual(await old, {})
                self.assertEqual(calls, [1, 2])
            finally:
                release.set()
                await asyncio.gather(old, return_exceptions=True)

    async def test_failure_is_shared_and_the_next_request_retries(self):
        history = InternalPriceHistory()
        started, release = threading.Event(), threading.Event()
        calls = []

        def query():
            calls.append(1)
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise RuntimeError("Test release missing")
                raise RuntimeError("Owned test database failure")
            return {"recovered": {"id": 3}}

        with patch.object(history, "_query_latest_all", side_effect=query), patch(
            "app.pricing.history.rights.revision", return_value="same-permissions"
        ):
            tasks = [asyncio.create_task(history.latest_all()) for _ in range(20)]
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                release.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                self.assertTrue(all(isinstance(item, RuntimeError) for item in results))
                self.assertEqual(len(calls), 1)
                self.assertEqual(await history.latest_all(), {"recovered": {"id": 3}})
                self.assertEqual(len(calls), 2)
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
