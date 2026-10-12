from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.config import settings
from core.templates import templates
from db.session import get_db
from services.home_service import build_home

app = FastAPI(title=settings.PROJECT_NAME, version="0.1.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home(
    request: Request,
    tool: str = "",
    tab: str = "all",
    category: str = Query("", alias="type"),
    topic: str = "",
    q: str = Query("", max_length=100),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """홈 화면을 그린다. 쿼리 값으로 도구, 탭, 유형, 주제, 검색어를 거른다.

    Args:
        request: 현재 요청
        tool: 소스 slug
        tab: `all`, `imp`, `risk`
        category: 유형 (`type` 쿼리 값. `feature`, `bugfix`, `breaking`, `security`)
        topic: 주제
        q: 검색어
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 홈 페이지
    """
    context = build_home(db, tool, tab, category, topic, q.strip())
    return templates.TemplateResponse(request, "home.html", context)


@app.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """앱과 DB 연결 상태를 돌려준다.

    Args:
        db: 요청에 쓸 DB 세션
    Returns:
        앱과 DB가 모두 정상일 때 `{"status": "ok", "db": "ok"}`
    Raises:
        HTTPException: DB에 닿지 않을 때 503
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="db unavailable") from exc
    return {"status": "ok", "db": "ok"}