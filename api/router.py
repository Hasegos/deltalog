from fastapi import APIRouter

from api.endpoints import home_endpoint, item_endpoint, page_endpoint

api_router = APIRouter()
api_router.include_router(home_endpoint.router)
api_router.include_router(page_endpoint.router)
api_router.include_router(item_endpoint.router)