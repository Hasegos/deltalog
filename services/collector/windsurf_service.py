import re
from datetime import datetime, timezone
from html.parser import HTMLParser

import httpx

from core.config import settings
from core.constants.source import SCRAPE_MAX_RELEASES, SCRAPE_TIMEOUT_SEC
from services.collector.github_release_service import FetchResult, Release

CHANGELOG_URL = "https://docs.devin.ai/desktop/changelog"
SKIP_TAGS = {"script", "style", "svg", "button"}
BLOCK_TAGS = {"p", "li", "ul", "ol", "div", "span"}


class _Updates(HTMLParser):
    """Mintlify 변경 로그 HTML에서 `update-label`(버전), `update-description`(날짜), `update-content`(본문)를 읽는다.

    본문은 `- 항목` 줄과 `## 제품 이름` 제목(문단이 `<strong>` 하나뿐일 때)으로 바꾼다. 다운로드 안내 줄은 버린다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.updates: list[dict] = []
        self._part = ""
        self._depth = 0
        self._skip = 0
        self._text: list[str] = []
        self._bold: list[str] = []
        self._in_item = 0
        self._in_bold = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        part = dict(attrs).get("data-component-part", "")
        if part in ("update-label", "update-description", "update-content"):
            self._part, self._depth = part, 1
            self._text = []
            if part == "update-label":
                self.updates.append({"label": "", "date": "", "lines": []})
            return
        if not self._part:
            return
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag not in ("br", "img", "hr", "input", "meta", "link", "source", "wbr"):
            self._depth += 1
        if self._part == "update-content":
            if tag == "li":
                self._in_item += 1
                self._text = []
            elif tag in ("strong", "b"):
                self._in_bold += 1

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """`<img/>`처럼 스스로 닫는 태그는 짝이 없어 깊이를 세지 않는다."""

    def handle_endtag(self, tag: str) -> None:
        if not self._part:
            return
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        self._depth -= 1
        if self._part == "update-content":
            if tag == "li" and self._in_item:
                self._in_item -= 1
                text = re.sub(r"\s+", " ", "".join(self._text)).strip()
                if text and not self._in_item:
                    self.updates[-1]["lines"].append(f"- {text}")
                self._text = []
            elif tag in ("strong", "b") and self._in_bold:
                self._in_bold -= 1
            elif tag in ("span", "p") and not self._in_item:
                text = re.sub(r"\s+", " ", "".join(self._text)).strip()
                if text and text == "".join(self._bold).strip() and not text.startswith("Download"):
                    self.updates[-1]["lines"].append(f"## {text}")
                self._text, self._bold = [], []
        if self._depth <= 0:
            part, self._part = self._part, ""
            value = re.sub(r"\s+", " ", "".join(self._text)).strip()
            if part == "update-label":
                self.updates[-1]["label"] = value
            elif part == "update-description":
                self.updates[-1]["date"] = value

    def handle_data(self, data: str) -> None:
        if not self._part or self._skip:
            return
        self._text.append(data)
        if self._in_bold:
            self._bold.append(data)


def parse(page: str) -> list[Release]:
    """Windsurf(Devin Desktop) 변경 로그 HTML에서 릴리스를 읽는다. 버전이나 날짜를 못 읽거나 항목이 없으면 건너뛴다.

    Args:
        page: `https://docs.devin.ai/desktop/changelog`의 HTML
    Returns:
        게시일 최신순 릴리스 목록 (최대 `SCRAPE_MAX_RELEASES`개)
    """
    parser = _Updates()
    parser.feed(page)
    releases = []
    for update in parser.updates:
        version = update["label"].lstrip("v")
        try:
            moment = datetime.strptime(update["date"], "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        body = "\n".join(update["lines"])
        if not version or "- " not in body:
            continue
        releases.append(
            Release(external_id=version, version=version, title=f"Windsurf {version}", published_at=moment, url=CHANGELOG_URL, body=body, prerelease=False)
        )
    releases.sort(key=lambda r: r.published_at, reverse=True)
    return releases[:SCRAPE_MAX_RELEASES]


def fetch_releases(url: str, etag: str | None) -> FetchResult:
    """Devin 문서에서 Windsurf 변경 로그를 받는다. 가벼운 `.md`(ETag 있음, 날짜는 없음)로 바뀌었는지만 보고, 바뀌었을 때만 날짜가 있는 HTML(약 2MB)을 받아 읽는다.

    Args:
        url: 변경 로그 Markdown 주소 (`.md`)
        etag: 지난번 `.md` 응답의 ETag
    Returns:
        새 ETag와 릴리스 목록. 304면 목록이 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    headers = {"User-Agent": settings.COLLECTOR_USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    head = httpx.get(url, headers=headers, timeout=SCRAPE_TIMEOUT_SEC, follow_redirects=True)
    if head.status_code == 304:
        return FetchResult(etag=etag, releases=None)
    head.raise_for_status()
    page = httpx.get(CHANGELOG_URL, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=SCRAPE_TIMEOUT_SEC, follow_redirects=True)
    page.raise_for_status()
    return FetchResult(etag=head.headers.get("ETag"), releases=parse(page.text))