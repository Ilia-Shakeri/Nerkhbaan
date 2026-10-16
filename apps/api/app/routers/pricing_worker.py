from __future__ import annotations

import hashlib
import hmac
import re
import time

from fastapi import APIRouter, HTTPException, Request, status

from ..config import settings
from ..pricing.cache import PricingRedisUnavailable, pricing_redis
from ..pricing.locks import PricingLeaseLost
from ..pricing.service import PricingRefreshSuspended, instrument_pricing_service
from ..schemas import PricingWorkerIngestRequest

router = APIRouter(prefix="/api/internal/pricing-worker", tags=["pricing-worker"])
_MAX_CLOCK_SKEW_SECONDS = 300
_WORKER_ROUTES = {
    "coingecko_btc": "BTC_USD",
    "coingecko_usdt": "USDT_USD",
    "gold_api_free_xag": "XAG_USD_OZ",
    "gold_api_free_xau": "XAU_USD_OZ",
    "xaus_xag": "XAG_USD_OZ",
}


async def _authenticate(request: Request, body: bytes) -> None:
    secret = (settings.pricing_worker_shared_secret or "").strip()
    timestamp = request.headers.get("X-Pricing-Worker-Timestamp", "")
    signature = request.headers.get("X-Pricing-Worker-Signature", "")
    if not re.fullmatch(r"[0-9]{1,20}", timestamp) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker authentication failed")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker timestamp") from exc
    if not secret or len(secret) < 32 or abs(time.time() - timestamp_value) > _MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker authentication failed")
    expected = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker authentication failed")
    try:
        accepted = await pricing_redis.client().set(
            # A future-dated request remains valid for two skew windows. Keep
            # the claim through the inclusive final second as well.
            f"pricing:worker:replay:{signature}", "1", ex=2 * _MAX_CLOCK_SKEW_SECONDS + 1, nx=True
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker replay protection unavailable") from exc
    if not accepted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Worker request already processed")


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest(request: Request) -> dict[str, int]:
    body = await request.body()
    await _authenticate(request, body)
    try:
        payload = PricingWorkerIngestRequest.model_validate_json(body)
        for quote in payload.quotes:
            expected = _WORKER_ROUTES.get(quote.provider_id)
            if quote.instrument_id != expected:
                raise ValueError("Worker provider does not match instrument")
        outcomes = []
        for quote in payload.quotes:
            outcomes.append(await instrument_pricing_service.ingest_worker_quote(**quote.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (PricingRedisUnavailable, PricingRefreshSuspended, PricingLeaseLost) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pricing storage unavailable") from exc
    return {"accepted": len(payload.quotes), "published": outcomes.count("accepted"),
            "history_persisted": outcomes.count("historical_persisted"),
            "ignored": sum(item not in {"accepted", "historical_persisted"} for item in outcomes)}
