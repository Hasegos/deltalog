import re
from datetime import datetime, timezone

import httpx

from core.config import settings
from core.constants.source import SCRAPE_MAX_RELEASES, SCRAPE_TIMEOUT_SEC
from services.collector.github_release_service import FetchResult, Release

# 소스 slug별 날짜 제목의 `#` 개수와 원문 주소. 날짜 제목 아래 목록이 그날의 항목인 Markdown 변경 로그를 읽는다
PAGES = {
    "anthropic-api": (3, "https://platform.claude.com/docs/en/release-notes/overview"),
    "gemini-api": (2, "https://ai.google.dev/gemini-api/docs/changelog"),
}
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
ESCAPED = re.compile(r"\\([_*\[\]])")


def _clean(text: str) -> str:
    """Markdown 링크(글자가 줄바꿈으로 갈라진 것 포함)는 글자만 남기고, `\\_` 같은 이스케이프는 푼다. 링크 주소가 요약 글자 수와 검증에 섞이지 않게 한다."""
    return ESCAPED.sub(r"\1", LINK.sub(r"\1", text))


def parse(markdown: str, level: int, url: str) -> list[Release]:
    """날짜 제목(`### October 15, 2026`)으로 나뉜 Markdown 변경 로그를 하루 단위 릴리스로 바꾼다.

    제목 앞의 안내 글은 버리고, 목록 항목이 없는 날짜는 건너뛴다. 같은 날짜가 여러 번이면 한 릴리스로 합친다.
    # ponytail: 하루 한 릴리스라 폴링 사이에 같은 날짜로 올라온 뒤늦은 항목은 저장하지 못한다. 필요해지면 항목마다 외부 ID를 둔다

    Args:
        markdown: 변경 로그 Markdown
        level: 날짜 제목의 `#` 개수
        url: 릴리스의 원문 주소
    Returns:
        게시일 최신순 릴리스 목록 (최대 `SCRAPE_MAX_RELEASES`개)
    """
    marks = "#" * level
    heads = list(re.finditer(rf"^{marks} (.+?)\s*$", markdown, re.MULTILINE))
    days: dict[str, list[str]] = {}
    for i, head in enumerate(heads):
        try:
            moment = datetime.strptime(head.group(1).replace(",", ""), "%B %d %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        block = markdown[head.end() : heads[i + 1].start() if i + 1 < len(heads) else len(markdown)]
        lines = [line.rstrip() for line in _clean(block).splitlines() if line.strip()]
        if any(line.startswith(("* ", "- ")) for line in lines):
            days.setdefault(moment.date().isoformat(), []).extend(lines)
    releases = [
        Release(
            external_id=day,
            version=None,
            title=day,
            published_at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
            url=url,
            body="\n".join(lines),
            prerelease=False,
        )
        for day, lines in days.items()
    ]
    releases.sort(key=lambda r: r.published_at, reverse=True)
    return releases[:SCRAPE_MAX_RELEASES]


def fetch_releases(feed_url: str, slug: str) -> FetchResult:
    """Markdown 변경 로그를 받는다. 이 사이트들은 ETag를 주지 않아(`no-store`, `no-cache`) 매번 받는다(60~130KB).

    Args:
        feed_url: 변경 로그 Markdown 주소
        slug: 소스 slug (`PAGES`의 키)
    Returns:
        `FetchResult`. `etag`는 항상 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    level, url = PAGES[slug]
    response = httpx.get(feed_url, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=SCRAPE_TIMEOUT_SEC, follow_redirects=True)
    response.raise_for_status()
    return FetchResult(etag=None, releases=parse(response.text, level, url))