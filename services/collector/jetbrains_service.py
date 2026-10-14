import re
from datetime import datetime, timedelta, timezone
from html import unescape

import httpx

from core.config import settings
from services.collector.github_release_service import FetchResult, Release

ISSUE_IDS = re.compile(r"\[(?:[A-Z]+-\d+(?:\s*,\s*)?)+\]|\s+[-–]\s+(?:[A-Z]+-\d+(?:,?\s*(?:and\s+)?)?)+\.?$")


def _body(html: str) -> str:
    """`whatsnew` HTML의 `<li>` 하나를 `-` 줄 하나로 바꾼다. 이슈 번호 `[IDEA-123]`는 뺀다. `<li>`가 없으면 빈 문자열."""
    lines = []
    for raw in re.findall(r"<li>(.*?)</li>", html, flags=re.DOTALL):
        text = unescape(re.sub(r"<[^>]+>", "", raw))
        text = re.sub(r"\s+", " ", ISSUE_IDS.sub("", text)).strip(" ,")
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


def fetch_releases(url: str, name: str) -> FetchResult:
    """JetBrains 릴리스 API에서 IDE 하나의 정식 릴리스를 받는다. 변경 목록(`<li>`)이 없는 릴리스는 요약할 내용이 없어 뺀다. 이 API는 ETag와 `If-Modified-Since`를 지원하지 않아 매번 받는다 (gzip으로 약 90KB).

    Args:
        url: 제품 코드가 들어 있는 API 주소
        name: IDE 이름 (`IntelliJ IDEA`). 글 제목에 쓴다
    Returns:
        `FetchResult`. `etag`는 항상 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    response = httpx.get(url, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=settings.JETBRAINS_TIMEOUT_SEC)
    response.raise_for_status()
    ceiling = datetime.now(timezone.utc) + timedelta(days=1)
    releases = []
    for row in next(iter(response.json().values()), []):
        moment = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
        if moment > ceiling:
            continue
        body = _body(row.get("whatsnew") or "")
        if not body:
            continue
        code = row.get("version") or row["build"]
        releases.append(
            Release(
                external_id=f"{url.split('code=')[1].split('&')[0]}:{code}",
                version=code,
                title=f"{name} {code}",
                published_at=moment,
                url=row.get("notesLink") or "https://www.jetbrains.com/",
                body=body,
                prerelease=False,
            )
        )
    releases.sort(key=lambda r: r.published_at, reverse=True)
    return FetchResult(etag=None, releases=releases[: settings.JETBRAINS_MAX_RELEASES])