"""Report source keys and history gaps without making network or database calls."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.environ.setdefault("JWT_SECRET_KEY", "provider-plan-local-not-for-runtime-00000000000000")

from app.config import Settings
from app.pricing.instruments import INSTRUMENTS
from app.pricing.registry import PROVIDERS


def plan(config: object) -> dict:
    prefixes = ("wallgold_", "bitpin_", "nobitex_", "wallex_", "tetherland_", "persian_toolbox_",
                "servix_", "navasan_", "tala_", "nerkh_io_", "alanchand_")
    routes = [provider for provider in PROVIDERS.values() if provider.provider_id.startswith(prefixes)]
    rows = []
    for provider in routes:
        key_names = [provider.api_key_setting] if provider.api_key_setting else []
        if provider.provider_id.startswith("nerkh_io_"):
            key_names = ["nerkh_io_bearer_token", "nerkh_io_api_key"]
        rows.append({
            "provider_id": provider.provider_id, "instrument_id": provider.instrument_id,
            "enabled_by_default_catalogue": provider.enabled,
            "configuration_present": provider.configured(config),
            "key_variables": [name.upper() for name in key_names],
            "key_present": any(bool(getattr(config, name, None)) for name in key_names) if key_names else None,
            "missing_contract_variables": [name.upper() for name in provider.required_settings if not getattr(config, name, None)],
            "history_registered": bool(provider.history_url and provider.history_parser_id),
            "catalogue_budget": {"requests_per_day": provider.budget.requests_per_day,
                                 "minimum_interval_seconds": provider.budget.minimum_interval_seconds},
            "scope": "catalogue_only_not_a_price_or_rights_proof",
        })
    covered = {row["instrument_id"] for row in rows if row["history_registered"]}
    return {
        "network_requests": 0, "database_or_redis_connections": 0, "production_changed": False,
        "budget_scope": "catalogue_only", "effective_runtime_budget": "unknown_not_read",
        "account_quota_verified": False,
        "servix_budget": {"catalogue_daily_sum": sum(p.budget.requests_per_day for p in routes if p.source_family == "servix"),
                          "runtime_daily_sum": None,
                          "activation_gate": "read_effective_database_and_operational_budgets_before_activation"},
        "routes": rows, "instruments_without_iranian_history_route": sorted(set(INSTRUMENTS)-covered),
        "candidate_not_integrated": {"BRSAPI_API_KEY": "Commodity plan candidate; troy-ounce and account usage proof still required"},
        "notes": ["Registration is not verified coverage", "TALA and Alanchand trial keys are not permanent free production plans",
                  "Servix catalogue defaults total 42 calls/day; stored budgets and overrides may differ and must be read before activation",
                  "Source freshness limits stay unchanged; no account-level quota or rights verification was performed"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.iranian-providers.local")
    args = parser.parse_args()
    config = Settings(_env_file=args.env_file)
    print(json.dumps(plan(config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
