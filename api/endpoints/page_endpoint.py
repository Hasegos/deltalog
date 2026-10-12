from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from core.templates import templates
from db.session import get_db
from services.page_service import build_tools, build_topics

router = APIRouter(include_in_schema=False)


@router.get("/tools", response_class=HTMLResponse)
def tools(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """도구 목록 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 도구 목록 페이지
    """
    return templates.TemplateResponse(request, "tools.html", build_tools(db))


@router.get("/topics", response_class=HTMLResponse)
def topics(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """주제 목록 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 주제 목록 페이지
    """
    return templates.TemplateResponse(request, "topics.html", build_topics(db))


@router.get("/about", response_class=HTMLResponse)
def about(request: Request) -> HTMLResponse:
    """소개 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 소개 페이지
    """
    return templates.TemplateResponse(request, "about.html", {})