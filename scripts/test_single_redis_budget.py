import unittest
from check_single_compose import validate_redis_headroom


class RedisBudgetTests(unittest.TestCase):
    def service(self, value):
        return {"environment": {"REDIS_MAXMEMORY": value}, "deploy": {"resources": {"limits": {"memory": 48 * 1024**2}}}}

    def test_data_cap_keeps_runtime_reserve(self):
        validate_redis_headroom(self.service("24mb"))

    def test_data_cap_must_not_consume_container_budget(self):
        for value in ("25mb", "48mb", "384mb"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_redis_headroom(self.service(value))

    def test_unbounded_or_ambiguous_capacity_is_rejected(self):
        for value in ("", "0", "0mb", "-1mb", "24", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_redis_headroom(self.service(value))


if __name__ == "__main__":
    unittest.main()
