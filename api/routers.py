from fastapi import APIRouter, Depends

from api.security import require_api_key
from api.endpoints import item_endpoint, monthly_endpoint, release_endpoint, source_endpoint

api_router = APIRouter(dependencies=[Depends(require_api_key)])

api_router.include_router(item_endpoint.router, prefix="/api/items", tags=["items"])
api_router.include_router(source_endpoint.router, prefix="/api/sources", tags=["sources"])
api_router.include_router(release_endpoint.router, prefix="/api/releases", tags=["releases"])
api_router.include_router(monthly_endpoint.router, prefix="/api/monthly", tags=["monthly"])