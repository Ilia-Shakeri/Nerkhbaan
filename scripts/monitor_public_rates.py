"""Record public rate coverage and source times without changing production."""
import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import time
from urllib.request import urlopen

BASE = "https://nerkhbaan.ir"
PATHS = {
    "ready": "/api/health/ready",
    "prices": "/api/prices",
    "references": "/api/prices/references?timeframe=24h",
}


def get_json(path: str) -> dict:
    with urlopen(BASE + path, timeout=20) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Public response exceeds probe limit")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("Expected a response object")
    return result


def sample() -> dict:
    record = {"checked_at": datetime.now(UTC).isoformat(), "errors": {}}
    for label, path in PATHS.items():
        try:
            data = get_json(path)
            if label == "ready":
                record[label] = {key: data.get(key) for key in
                                 ("ready", "release_version", "pricing_refresh", "migration_version")}
            elif label == "prices":
                record[label] = {
                    "refreshed_at": data["refreshed_at"],
                    "rights_revision": data["rights_revision"],
                    "assets": [
                        {key: asset.get(key) for key in
                         ("asset", "price_usd", "price_toman", "usd_status", "toman_status",
                          "usd_observed_at", "toman_observed_at", "source_usd", "source_toman")}
                        for asset in data["assets"]
                    ],
                }
            else:
                record[label] = [
                    {"instrument": item["current"]["instrument_id"], "status": item["status"],
                     "price": item["current"].get("price"), "as_of": item["current"].get("observed_at"),
                     "age_seconds": item["current"].get("age_seconds"), "history": item["history_status"]}
                    for item in data["references"]
                ]
        except (OSError, AttributeError, TypeError, ValueError, KeyError) as exc:
            record["errors"][label] = type(exc).__name__
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=97)
    parser.add_argument("--interval-seconds", type=int, default=900)
    args = parser.parse_args()
    if not 1 <= args.samples <= 289 or not 300 <= args.interval_seconds <= 3600:
        parser.error("Use 1–289 samples at intervals of 300–3600 seconds")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        next_at = time.monotonic()
        for index in range(args.samples):
            if index:
                time.sleep(max(0, next_at - time.monotonic()))
            row = sample()
            row.update(sample=index + 1, planned_samples=args.samples)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            next_at = max(next_at + args.interval_seconds, time.monotonic())


if __name__ == "__main__":
    main()
