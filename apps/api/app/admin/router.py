from fastapi import APIRouter, Depends

from .network import enforce_admin_network
from .routers import access_router, auth_router, operations_router, support_router

router = APIRouter(
    prefix="/api/admin",
    dependencies=[Depends(enforce_admin_network)],
)
router.include_router(auth_router)
router.include_router(access_router)
router.include_router(support_router)
router.include_router(operations_router)
