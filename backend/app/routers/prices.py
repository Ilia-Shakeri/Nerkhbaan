from fastapi import APIRouter, HTTPException

from ..schemas import PricesHealthResponse, PricesResponse
from ..services.pricing import pricing_service

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("", response_model=PricesResponse)
async def get_prices() -> PricesResponse:
    try:
        payload = await pricing_service.get_prices()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch market prices: {exc}") from exc

    return PricesResponse.model_validate(payload)


@router.get("/health", response_model=PricesHealthResponse)
async def get_prices_health() -> PricesHealthResponse:
    try:
        if not pricing_service.has_refreshed():
            await pricing_service.get_prices()
    except Exception:
        # Health should remain available even if upstream providers fail.
        pass

    return PricesHealthResponse.model_validate(pricing_service.get_chain_health())
