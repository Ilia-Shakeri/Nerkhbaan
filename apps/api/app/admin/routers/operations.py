from fastapi import APIRouter

from .health_jobs import router as health_jobs_router
from .pricing import router as pricing_router
from .providers import router as providers_router
from .settings import router as settings_router

router = APIRouter()
router.include_router(health_jobs_router)
router.include_router(pricing_router)
router.include_router(providers_router)
router.include_router(settings_router)
