#!/usr/bin/env python3
"""Collect approved observations for the application through its private ingest route."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ENDPOINT = os.environ.get("NERKHBAAN_WORKER_ENDPOINT", "").rstrip("/")
SECRET = os.environ.get("NERKHBAAN_WORKER_SECRET", "")
STATE_FILE = Path(os.environ.get("NERKHBAAN_WORKER_STATE_FILE", "/var/lib/nerkhbaan-price-worker/history-complete"))
TIMEOUT = 20
MAX_RESPONSE_BYTES = 1_000_000
MAX_LIVE_AGE_SECONDS = 600
ATTRIBUTION = {"label": "Gold API", "url": "https://gold-api.com/"}
ROUTES = {
    "gold_api_free_xau": ("XAU", "XAU_USD_OZ", "troy_ounce", "500", "10000"),
    "gold_api_free_xag": ("XAG", "XAG_USD_OZ", "troy_ounce", "5", "500"),
    "gold_api_free_btc": ("BTC", "BTC_USD", "unit", "1000", "1000000"),
}
_ACTIONS = {"collect", "store", "display", "history", "derive", "own_app_transport", "external_processing", "relay"}
logger = logging.getLogger("price_worker")


def _time(value: object, label: str, now: datetime, maximum_age: timedelta) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed > now+timedelta(minutes=5) or now-parsed > maximum_age:
        raise ValueError(f"{label} is outside the safe time window")
    return parsed


def source_allowed(provider: str, action: str) -> bool:
    if provider not in ROUTES or action not in _ACTIONS:
        return False
    path = os.environ.get("PRICING_RIGHTS_MANIFEST_PATH", "")
    now = datetime.now(UTC)
    if not path:
        return (action in {"collect", "store", "display", "history", "derive", "own_app_transport"}
                and datetime(2026, 10, 17, tzinfo=UTC) <= now < datetime(2027, 1, 15, tzinfo=UTC))
    try:
        selected = Path(path)
        if not selected.is_absolute() or selected.stat().st_size > 262_144:
            return False
        manifest = json.loads(selected.read_text(encoding="utf-8"))
        if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1 or manifest.get("environment") != "production":
            return False
        grant = manifest["providers"][provider]
        checked = datetime.fromisoformat(grant["checked_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(grant["expires_at"].replace("Z", "+00:00"))
        evidence = urlsplit(grant["evidence_ref"])
        permissions = grant.get("permissions")
        hosts = grant.get("hosts")
        required = {action, "display"} if action == "history" else {action}
        return (checked.tzinfo is not None and expires.tzinfo is not None
                and checked <= now < expires and (expires-checked).total_seconds() <= 366*86400
                and evidence.scheme == "https" and bool(evidence.hostname) and not evidence.username and not evidence.password
                and isinstance(permissions, list) and bool(permissions) and all(isinstance(value, str) and value in _ACTIONS for value in permissions)
                and required <= set(permissions)
                and isinstance(hosts, list) and bool(hosts) and all(isinstance(host, str) and host for host in hosts)
                and "api.gold-api.com" in hosts)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


def _transport_allowed(provider: str) -> bool:
    return all(source_allowed(provider, action) for action in ("collect", "store", "own_app_transport"))


class _RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(url: str) -> object:
    provider = next((name for name, route in ROUTES.items() if url == f"https://api.gold-api.com/price/{route[0]}"), None)
    if provider is None or not _transport_allowed(provider):
        raise RuntimeError("Source route permission unavailable")
    request = Request(url, headers={"User-Agent": "Nerkhbaan-Price-Worker/3"})
    with build_opener(_RejectRedirect()).open(request, timeout=TIMEOUT) as response:
        if response.status != 200 or response.geturl() != url:
            raise RuntimeError("Source response route or status changed")
        body = response.read(MAX_RESPONSE_BYTES+1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Source payload exceeds the size limit")
        return json.loads(body.decode("utf-8"))


def gold_quote(payload: object, provider: str, now: datetime | None = None) -> dict:
    if provider not in ROUTES:
        raise ValueError("Source route is not allowed")
    symbol, instrument, unit, low, high = ROUTES[provider]
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if not isinstance(payload, dict) or payload.get("symbol") != symbol or payload.get("currency") != "USD":
        raise ValueError("Source symbol or USD currency changed")
    observed = _time(payload.get("updatedAt"), "Source timestamp", current, timedelta(seconds=MAX_LIVE_AGE_SECONDS))
    try:
        price = Decimal(str(payload.get("price")))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Source price is not numeric") from exc
    if not price.is_finite() or not Decimal(low) <= price <= Decimal(high):
        raise ValueError("Source price is outside the safe range")
    return {"provider_id": provider, "instrument_id": instrument, "price": str(price), "observed_at": observed.isoformat(), "historical": False, "currency": "USD", "weight_unit": unit, "source_url": f"https://api.gold-api.com/price/{symbol}", "attributions": [dict(ATTRIBUTION)]}


def send(quotes: list[dict[str, object]]) -> None:
    if not quotes or len(quotes) > 3 or len({quote.get("provider_id") for quote in quotes}) != len(quotes):
        raise RuntimeError("Source route selection is invalid")
    for quote in quotes:
        provider = str(quote.get("provider_id", ""))
        if not _transport_allowed(provider) or quote.get("historical"):
            raise RuntimeError("Source transport permission unavailable")
        checked = gold_quote({"symbol": ROUTES[provider][0], "currency": quote.get("currency"), "price": quote.get("price"), "updatedAt": quote.get("observed_at")}, provider)
        if any(quote.get(key) != checked[key] for key in ("instrument_id", "weight_unit", "source_url", "attributions")):
            raise RuntimeError("Source route metadata changed")
    destination = urlsplit(ENDPOINT)
    if destination.scheme != "https" or not destination.hostname or destination.username or destination.password or len(SECRET) < 32:
        raise RuntimeError("Private worker endpoint configuration is invalid")
    body = json.dumps({"quotes": quotes}, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET.encode("utf-8"), timestamp.encode("ascii")+b"."+body, hashlib.sha256).hexdigest()
    request = Request(f"{ENDPOINT}/ingest", data=body, headers={"Content-Type": "application/json", "X-Pricing-Worker-Timestamp": timestamp, "X-Pricing-Worker-Signature": signature}, method="POST")
    with build_opener(_RejectRedirect()).open(request, timeout=TIMEOUT) as response:
        if response.status != 202 or response.geturl() != request.full_url:
            raise RuntimeError("Unexpected private ingest response")
        result = json.loads(response.read(4096).decode("utf-8"))
        if not isinstance(result, dict) or result.get("accepted") != len(quotes) or result.get("published") != len(quotes):
            raise RuntimeError("Core did not publish every submitted quote")


def backfill() -> dict:
    # The approved free endpoint has no historical route. Preserve old progress.
    return {"status": "unavailable", "reason": "no_approved_history_source"}


def live() -> None:
    quotes = []
    failed = False
    for provider, route in ROUTES.items():
        try:
            if not _transport_allowed(provider):
                raise RuntimeError("Source permission unavailable")
            value = get_json(f"https://api.gold-api.com/price/{route[0]}")
            if not _transport_allowed(provider):
                raise RuntimeError("Source permission revoked")
            quotes.append(gold_quote(value, provider))
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.error("Live source unavailable: %s", provider)
            failed = True
    if quotes:
        send(quotes)
    if failed or not quotes:
        raise RuntimeError("One or more live prices are unavailable")


def run() -> None:
    live()
    logger.info("Historical source unavailable; old progress retained")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
