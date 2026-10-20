from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.news import NEWS_COMPANIES
from core.templates import site_url, templates
from crud import item_crud
from db.session import get_db
from services.web.changes_service import build_changes
from services.web.deadline_service import build_deadlines
from services.web.feed_service import build_feed
from services.web.home_service import build_home
from services.web.news_service import build_news, build_news_detail
from services.web.page_service import build_tools, build_topics
from services.web.status_service import build_status
from services.web.weekly_service import build_weekly, parse_week
from services.web import sitemap_service
from services.web.release_service import build_release, build_release_index

page_router = APIRouter(include_in_schema=False)


def page(path: str, **kwargs):
    """`GET`과 `HEAD`를 함께 받는 페이지 라우트 데코레이터. 업타임 확인이나 `curl -I`가 `HEAD`로 오기 때문이다.

    Args:
        path: 라우트 주소
        **kwargs: `APIRouter.api_route`에 넘길 값 (예: `response_class`)
    Returns:
        라우트 데코레이터
    """
    return page_router.api_route(path, methods=["GET", "HEAD"], **kwargs)


@page("/", response_class=HTMLResponse)
def home_page(
    request: Request,
    tool: str = "",
    tab: str = "all",
    category: str = Query("", alias="type"),
    topic: str = "",
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=10000),
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
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 홈 페이지
    """
    context = build_home(db, tool, tab, category, topic, q.strip(), page)
    return templates.TemplateResponse(request, "home.html", context)


@page("/news", response_class=HTMLResponse)
def news_page(
    request: Request,
    company: str = "",
    tab: str = "all",
    topic: str = "",
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """소식(제작사 공식 발표) 화면을 그린다. 쿼리 값으로 제작사, 탭, 주제, 검색어를 거른다.

    Args:
        request: 현재 요청
        company: 제작사 이름
        tab: `all`, `imp`, `model`, `pricing`, `security`
        topic: 주제
        q: 검색어
        page: 쪽 번호 (1부터)
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 소식 페이지
    """
    return templates.TemplateResponse(request, "news.html", build_news(db, company, tab, topic, q, page))


@page("/news/{news_id}", response_class=HTMLResponse)
def news_detail_page(request: Request, news_id: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """소식 하나의 한국어 요약과 같은 시기 릴리스를 보여주는 상세 페이지를 그린다.

    Args:
        request: 현재 요청
        news_id: 소식 ID (숫자가 아니면 404)
        db: 요청에 쓸 DB 세션
    Returns:
        소식 상세 페이지
    Raises:
        HTTPException: 그런 소식이 없거나 아직 요약되지 않았을 때 (404)
    """
    context = build_news_detail(db, int(news_id), site_url(request)) if news_id.isdigit() and len(news_id) < 10 else None
    if context is None:
        raise HTTPException(status_code=404, detail="소식을 찾을 수 없습니다")
    return templates.TemplateResponse(request, "news_item.html", context)


@page("/deadlines", response_class=HTMLResponse)
def deadlines_page(request: Request, provider: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    """모델 · API 종료 일정 화면을 그린다. `provider` 쿼리 값으로 제공사를 거른다.

    Args:
        request: 현재 요청
        provider: 제공사 이름 (`Anthropic`, `OpenAI`, `Google`)
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 종료 일정 페이지
    """
    return templates.TemplateResponse(request, "deadlines.html", build_deadlines(db, provider))


@page("/status", response_class=HTMLResponse)
def status_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """수집 대상마다 마지막 확인 시각과 상태를 보여주는 수집 현황 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 수집 현황 페이지
    """
    return templates.TemplateResponse(request, "status.html", build_status(db))


@page("/weekly", response_class=HTMLResponse)
def weekly_latest(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """가장 최근 주의 주간 요약 화면을 그린다. 아직 요약이 없으면 빈 화면이다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 주간 요약 페이지
    """
    return templates.TemplateResponse(request, "weekly.html", build_weekly(db, None))


@page("/weekly/{week}", response_class=HTMLResponse)
def weekly_page(request: Request, week: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """한 주의 주간 요약 화면을 그린다. 주소의 날짜는 그 주 월요일이다.

    Args:
        request: 현재 요청
        week: `YYYY-MM-DD` (월요일)
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 주간 요약 페이지
    Raises:
        HTTPException: 날짜가 아니거나, 월요일이 아니거나, 그 주의 요약이 없을 때 (404)
    """
    monday = parse_week(week)
    values = build_weekly(db, monday) if monday and monday.isoformat() == week else None
    if values is None:
        raise HTTPException(status_code=404, detail="주간 요약을 찾을 수 없습니다")
    return templates.TemplateResponse(request, "weekly.html", values)


@page("/subscribe", response_class=HTMLResponse)
def subscribe_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """도구 · 제작사 · 최소 중요도를 골라 `/feed.xml` 주소를 만드는 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 RSS 구독 만들기 페이지
    """
    tools = [(src.slug, src.name) for src in item_crud.list_sources(db)]
    return templates.TemplateResponse(request, "subscribe.html", {"tools": tools, "companies": NEWS_COMPANIES, "base": site_url(request)})


@page("/tools", response_class=HTMLResponse)
def tools_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """도구 목록 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 도구 목록 페이지
    """
    return templates.TemplateResponse(request, "tools.html", build_tools(db))


@page("/topics", response_class=HTMLResponse)
def topics_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """주제 목록 화면을 그린다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 주제 목록 페이지
    """
    return templates.TemplateResponse(request, "topics.html", build_topics(db))


@page("/agents", response_class=HTMLResponse)
def agents_page(request: Request) -> HTMLResponse:
    """AI 에이전트(Claude Code, Cursor 등)에 MCP 서버(`/mcp`)를 연결하는 방법을 안내하는 페이지를 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 안내 페이지
    """
    return templates.TemplateResponse(request, "agents.html", {})


@page("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    """소개 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 소개 페이지
    """
    return templates.TemplateResponse(request, "about.html", {})


@page("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request) -> HTMLResponse:
    """개인정보 처리방침 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 개인정보 처리방침 페이지
    """
    return templates.TemplateResponse(request, "privacy.html", {})


@page("/terms", response_class=HTMLResponse)
def terms_page(request: Request) -> HTMLResponse:
    """이용약관 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 이용약관 페이지
    """
    return templates.TemplateResponse(request, "terms.html", {})


@page("/contact", response_class=HTMLResponse)
def contact_page(request: Request) -> HTMLResponse:
    """문의 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 문의 페이지
    """
    return templates.TemplateResponse(request, "contact.html", {})


@page("/changes", response_class=HTMLResponse)
def changes_page(
    request: Request,
    tool: str = "",
    version: str = Query("", max_length=40),
    level: str = "key",
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """"내 버전부터 최신까지 바뀐 점" 화면을 그린다.

    Args:
        request: 현재 요청
        tool: 소스 slug
        version: 지금 쓰는 버전
        level: `key`(중요한 것만) 또는 `all`
        db: 요청에 쓸 DB 세션
    Returns:
        렌더링한 버전 비교 페이지
    """
    return templates.TemplateResponse(request, "changes.html", build_changes(db, tool, version.strip(), level))


@page("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request) -> PlainTextResponse:
    """검색 로봇 안내문을 돌려준다. API는 막고 사이트맵 주소를 알린다.

    Args:
        request: 현재 요청
    Returns:
        `robots.txt` 본문
    """
    return PlainTextResponse(f"User-agent: *\nDisallow: /api/\n\nSitemap: {site_url(request)}/sitemap.xml\n")


@page("/feed.xml")
def feed(
    request: Request,
    tool: str = Query("", max_length=300),
    company: str = Query("", max_length=300),
    min_importance: int = Query(1, alias="min", ge=1, le=5),
    db: Session = Depends(get_db),
) -> Response:
    """릴리스와 공식 소식을 섞은 최신 30건 RSS를 돌려준다. 10분 동안 캐시해도 된다.

    쉼표로 이은 `tool`(소스 slug), `company`(제작사 이름)와 `min`(최소 중요도)으로 거를 수 있다. 목록에 없는 값은 무시한다.

    Args:
        request: 현재 요청
        tool: 릴리스 소스 slug 목록. 예: `claude-code,codex`
        company: 소식 제작사 이름 목록. 예: `Anthropic,OpenAI`
        min_importance: 최소 중요도 (`min` 쿼리 값, 1~5)
        db: 요청에 쓸 DB 세션
    Returns:
        RSS 2.0 XML
    """
    known = {src.slug for src in item_crud.list_sources(db)}
    tools = [t for t in dict.fromkeys(tool.split(",")) if t in known]
    companies = [c for c in dict.fromkeys(company.split(",")) if c in NEWS_COMPANIES]
    return Response(build_feed(db, site_url(request), tools, companies, min_importance), media_type="application/rss+xml", headers={"Cache-Control": "public, max-age=600"})


@page("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)) -> Response:
    """공개 페이지와 글 상세 페이지 주소를 담은 `sitemap.xml`을 돌려준다. 주소가 많으면 색인이 되어 `/sitemap-<쪽>.xml`을 가리킨다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        사이트맵 XML
    """
    return Response(sitemap_service.render(site_url(request), sitemap_service.collect_urls(db), None), media_type="application/xml")


@page("/sitemap-{page}.xml")
def sitemap_part(request: Request, page: int, db: Session = Depends(get_db)) -> Response:
    """사이트맵을 나눴을 때 한 쪽을 돌려준다.

    Args:
        request: 현재 요청
        page: 쪽 번호(1부터)
        db: 요청에 쓸 DB 세션
    Returns:
        사이트맵 XML
    Raises:
        HTTPException: 그런 쪽이 없을 때 (404)
    """
    xml = sitemap_service.render(site_url(request), sitemap_service.collect_urls(db), page)
    if xml is None or page < 1:
        raise HTTPException(status_code=404, detail="Not Found")
    return Response(xml, media_type="application/xml")


@page("/releases/{slug}/{key}", response_class=HTMLResponse)
def release_page(request: Request, slug: str, key: str, db: Session = Depends(get_db)) -> HTMLResponse:
    """릴리스 하나의 변경 사항을 항목별 요약으로 보여주는 상세 페이지를 그린다.

    Args:
        request: 현재 요청
        slug: 소스 slug
        key: 버전 (버전이 없는 글은 글 ID)
        db: 요청에 쓸 DB 세션
    Returns:
        릴리스 상세 페이지
    Raises:
        HTTPException: 그런 릴리스가 없을 때 (404)
    """
    context = build_release(db, slug, key, site_url(request))
    if context is None:
        raise HTTPException(status_code=404, detail="릴리스를 찾을 수 없습니다")
    return templates.TemplateResponse(request, "release.html", context)


@page("/releases", response_class=HTMLResponse)
@page("/releases/{slug}", response_class=HTMLResponse)
def release_index_page(request: Request, slug: str = "", db: Session = Depends(get_db)) -> HTMLResponse:
    """릴리스 목록 화면을 그린다. `/releases`는 도구마다 최근 릴리스, `/releases/<도구>`는 그 도구의 전체 릴리스다.

    Args:
        request: 현재 요청
        slug: 소스 slug. 비우면 모든 도구
        db: 요청에 쓸 DB 세션
    Returns:
        릴리스 목록 페이지
    Raises:
        HTTPException: 그런 도구가 없을 때 (404)
    """
    context = build_release_index(db, slug, site_url(request))
    if context is None:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다")
    return templates.TemplateResponse(request, "releases.html", context)


@page("/r")
@page("/r/{rest:path}")
def legacy_release_path(request: Request, rest: str = "") -> RedirectResponse:
    """옛 릴리스 주소(`/r/...`)를 새 주소(`/releases/...`)로 영구 이동시킨다.

    Args:
        request: 현재 요청
        rest: `/r/` 뒤의 경로
    Returns:
        301 응답
    """
    target = "/releases" + (f"/{quote(rest)}" if rest else "")
    if request.url.query:
        target += f"?{request.url.query}"
    return RedirectResponse(target, status_code=301)


@page("/ads.txt", response_class=PlainTextResponse)
def ads_txt() -> PlainTextResponse:
    """애드센스 판매자 확인 파일. `ADSENSE_CLIENT`가 없으면 404.

    Returns:
        `google.com, pub-<숫자>, DIRECT, f08c47fec0942fa0` 한 줄
    Raises:
        HTTPException: 광고 설정이 비어 있을 때 (404)
    """
    client = settings.adsense_client
    if not client:
        raise HTTPException(status_code=404, detail="Not Found")
    return PlainTextResponse(f"google.com, {client.removeprefix('ca-')}, DIRECT, f08c47fec0942fa0\n")


@page("/favicon.ico")
def favicon() -> FileResponse:
    """브라우저와 검색 로봇이 기본으로 찾는 `/favicon.ico`를 돌려준다.

    Returns:
        `static/img/favicon.ico` 파일 (하루 캐시)
    """
    return FileResponse("static/img/favicon.ico", media_type="image/x-icon", headers={"Cache-Control": "public, max-age=86400"})