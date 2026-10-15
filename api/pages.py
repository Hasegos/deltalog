from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from core.config import settings
from core.templates import site_url, templates
from db.session import get_db
from services.web.changes_service import build_changes
from services.web.home_service import build_home
from services.web.page_service import build_tools, build_topics
from services.web import sitemap_service
from services.web.release_service import build_release, build_release_index

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


@page_router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request) -> HTMLResponse:
    """개인정보 처리방침 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 개인정보 처리방침 페이지
    """
    return templates.TemplateResponse(request, "privacy.html", {})


@page_router.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request) -> HTMLResponse:
    """이용약관 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 이용약관 페이지
    """
    return templates.TemplateResponse(request, "terms.html", {})


@page_router.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request) -> HTMLResponse:
    """문의 화면을 그린다.

    Args:
        request: 현재 요청
    Returns:
        렌더링한 문의 페이지
    """
    return templates.TemplateResponse(request, "contact.html", {})


@page_router.get("/changes", response_class=HTMLResponse)
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


@page_router.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request) -> PlainTextResponse:
    """검색 로봇 안내문을 돌려준다. API는 막고 사이트맵 주소를 알린다.

    Args:
        request: 현재 요청
    Returns:
        `robots.txt` 본문
    """
    return PlainTextResponse(f"User-agent: *\nDisallow: /api/\n\nSitemap: {site_url(request)}/sitemap.xml\n")


@page_router.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)) -> Response:
    """공개 페이지와 글 상세 페이지 주소를 담은 `sitemap.xml`을 돌려준다. 주소가 많으면 색인이 되어 `/sitemap-<쪽>.xml`을 가리킨다.

    Args:
        request: 현재 요청
        db: 요청에 쓸 DB 세션
    Returns:
        사이트맵 XML
    """
    return Response(sitemap_service.render(site_url(request), sitemap_service.collect_urls(db), None), media_type="application/xml")


@page_router.get("/sitemap-{page}.xml")
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


@page_router.get("/releases/{slug}/{key}", response_class=HTMLResponse)
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


@page_router.get("/releases", response_class=HTMLResponse)
@page_router.get("/releases/{slug}", response_class=HTMLResponse)
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
    context = build_release_index(db, slug)
    if context is None:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다")
    return templates.TemplateResponse(request, "releases.html", context)


@page_router.get("/r")
@page_router.get("/r/{rest:path}")
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


@page_router.get("/ads.txt", response_class=PlainTextResponse)
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