from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from compact_memory_gate import MIB, STEADY, assess


class CompactMemoryGateTests(unittest.TestCase):
    def setUp(self):
        limits = dict(zip((*STEADY, "migrate"), (384, 64, 224, 32, 32, 96, 32, 64, 256)))
        self.plan = {"services": {name: {"deploy": {"resources": {"limits": {"memory": value * MIB}}}}
                                  for name, value in limits.items()}}
        self.plan["services"]["backend"]["deploy"]["replicas"] = 2
        now = datetime(2026, 11, 10, tzinfo=UTC)
        self.receipt = {"read_only": True, "before": {"complete": True, "rows": [{"id": "existing"}]},
                        "after": {"complete": True, "rows": [{"id": "existing"}]},
                        "samples": [{"time": (now + timedelta(seconds=i * 5)).isoformat(),
                                     "memory_kib": {"MemAvailable": 3000 * 1024}} for i in range(13)],
                        "backup_check": {"owned": {"present": True, "matches_yesterday": True}}}

    def test_two_apis_and_a_full_gib_of_reserve_are_counted(self):
        result = assess(self.plan, self.receipt)
        self.assertEqual(result["steady_limit_bytes"], 1152 * MIB)
        self.assertEqual(result["required_available_bytes"], 2432 * MIB)
        self.assertTrue(result["memory_gate_passed"])
        self.assertFalse(result["deployment_accepted"])

    def test_minimum_sample_controls_gate_not_last_or_average(self):
        self.receipt["samples"][0]["memory_kib"]["MemAvailable"] = 2000 * 1024
        result = assess(self.plan, self.receipt)
        self.assertFalse(result["memory_gate_passed"])
        self.assertEqual(result["shortfall_bytes"], 432 * MIB)

    def test_startup_peak_can_exceed_the_steady_plan(self):
        self.plan["services"]["migrate"]["deploy"]["resources"]["limits"]["memory"] = 2048 * MIB
        result = assess(self.plan, self.receipt)
        self.assertEqual(result["required_available_bytes"], (1152 + 2048 + 1024) * MIB)
        self.assertFalse(result["memory_gate_passed"])

    def test_preservation_and_complete_sampling_fail_closed(self):
        for change in (lambda r: r["after"].update(complete=False),
                       lambda r: r["after"]["rows"].append({"id": "replaced"}),
                       lambda r: r.update(samples=r["samples"][:12]),
                       lambda r: r["backup_check"]["owned"].update(matches_yesterday=False),
                       lambda r: r["samples"][5].update(time=r["samples"][4]["time"])):
            receipt = deepcopy(self.receipt)
            change(receipt)
            with self.assertRaises(ValueError):
                assess(self.plan, receipt)

    def test_unbounded_or_unrendered_limits_are_rejected(self):
        for value in (0, -1, None, True, "320M"):
            self.plan["services"]["postgres"]["deploy"]["resources"]["limits"]["memory"] = value
            with self.assertRaises(ValueError):
                assess(self.plan, self.receipt)

    def test_single_replica_is_not_a_way_to_pass_the_memory_gate(self):
        self.plan["services"]["backend"]["deploy"]["replicas"] = 1
        with self.assertRaises(ValueError):
            assess(self.plan, self.receipt)

    def test_extra_services_or_extra_replicas_are_not_ignored(self):
        plan = deepcopy(self.plan)
        plan["services"]["monitoring"] = {"deploy": {"resources": {"limits": {"memory": 1024 * MIB}}}}
        with self.assertRaises(ValueError):
            assess(plan, self.receipt)
        self.plan["services"]["redis"]["deploy"]["replicas"] = 2
        with self.assertRaises(ValueError):
            assess(self.plan, self.receipt)

    def single_plan(self):
        caps = {"postgres": 320, "redis": 48, "backend": 192, "web": 24,
                "price-feed-pull": 32, "db-backup": 48, "migrate": 192}
        return {"services": {name: {"deploy": {"replicas": 1,
                "resources": {"limits": {"memory": value * MIB}}}} for name, value in caps.items()}}

    def test_single_mode_keeps_a_gib_reserve_and_counts_gateway_growth(self):
        result = assess(self.single_plan(), self.receipt, single_instance=True, downtime_accepted=True)
        self.assertEqual(result["steady_limit_bytes"], 664 * MIB)
        self.assertEqual(result["maintenance_limit_bytes"], 664 * MIB)
        self.assertEqual(result["required_available_bytes"], 1720 * MIB)
        self.assertEqual(result["host_reserve_bytes"], 1024 * MIB)

    def test_one_instance_cannot_silently_relax_the_original_mode(self):
        for flags in ({}, {"single_instance": True}, {"downtime_accepted": True}):
            with self.assertRaises(ValueError):
                assess(self.single_plan(), self.receipt, **flags)

    def test_single_mode_counts_a_larger_migration_after_stopping_only_its_api(self):
        plan = self.single_plan()
        plan["services"]["migrate"]["deploy"]["resources"]["limits"]["memory"] = 512 * MIB
        result = assess(plan, self.receipt, single_instance=True, downtime_accepted=True)
        self.assertEqual(result["required_available_bytes"], (664 - 192 + 512 + 1024 + 32) * MIB)

    def test_cli_returns_failure_status_for_insufficient_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, receipt = Path(directory) / "plan.json", Path(directory) / "receipt.json"
            plan.write_text(json.dumps(self.plan), encoding="utf8")
            for available, status in ((3000, 0), (2000, 2)):
                for sample in self.receipt["samples"]:
                    sample["memory_kib"]["MemAvailable"] = available * 1024
                receipt.write_text(json.dumps(self.receipt), encoding="utf8")
                result = subprocess.run([sys.executable, str(Path(__file__).with_name("compact_memory_gate.py")),
                    "--plan", str(plan), "--receipt", str(receipt)], capture_output=True, text=True)
                self.assertEqual(result.returncode, status)
                self.assertEqual(json.loads(result.stdout)["memory_gate_passed"], status == 0)


if __name__ == "__main__":
    unittest.main()
