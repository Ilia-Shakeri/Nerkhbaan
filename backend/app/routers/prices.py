from fastapi import APIRouter, HTTPException, Response

from ..schemas import PricesHealthResponse, PricesResponse
from ..services.pricing import pricing_service

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("", response_model=PricesResponse)
async def get_prices(response: Response) -> PricesResponse:
    try:
        payload = await pricing_service.get_prices()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch market prices: {exc}") from exc

    # Set Cache-Control to reduce network load from duplicate client queries
    response.headers["Cache-Control"] = "public, max-age=10"
    return PricesResponse.model_validate(payload)


@router.get("/health", response_model=PricesHealthResponse)
async def get_prices_health() -> PricesHealthResponse:
    try:
        if not pricing_service.has_refreshed():
            await pricing_service.get_prices()
    except Exception:
        # Health should remain visibly available even if upstream providers fail entirely.
        pass

    return PricesHealthResponse.model_validate(pricing_service.get_chain_health())