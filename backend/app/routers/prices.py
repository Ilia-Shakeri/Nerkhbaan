from fastapi import APIRouter, HTTPException

from ..schemas import PricesResponse
from ..services.pricing import pricing_service

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("", response_model=PricesResponse)
async def get_prices() -> PricesResponse:
    try:
        payload = await pricing_service.get_prices()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch market prices: {exc}") from exc

    return PricesResponse.model_validate(payload)
