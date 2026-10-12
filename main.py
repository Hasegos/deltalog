from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.pages import page_router
from api.routers import api_router
from core.config import settings
from db.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """시작할 때 테이블과 기본 소스를 준비한다.

    Args:
        app: 앱 인스턴스
    Yields:
        앱이 도는 동안 대기
    """
    init_db()
    yield


app = FastAPI(title=settings.PROJECT_NAME, version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(page_router)
app.include_router(api_router)
