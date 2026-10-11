"""Export the current API schema and route index from the application."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.environ["JWT_SECRET_KEY"] = "schema-export-key-not-for-runtime-00000000000000"
os.environ["DATABASE_URL"] = "postgresql+psycopg://schema:schema@127.0.0.1:5432/schema"
os.environ["REDIS_URL"] = ""
os.environ["PRICING_REQUIRE_PROVIDER_KEYS"] = "false"

from app.main import app


def export() -> None:
    schema = app.openapi()
    destination = ROOT / "docs" / "api-contracts.json"
    destination.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = ["# API Route Index", "", "Generated from the current application. Regenerate with `python scripts/export_api_contracts.py`.", "", f"Release: `{schema['info']['version']}`. Full schemas: [api-contracts.json](api-contracts.json).", "", "| Method | Path | Request | Success |", "| --- | --- | --- | --- |"]
    for path, methods in sorted(schema["paths"].items()):
        for method, operation in sorted(methods.items()):
            request = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            request_name = request.get("$ref", "").rsplit("/", 1)[-1] or (request.get("type", "—"))
            success = ", ".join(code for code in operation.get("responses", {}) if code.startswith("2"))
            rows.append(f"| {method.upper()} | `{path}` | `{request_name}` | {success} |")
    (ROOT / "docs" / "api-route-index.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"API_CONTRACTS_EXPORTED paths={len(schema['paths'])}")


if __name__ == "__main__":
    export()
