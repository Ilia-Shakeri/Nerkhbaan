from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from ..pricing.compatibility import legacy_pricing_adapter
from ..pricing.health import pricing_health_service
from ..pricing.instruments import LEGACY_ASSET_MAPPING
from ..schemas import PriceHistoryResponse, PricesHealthResponse, PricesResponse

router = APIRouter(prefix="/api/prices", tags=["prices"])
_LEGACY_ASSETS = {asset for asset, _currency in LEGACY_ASSET_MAPPING}


@router.get("/{asset}/history", response_model=PriceHistoryResponse)
async def get_price_history(
    asset: str,
    response: Response,
    timeframe: Annotated[str, Query(pattern="^(1h|24h|7d|30d|1y)$")] = "30d",
) -> PriceHistoryResponse:
    asset_id = asset.lower()
    if asset_id not in _LEGACY_ASSETS:
        raise HTTPException(status_code=422, detail="Unknown asset")
    try:
        payload = await legacy_pricing_adapter.get_history(asset_id, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Price history is unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=60"
    return PriceHistoryResponse.model_validate(payload)


@router.get("", response_model=PricesResponse)
async def get_prices(response: Response) -> PricesResponse:
    try:
        payload = await legacy_pricing_adapter.get_prices()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Pricing data is unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=10"
    return PricesResponse.model_validate(payload)


@router.get("/health", response_model=PricesHealthResponse)
async def get_prices_health() -> PricesHealthResponse:
    payload = await legacy_pricing_adapter.health()
    detail = await pricing_health_service.detailed(authenticated=False)
    payload["startup"]["ok"] = detail["database"] == "connected" or detail["redis"] == "connected"
    return PricesHealthResponse.model_validate(payload)
