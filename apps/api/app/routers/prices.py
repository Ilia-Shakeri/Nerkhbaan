from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response

from ..pricing.compatibility import legacy_pricing_adapter
from ..pricing import rights
from ..pricing.health import pricing_health_service
from ..pricing.instruments import LEGACY_ASSET_MAPPING
from ..schemas import PriceHistoryResponse, PricesHealthResponse, PricesResponse, ReferenceRatesResponse

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
    response.headers["Cache-Control"] = "no-store" if rights.enforced() else "public, max-age=60"
    return PriceHistoryResponse.model_validate(payload)


@router.get("", response_model=PricesResponse)
async def get_prices(response: Response) -> PricesResponse:
    try:
        payload = await legacy_pricing_adapter.get_prices()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Pricing data is unavailable") from exc
    response.headers["Cache-Control"] = "no-store"
    return PricesResponse.model_validate(payload)


@router.get("/health", response_model=PricesHealthResponse)
async def get_prices_health() -> PricesHealthResponse:
    payload = await legacy_pricing_adapter.health()
    detail = await pricing_health_service.detailed(authenticated=False)
    payload["startup"]["ok"] = bool(payload["startup"]["ok"] and detail["database"] == "connected" and detail["redis"] == "connected")
    payload["refresh"] = detail["refresh"]
    return PricesHealthResponse.model_validate(payload)


@router.get("/references", response_model=ReferenceRatesResponse)
async def get_reference_rates(
    response: Response,
    timeframe: Annotated[str, Query(pattern="^(1h|24h|7d|30d|1y)$")] = "30d",
) -> ReferenceRatesResponse:
    from ..pricing.reference_service import iranian_reference_service

    response.headers["Cache-Control"] = "no-store"
    try:
        payload = await iranian_reference_service.get(timeframe)
        return ReferenceRatesResponse.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Reference rates are unavailable") from exc
