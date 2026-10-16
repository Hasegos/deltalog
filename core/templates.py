import os
import re

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from core.config import settings
from core.constants.source import SOURCES
from core.constants.taxonomy import TOPICS

templates = Jinja2Templates(directory="templates")


def mark(text: str | None, q: str) -> Markup:
    """글을 HTML로 이스케이프하고, 검색어와 일치하는 부분(대소문자 무시)을 `<mark>`로 감싼다.

    Args:
        text: 원래 글
        q: 검색어. 비어 있으면 이스케이프만 한다
    Returns:
        안전한 HTML
    """
    text = text or ""
    if not q:
        return escape(text)
    parts = re.split(f"({re.escape(q)})", text, flags=re.IGNORECASE)
    return Markup("".join(f"<mark>{escape(p)}</mark>" if i % 2 else escape(p) for i, p in enumerate(parts)))


templates.env.filters["mark"] = mark
templates.env.globals["footer_tools"] = [(s["slug"], s["name"]) for s in SOURCES]
templates.env.globals["footer_topics"] = TOPICS


def asset(path: str) -> str:
    """정적 파일 주소 뒤에 수정 시각을 붙여, 파일이 바뀌면 브라우저가 새로 받게 한다.

    Args:
        path: `static/` 아래 경로 (예: `css/home.css`)
    Returns:
        `/static/...?v=<수정 시각>` 주소
    """
    return f"/static/{path}?v={int(os.path.getmtime(os.path.join('static', path)))}"


templates.env.globals["asset"] = asset


def site_url(request) -> str:
    """사이트 주소를 끝 `/` 없이 돌려준다. `SITE_URL` 설정을 쓰고, 비어 있으면 요청 주소를 쓴다."""
    return (settings.SITE_URL or str(request.base_url)).rstrip("/")


def canonical_url(request) -> str:
    """현재 페이지의 대표 주소를 돌려준다. 검색어 같은 쿼리는 뺀다."""
    return site_url(request) + request.url.path


templates.env.globals["site_url"] = site_url
templates.env.globals["canonical_url"] = canonical_url
templates.env.globals["adsense_client"] = settings.adsense_client