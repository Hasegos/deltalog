import re
from datetime import datetime, timezone
from html import unescape

import httpx

from core.config import settings
from core.constants.source import SCRAPE_MAX_RELEASES, SCRAPE_TIMEOUT_SEC
from services.collector.github_release_service import FetchResult, Release

# 소스 slug별 변경 로그 탭. 같은 페이지에 탭마다 버전 번호가 따로 있다 (hub는 Antigravity App)
PANELS = {"antigravity": "hub", "antigravity-ide": "ide", "antigravity-cli": "cli", "antigravity-sdk": "sdk"}
ARTICLE = re.compile(r'<article\b[^>]*id="rel-{panel}-([^"]+)"[^>]*>(.*?)</article>', re.DOTALL)
GROUP = re.compile(r'<details\b[^>]*data-item-title="([^"]+)"[^>]*>.*?<ul[^>]*>(.*?)</ul>', re.DOTALL)
ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL)
DATE = re.compile(r"<time[^>]*>([^<]+)</time>")


def _text(fragment: str) -> str:
    """HTML 조각에서 태그를 지우고 공백을 하나로 줄인다."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def parse(page: str, panel: str, name: str, url: str) -> list[Release]:
    """Antigravity 변경 로그 HTML에서 탭 하나의 릴리스를 읽는다. 날짜를 못 읽거나 항목이 없으면 건너뛴다.

    Args:
        page: 변경 로그 페이지 HTML
        panel: 탭 이름 (`hub`, `ide`, `cli`, `sdk`, `extensions`)
        name: 제품 이름. 글 제목에 쓴다
        url: 글의 원문 주소로 쓸 변경 로그 주소
    Returns:
        게시일 최신순 릴리스 목록 (최대 `SCRAPE_MAX_RELEASES`개). 탭이 없으면 빈 목록
    """
    start = page.find(f'id="panel-{panel}"')
    if start < 0:
        return []
    end = page.find('id="panel-', start + 1)
    segment = page[start : end if end > 0 else len(page)]
    releases = []
    for version, block in re.findall(ARTICLE.pattern.format(panel=re.escape(panel)), segment, flags=re.DOTALL):
        date = DATE.search(block)
        try:
            moment = datetime.strptime(_text(date.group(1)), "%B %d, %Y").replace(tzinfo=timezone.utc)
        except (AttributeError, ValueError):
            continue
        lines = []
        for title, items in GROUP.findall(block):
            texts = [t for t in (_text(i) for i in ITEM.findall(items)) if t]
            if texts:
                lines += [f"## {_text(title)}"] + [f"- {t}" for t in texts]
        if not lines:
            continue
        releases.append(
            Release(external_id=f"{panel}:{version}", version=version, title=f"{name} {version}", published_at=moment, url=url, body="\n".join(lines), prerelease=False)
        )
    releases.sort(key=lambda r: r.published_at, reverse=True)
    return releases[:SCRAPE_MAX_RELEASES]


def fetch_releases(url: str, name: str, panel: str, etag: str | None) -> FetchResult:
    """Antigravity 변경 로그 페이지를 받는다. 저장해 둔 ETag를 보내 변경이 없으면 304로 끝낸다. 한 페이지를 소스마다 받으므로 ETag는 소스별로 따로 저장한다.

    Args:
        url: 변경 로그 주소
        name: 제품 이름
        panel: 읽을 탭 (`PANELS`의 값)
        etag: 지난번 응답의 ETag
    Returns:
        새 ETag와 릴리스 목록. 304면 목록이 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    headers = {"User-Agent": settings.COLLECTOR_USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    response = httpx.get(url, headers=headers, timeout=SCRAPE_TIMEOUT_SEC, follow_redirects=True)
    if response.status_code == 304:
        return FetchResult(etag=etag, releases=None)
    response.raise_for_status()
    return FetchResult(etag=response.headers.get("ETag"), releases=parse(response.text, panel, name, url))