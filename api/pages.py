from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from core.constant import MIN_WEEK
from core.templates import templates
from db.session import get_db
from services.home_service import build_home
from services.page_service import build_tools, build_topics

page_router = APIRouter(include_in_schema=False)


@page_router.get("/", response_class=HTMLResponse)
def home_page(
    request: Request,
    tool: str = "",
    tab: str = "all",
    category: str = Query("", alias="type"),
    topic: str = "",
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=10000),
    week: int | None = Query(None, ge=MIN_WEEK, le=0),
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
        page: 쪽 번호 (1부터)
        week: 0이면 이번 주, -1이면 지난주. 값이 있으면 그 주의 글만 보여준다
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 홈 페이지
    """
    context = build_home(db, tool, tab, category, topic, q.strip(), page, week)
    return templates.TemplateResponse(request, "home.html", context)


@page_router.get("/tools", response_class=HTMLResponse)
def tools_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """도구 목록 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 도구 목록 페이지
    """
    return templates.TemplateResponse(request, "tools.html", build_tools(db))


@page_router.get("/topics", response_class=HTMLResponse)
def topics_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """주제 목록 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 주제 목록 페이지
    """
    return templates.TemplateResponse(request, "topics.html", build_topics(db))


@page_router.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    """소개 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 소개 페이지
    """
    return templates.TemplateResponse(request, "about.html", {})