from fastapi import APIRouter

from api.endpoints import health_endpoint, home_endpoint

api_router = APIRouter()
api_router.include_router(home_endpoint.router)
api_router.include_router(health_endpoint.router)
