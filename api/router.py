from fastapi import APIRouter

from api.endpoints import home_endpoint

api_router = APIRouter()
api_router.include_router(home_endpoint.router)
