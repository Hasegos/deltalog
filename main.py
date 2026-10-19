from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from prometheus_client import REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator

from api.pages import page_router
from api.routers import api_router
from core.config import settings
from core.errors import register_exception_handlers
from core.logger import purge_old_logs, setup_logging
from core.middleware import access_log, api_headers, metrics_guard, security_headers
from db.init_db import init_db
from services.collector.poller_service import poll_all
from services.llm.llm_service import requeue_failed_job, summarize_job
from services.web.metrics_service import ItemStatusCollector

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """시작할 때 테이블과 기본 소스를 준비하고, 일정 주기로 소스를 가져오고 새 항목을 요약하는 스케줄러를 켠다.

    Args:
        app: 앱 인스턴스
    Yields:
        앱이 도는 동안 대기
    """
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        poll_all,
        "interval",
        minutes=settings.POLL_INTERVAL_MIN,
        next_run_time=datetime.now(),
        max_instances=1,
        coalesce=True,
    )
    if settings.AUTO_SUMMARIZE:
        scheduler.add_job(
            summarize_job,
            "interval",
            minutes=settings.SUMMARIZE_INTERVAL_MIN,
            next_run_time=datetime.now() + timedelta(seconds=30),
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(purge_old_logs, "cron", hour=3, minute=0, next_run_time=datetime.now())
    scheduler.add_job(requeue_failed_job, "cron", hour=4, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
register_exception_handlers(app)
app.middleware("http")(access_log)
app.middleware("http")(security_headers)
app.middleware("http")(api_headers)
app.middleware("http")(metrics_guard)
Instrumentator(should_ignore_untemplated=True, excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)
REGISTRY.register(ItemStatusCollector())
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(page_router)
app.include_router(api_router)