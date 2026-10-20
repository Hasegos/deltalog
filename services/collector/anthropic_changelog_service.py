import re
from datetime import datetime, timezone

import httpx

from core.config import settings
from core.constants.source import SCRAPE_MAX_RELEASES, SCRAPE_TIMEOUT_SEC
from services.collector.github_release_service import FetchResult, Release

DATE_HEADING = re.compile(r"^### ([A-Z][a-z]+ \d{1,2}, \d{4})\s*$", re.MULTILINE)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
ESCAPED = re.compile(r"\\([_*\[\]])")
CHANGELOG_URL = "https://platform.claude.com/docs/en/release-notes/overview"


def _clean(text: str) -> str:
    """Markdown 링크는 글자만 남기고, `\\_` 같은 이스케이프는 푼다. 링크 주소가 요약 글자 수와 검증에 섞이지 않게 한다."""
    return ESCAPED.sub(r"\1", LINK.sub(r"\1", text)).strip()


def parse(markdown: str) -> list[Release]:
    """Claude Platform 릴리스 노트 Markdown을 하루 단위 릴리스로 바꾼다.

    `### October 15, 2026` 제목 아래의 `*` 목록이 그날의 항목이다. 제목 앞의 안내 글은 버리고, 항목이 없는 날짜는 건너뛴다.
    # ponytail: 하루 한 릴리스라 폴링 사이에 같은 날짜로 올라온 뒤늦은 항목은 저장하지 못한다. 필요해지면 항목마다 외부 ID를 둔다

    Args:
        markdown: `https://platform.claude.com/docs/en/release-notes/overview.md`의 내용
    Returns:
        게시일 최신순 릴리스 목록 (최대 `SCRAPE_MAX_RELEASES`개)
    """
    heads = list(DATE_HEADING.finditer(markdown))
    days: dict[str, list[str]] = {}
    for i, head in enumerate(heads):
        try:
            moment = datetime.strptime(head.group(1), "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        block = markdown[head.end() : heads[i + 1].start() if i + 1 < len(heads) else len(markdown)]
        lines = [_clean(line) if line[:1] not in (" ", "\t") else "  " + _clean(line) for line in block.splitlines() if line.strip()]
        if any(line.startswith(("* ", "- ")) for line in lines):
            days.setdefault(moment.date().isoformat(), []).extend(lines)
    releases = [
        Release(
            external_id=day,
            version=None,
            title=day,
            published_at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc),
            url=CHANGELOG_URL,
            body="\n".join(lines),
            prerelease=False,
        )
        for day, lines in days.items()
    ]
    releases.sort(key=lambda r: r.published_at, reverse=True)
    return releases[:SCRAPE_MAX_RELEASES]


def fetch_releases(url: str) -> FetchResult:
    """Claude Platform 릴리스 노트를 받는다. 이 사이트는 ETag를 주지 않아(`no-store`) 매번 받는다(약 130KB).

    Args:
        url: 릴리스 노트 Markdown 주소 (`.md`)
    Returns:
        `FetchResult`. `etag`는 항상 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    response = httpx.get(url, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=SCRAPE_TIMEOUT_SEC, follow_redirects=True)
    response.raise_for_status()
    return FetchResult(etag=None, releases=parse(response.text))