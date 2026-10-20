import re
import textwrap
from datetime import datetime, timezone

import httpx

from core.config import settings
from core.constants.source import SCRAPE_MAX_RELEASES, SCRAPE_TIMEOUT_SEC
from services.collector.github_release_service import FetchResult, Release

UPDATE = re.compile(r'<Update label="v?([^"]+)" description="([^"]+)">\n(.*?)\n</Update>', re.DOTALL)
BLOCK_TAGS = re.compile(r"<(Accordion|Release|Frame|Note|Tip|Warning)\b.*?(?:</\1>|/>)", re.DOTALL)
SECTION = re.compile(r"^\*\*([^*]+)\*\*$", re.MULTILINE)
CHANGELOG_URL = "https://docs.devin.ai/desktop/changelog"


def _body(raw: str) -> str:
    """`<Update>` 블록 안쪽을 요약에 넘길 Markdown으로 바꾼다. 다운로드 컴포넌트는 지우고, `**제품 이름**` 한 줄은 `## 제품 이름` 제목으로, `*` 목록은 `-` 목록으로 바꾼다."""
    text = textwrap.dedent(BLOCK_TAGS.sub("", raw))
    text = SECTION.sub(r"## \1", text).replace("\\[", "[").replace("\\]", "]")
    return re.sub(r"^(\s*)\*\s+", r"\1- ", text, flags=re.MULTILINE).strip()


def parse(markdown: str) -> list[Release]:
    """Windsurf(Devin Desktop) 변경 로그 Markdown에서 릴리스를 읽는다. 본문이 비면 건너뛴다.

    Args:
        markdown: `https://docs.devin.ai/desktop/changelog.md`의 내용
    Returns:
        게시일 최신순 릴리스 목록 (최대 `SCRAPE_MAX_RELEASES`개)
    """
    releases = []
    for version, label, raw in UPDATE.findall(markdown):
        try:
            moment = datetime.strptime(label, "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        body = _body(raw)
        if "- " not in body:
            continue
        releases.append(
            Release(external_id=version, version=version, title=f"Windsurf {version}", published_at=moment, url=CHANGELOG_URL, body=body, prerelease=False)
        )
    releases.sort(key=lambda r: r.published_at, reverse=True)
    return releases[:SCRAPE_MAX_RELEASES]


def fetch_releases(url: str) -> FetchResult:
    """Devin 문서에서 Windsurf 변경 로그를 받는다. 이 사이트는 ETag를 주지 않아 매번 받는다.

    Args:
        url: 변경 로그 Markdown 주소 (`.md`)
    Returns:
        `FetchResult`. `etag`는 항상 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    response = httpx.get(url, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=SCRAPE_TIMEOUT_SEC, follow_redirects=True)
    response.raise_for_status()
    return FetchResult(etag=None, releases=parse(response.text))