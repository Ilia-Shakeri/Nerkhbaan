from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ["DEBUG"] = "false"

from app.pricing.budgets import RedisRequestBudget
from app.pricing.models import RequestPurpose
from app.pricing.registry import PROVIDERS


class _BudgetClient:
    def __init__(self) -> None:
        self.keys: list[str] = []
        self.arguments: list[int] = []

    async def ttl(self, _key: str) -> int:
        return -2

    async def eval(self, _script: str, count: int, *values: object) -> list[int]:
        self.keys = [str(value) for value in values[:count]]
        self.arguments = [int(value) for value in values[count:]]
        return [1, 1, 0]


class _BudgetStore:
    def __init__(self) -> None:
        self.client_instance = _BudgetClient()

    def client(self) -> _BudgetClient:
        return self.client_instance


class FallbackBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_refresh_uses_bounded_provider_budget(self) -> None:
        store = _BudgetStore()
        provider = PROVIDERS["tetherland_usdt"]

        with patch("app.pricing.budgets.time.time", return_value=1_700_000_000):
            decision = await RedisRequestBudget(store=store).consume(
                provider,
                RequestPurpose.FALLBACK,
            )

        self.assertTrue(decision.allowed)
        self.assertFalse(any(":fallback:day:" in key for key in store.client_instance.keys))
        day_key_index = next(
            index
            for index, key in enumerate(store.client_instance.keys)
            if key.endswith(":all:day:19675")
        )
        self.assertEqual(
            store.client_instance.arguments[day_key_index * 2],
            provider.budget.requests_per_day
            - provider.budget.reserved_anomaly_requests
            - provider.budget.reserved_fallback_requests,
        )


if __name__ == "__main__":
    unittest.main()
