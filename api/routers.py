from fastapi import APIRouter

from api.endpoints import item_endpoint, release_endpoint, source_endpoint

api_router = APIRouter()

api_router.include_router(item_endpoint.router, prefix="/api/items", tags=["items"])
api_router.include_router(source_endpoint.router, prefix="/api/sources", tags=["sources"])
api_router.include_router(release_endpoint.router, prefix="/api/releases", tags=["releases"])