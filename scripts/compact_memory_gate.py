"""Assess shared-host memory from a rendered plan and a read-only host receipt.

This is a memory gate only: disk, image, network, TLS and deployment gates remain.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


MIB = 1024 * 1024
RESERVE = 1024 * MIB
STEADY = ("postgres", "redis", "backend", "frontend", "admin-frontend",
          "edge", "price-feed-pull", "db-backup")
SINGLE_STEADY = ("postgres", "redis", "backend", "web", "price-feed-pull", "db-backup")


def assess(plan: dict, receipt: dict, *, single_instance=False, downtime_accepted=False) -> dict:
    if single_instance != downtime_accepted:
        raise ValueError("Single-instance mode requires explicit upgrade downtime acceptance")
    services = plan["services"]
    names = SINGLE_STEADY if single_instance else STEADY
    replicas = 1 if single_instance else 2
    if set(services) != {*names, "migrate"}:
        raise ValueError("Only the reviewed compact services may be enabled")
    if services["backend"]["deploy"].get("replicas") != replicas:
        raise ValueError("The rendered backend count does not match the selected mode")
    caps = {}
    for name in (*names, "migrate"):
        if name != "backend" and services[name]["deploy"].get("replicas", 1) != 1:
            raise ValueError("An unreviewed extra service replica is enabled")
        value = services[name]["deploy"]["resources"]["limits"]["memory"]
        if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
            raise ValueError("A rendered positive byte limit is required: " + name)
        caps[name] = int(value)
    # The ordinary updater and the account tests require two backend replicas.
    steady = sum(caps[name] * (replicas if name == "backend" else 1) for name in names)
    startup = caps["postgres"] + caps["redis"] + caps["migrate"]
    # Keep room for the guarded updater's replacement API or a migration while
    # existing services remain running. Do not spend the host reserve on this.
    maintenance = (steady - caps["backend"] + max(caps["backend"], caps["migrate"])) if single_instance else (
        steady + max(caps["backend"], caps["migrate"]))
    gateway_growth = 32 * MIB if single_instance else 0
    before, after = receipt["before"], receipt["after"]
    samples = receipt["samples"]
    backups = receipt["backup_check"]
    if not receipt.get("read_only") or not before.get("complete") or not after.get("complete"):
        raise ValueError("Incomplete read-only host inventory")
    if not before.get("rows") or before["rows"] != after["rows"]:
        raise ValueError("Existing container identity changed")
    if len(samples) < 13 or not backups or not all(
        item.get("present") and item.get("matches_yesterday") for item in backups.values()
    ):
        raise ValueError("Missing host samples or checked backup preservation")
    from datetime import datetime
    clocks = [datetime.fromisoformat(item["time"]) for item in samples]
    if any(b <= a for a, b in zip(clocks, clocks[1:])) or (clocks[-1] - clocks[0]).total_seconds() < 60:
        raise ValueError("Host memory samples must span at least one minute")
    values = [item["memory_kib"]["MemAvailable"] for item in samples]
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
        raise ValueError("Invalid available-memory reading")
    available = min(values) * 1024
    required = max(steady, startup, maintenance) + RESERVE + gateway_growth
    return {"steady_limit_bytes": steady, "startup_limit_bytes": startup,
            "maintenance_limit_bytes": maintenance,
            "api_replicas": replicas, "upgrade_downtime_accepted": downtime_accepted,
            "gateway_growth_bytes": gateway_growth,
            "host_reserve_bytes": RESERVE, "minimum_available_bytes": available,
            "required_available_bytes": required,
            "memory_gate_passed": available >= required,
            "shortfall_bytes": max(0, required - available),
            "scope": "Historical sampled memory only; refresh before deployment",
            "deployment_accepted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--single-instance", action="store_true")
    parser.add_argument("--accept-upgrade-downtime", action="store_true")
    args = parser.parse_args()
    result = assess(json.loads(args.plan.read_text(encoding="utf8")),
                    json.loads(args.receipt.read_text(encoding="utf8")),
                    single_instance=args.single_instance,
                    downtime_accepted=args.accept_upgrade_downtime)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["memory_gate_passed"] else 2)
