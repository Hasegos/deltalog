import re
from datetime import datetime, timezone
from html import unescape

import httpx

from core.config import settings
from core.constants.source import SCRAPE_MAX_RELEASES, SCRAPE_TIMEOUT_SEC
from services.collector.github_release_service import FetchResult, Release

MONTH_NAMES = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTH_HEADING = re.compile(rf"<h3[^>]*>({MONTH_NAMES}), (\d{{4}})</h3>")
DATE_BADGE = re.compile(r'data-variant="outline">([A-Z][a-z]{2}) (\d{1,2})</div>')
KIND = re.compile(r'<span class="capitalize">([^<]*)</span>')
TAG = re.compile(r'data-variant="soft">([^<]+)</div>')
CONTENT = re.compile(r'<div class="[^"]*ChangelogMarkdown[^"]*">(.*)', re.DOTALL)
CHANGELOG_URL = "https://developers.openai.com/api/docs/changelog"


def _text(fragment: str) -> str:
    """변경 로그 본문 HTML을 한 줄 글로 바꾼다. 태그를 지우고 공백을 하나로 줄인다."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<li[^>]*>", " - ", fragment)))).strip()


def parse(page: str) -> list[Release]:
    """OpenAI API 변경 로그 HTML을 하루 단위 릴리스로 바꾼다. 같은 날짜의 항목은 한 릴리스에 모은다.

    날짜 배지(`Oct 16`)에는 연도가 없어서 바로 앞의 월 제목(`October, 2026`)에서 연도를 가져온다.
    항목은 `- [유형 · 모델 · 엔드포인트] 본문` 한 줄이다. 본문이 비면 건너뛴다.
    # ponytail: 하루 한 릴리스라 폴링 사이에 같은 날짜로 올라온 뒤늦은 항목은 저장하지 못한다. 필요해지면 항목마다 외부 ID를 둔다

    Args:
        page: 변경 로그 페이지 HTML
    Returns:
        게시일 최신순 릴리스 목록 (최대 `SCRAPE_MAX_RELEASES`개)
    """
    main_end = page.find("</main>")
    page = page[: main_end if main_end > 0 else len(page)]
    months = [(m.start(), m.group(1), int(m.group(2))) for m in MONTH_HEADING.finditer(page)]
    badges = list(DATE_BADGE.finditer(page))
    days: dict[str, list[str]] = {}
    for i, badge in enumerate(badges):
        next_month = MONTH_HEADING.search(page, badge.end())
        ends = [len(page)]
        if i + 1 < len(badges):
            ends.append(badges[i + 1].start())
        if next_month:
            ends.append(next_month.start())
        segment = page[badge.end() : min(ends)]
        year = next((y for pos, _, y in reversed(months) if pos < badge.start()), None)
        content = CONTENT.search(segment)
        if year is None or content is None:
            continue
        try:
            moment = datetime.strptime(f"{badge.group(1)} {badge.group(2)} {year}", "%b %d %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        body = _text(content.group(1).split('<div class="_Badge', 1)[0])
        if not body:
            continue
        labels = [_text(k) for k in KIND.findall(segment)[:1]] + [_text(t) for t in TAG.findall(segment)]
        days.setdefault(moment.date().isoformat(), []).append(f"- [{' · '.join(labels)}] {body}" if labels else f"- {body}")
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


def fetch_releases(url: str, etag: str | None) -> FetchResult:
    """OpenAI API 변경 로그 페이지를 받는다. 저장해 둔 ETag를 보내 변경이 없으면 304로 끝낸다.

    Args:
        url: 변경 로그 주소
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
    return FetchResult(etag=response.headers.get("ETag"), releases=parse(response.text))