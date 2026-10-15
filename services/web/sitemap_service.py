import os
from datetime import datetime, timezone
from urllib.parse import quote
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from crud import entry_crud, item_crud
from services.web.release_service import release_path

SITEMAP_LIMIT = 45000
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
DATA_PAGES = ("/", "/releases", "/changes", "/tools", "/topics")
FILE_PAGES = {"/about": "about.html", "/contact": "contact.html", "/privacy": "privacy.html", "/terms": "terms.html"}
ENTRY_PATHS = {"release": release_path}


def _day(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def collect_urls(db: Session) -> list[tuple[str, str]]:
    """사이트맵에 넣을 모든 `(경로, lastmod)`를 모은다.

    - 데이터를 보여주는 목록 페이지는 그 데이터의 가장 최근 글 게시일을 쓴다.
    - 소개, 문의, 처리방침, 약관은 템플릿 파일의 수정일을 쓴다.
    - 글 상세 페이지는 요약된 항목이 있는 글만 넣고, 주소는 글의 `kind`에 맞는 함수(`ENTRY_PATHS`)로 만든다.
      새 종류(뉴스)는 `ENTRY_PATHS`에 함수를 더하면 자동으로 들어간다.

    Args:
        db: DB 세션
    Returns:
        `(경로, YYYY-MM-DD)` 목록
    """
    newest = entry_crud.latest_published_per_source(db)
    overall = max(newest.values(), default=None)
    urls: list[tuple[str, str]] = []
    for path in DATA_PAGES:
        urls.append((path, _day(overall)) if overall else (path, ""))
    for source in item_crud.list_sources(db):
        moment = newest.get(source.id)
        urls.append((f"/releases/{quote(source.slug, safe='')}", _day(moment) if moment else ""))
    for path, template in FILE_PAGES.items():
        urls.append((path, _day(datetime.fromtimestamp(os.path.getmtime(os.path.join("templates", template)), timezone.utc))))
    for entry, source in entry_crud.list_summarized_entries(db):
        make_path = ENTRY_PATHS.get(entry.kind)
        if make_path:
            urls.append((make_path(source.slug, entry), _day(entry.published_at)))
    return urls


def _url_tag(base: str, path: str, day: str) -> str:
    lastmod = f"<lastmod>{day}</lastmod>" if day else ""
    return f"<url><loc>{escape(base + path)}</loc>{lastmod}</url>"


def page_count(urls: list[tuple[str, str]]) -> int:
    """사이트맵을 몇 파일로 나눠야 하는지 돌려준다. `SITEMAP_LIMIT` 이하면 1이다."""
    return max(1, -(-len(urls) // SITEMAP_LIMIT))


def render(base: str, urls: list[tuple[str, str]], page: int | None) -> str | None:
    """사이트맵 XML을 만든다. 주소가 `SITEMAP_LIMIT`개를 넘으면 `page`가 없을 때 색인(sitemapindex)을 돌려준다.

    Args:
        base: 사이트 주소 (끝 `/` 없음)
        urls: `collect_urls`의 결과
        page: 쪽 번호(1부터). `None`이면 `/sitemap.xml` 본체
    Returns:
        XML 문자열. 없는 쪽이면 `None`
    """
    pages = page_count(urls)
    head = '<?xml version="1.0" encoding="UTF-8"?>'
    if page is None and pages > 1:
        parts = "".join(f"<sitemap><loc>{escape(base)}/sitemap-{n}.xml</loc></sitemap>" for n in range(1, pages + 1))
        return f'{head}<sitemapindex xmlns="{SITEMAP_NS}">{parts}</sitemapindex>'
    number = page or 1
    if number > pages:
        return None
    chunk = urls[(number - 1) * SITEMAP_LIMIT : number * SITEMAP_LIMIT]
    return f'{head}<urlset xmlns="{SITEMAP_NS}">{"".join(_url_tag(base, path, day) for path, day in chunk)}</urlset>'