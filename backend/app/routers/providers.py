from fastapi import APIRouter

from ..services.api_registry import API_REGISTRY

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
def get_provider_catalog() -> dict:
    return API_REGISTRY
