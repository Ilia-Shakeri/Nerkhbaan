"""Prepare or clean only a run-owned schema on an explicit loopback test database."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "scripts"))
from browser_fixture_database import align_owned_json_types, cleanup, prepare


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--align-json-types", action="store_true", help="Align PostgreSQL JSONB only in the explicitly owned fixture schema")
    arguments = parser.parse_args()
    if arguments.cleanup:
        if arguments.align_json_types:
            parser.error("--cleanup cannot also align types")
        if not arguments.schema:
            parser.error("--cleanup requires the exact generated --schema")
        cleanup(arguments.schema)
        print("BROWSER_FIXTURE_SCHEMA_REMOVED")
    else:
        schema, engine, _async_engine = prepare(arguments.schema)
        aligned = align_owned_json_types(schema, engine) if arguments.align_json_types else 0
        engine.dispose()
        print(json.dumps({"schema": schema, "kind": "postgresql-orm-fixture", "migration_proof": False, "fixture_json_columns_aligned": aligned}))
