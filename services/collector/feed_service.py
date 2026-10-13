import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

import httpx

from core.logger import get_logger
from services.collector.github_release_service import FetchResult, Release

logger = get_logger("feed")

TIMEOUT_SEC = 20
USER_AGENT = "deltalog/0.1 (+https://github.com/Hasegos/deltalog)"
MAX_ENTRIES = 15
MAX_ITEM_CHARS = 900
PAGE_DELAY_SEC = 0.5
SKIP_TAGS = {"script", "style", "figure", "nav", "svg", "pre", "noscript"}
VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}
SKIP_HINTS = re.compile(r"thank|contribut|download|insiders", re.IGNORECASE)
PREVIEW_TITLE = re.compile(r"canary|beta|\bRC\b|alpha|\bdev\b", re.IGNORECASE)
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


class _Items(HTMLParser):
    """HTML에서 제목(`item_tag`) 하나와 그 뒤의 문단을 항목 하나로 모은다. 다운로드 안내, 그림, 코드 블록은 건너뛴다."""

    def __init__(self, item_tag: str, first_title: str = "") -> None:
        """
        Args:
            item_tag: 항목을 시작하는 제목 태그 (`h2` 또는 `h3`)
            first_title: 첫 제목 앞의 소개 문단을 한 항목으로 만들 때 쓸 이름. 비우면 소개 문단은 버린다
        """
        super().__init__(convert_charrefs=True)
        self.item_tag = item_tag
        self.items: list[list[str]] = []
        self.hints: list[str] = []
        self.hint = ""
        self.first_title = first_title
        self._skip = 0
        self._tag = ""
        self._text: list[str] = []
        self._current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in VOID_TAGS:
            return
        classes = dict(attrs).get("class") or ""
        if self._skip or tag in SKIP_TAGS or "release-downloads" in classes:
            self._skip += 1
            return
        if tag in ("h2", "h3", "h4", "p", "li"):
            self._tag = tag
            self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self._skip:
            self._skip -= 1
            return
        if tag != self._tag:
            return
        text = re.sub(r"<[^>]+>|Open in VS Code(?: Insiders)?", "", "".join(self._text))
        text = re.sub(r"\s+", " ", text).strip()
        self._tag = ""
        if not text:
            return
        if tag == self.item_tag:
            self._current = [text]
            self.items.append(self._current)
            self.hints.append(self.hint)
        elif tag == "h2":
            self.hint = text
            self._current = None
        elif tag in ("p", "li"):
            if self._current is None and self.first_title and not self.items:
                self._current = [self.first_title]
                self.items.append(self._current)
                self.hints.append("")
            if self._current is not None and sum(len(p) for p in self._current) < MAX_ITEM_CHARS:
                self._current.append(text)

    def handle_data(self, data: str) -> None:
        if not self._skip and self._tag:
            self._text.append(data)


def html_to_markdown(html: str, item_tag: str, title: str = "") -> str:
    """HTML 릴리스 노트를 `split_items`가 나눌 수 있는 Markdown으로 바꾼다. 제목 하나와 그 문단이 `-` 줄 하나가 된다.

    Args:
        html: 릴리스 노트 HTML
        item_tag: 항목을 시작하는 제목 태그 (`h2` 또는 `h3`)
        title: 글 제목. `h2`가 항목이면 첫 제목 앞의 소개 문단이 이 이름의 항목이 된다
    Returns:
        Markdown. 항목이 없으면 빈 문자열
    """
    parser = _Items(item_tag, first_title=title if item_tag == "h2" else "")
    parser.feed(html)
    lines: list[str] = []
    last_hint = None
    for hint, parts in zip(parser.hints, parser.items):
        if SKIP_HINTS.search(hint):
            continue
        if hint != last_hint and hint:
            lines.append(f"## {hint}")
        last_hint = hint
        head, rest = parts[0], " ".join(parts[1:])
        lines.append(f"- {head}: {rest}"[:MAX_ITEM_CHARS] if rest else f"- {head}")
    return "\n".join(lines)


def _studio_body(html: str) -> str:
    """Android Studio 글의 "Fixed Issues" 표에서 수정 항목을 `- 분류: 설명` 줄로 뽑는다. 표가 없으면 빈 문자열."""
    lines = []
    for block in re.split(r"<td><b>", html)[1:]:
        category, _, rest = block.partition("</b>")
        for raw in re.findall(r"<div>(.*?)</div>", rest, flags=re.DOTALL):
            text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", raw))).strip()
            if text and not text.startswith("Issue #"):
                lines.append(f"- {category.strip()}: {text}"[:MAX_ITEM_CHARS])
    return "\n".join(lines)


def _date(text: str) -> datetime:
    """Atom(ISO 8601)이나 RSS(RFC 822) 날짜를 UTC 시각으로 바꾼다."""
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _text(node: ET.Element, *names: str) -> str:
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _entries(xml: str, slug: str) -> list[Release]:
    """Atom이나 RSS 본문에서 글 목록을 읽는다. 본문이 피드에 있으면 채우고, 없으면 `body`를 비워 둔다.

    Args:
        xml: 피드 XML
        slug: 소스 slug (`vscode`, `cursor`, `android-studio`). 소스마다 제목, 항목 규칙이 다르다
    Returns:
        최신순 글 목록. 미리보기(Insiders)와 미래 날짜 글은 뺀다
    """
    root = ET.fromstring(xml)
    ceiling = datetime.now(timezone.utc) + timedelta(days=1)
    releases: list[Release] = []
    for node in root.iter(f"{ATOM}entry") if root.tag.startswith(ATOM) else root.iter("item"):
        title = _text(node, f"{ATOM}title", "title")
        link_node = next((n for n in node.findall(f"{ATOM}link") if n.get("rel", "alternate") == "alternate"), None)
        link = link_node.get("href", "") if link_node is not None else _text(node, "link")
        moment = _date(_text(node, f"{ATOM}published", f"{ATOM}updated", "pubDate"))
        if not title or not link or "insiders" in title.lower() or moment > ceiling:
            continue
        match = re.search(r"/updates/v(\d+)_(\d+)", link) if slug == "vscode" else None
        if slug == "vscode" and not match:
            continue
        body = ""
        if slug == "cursor":
            body = html_to_markdown(_text(node, f"{CONTENT}encoded", "description"), "h2", title)
        if slug == "android-studio":
            body = _studio_body(_text(node, f"{ATOM}content"))
        releases.append(
            Release(
                external_id=_text(node, f"{ATOM}id", "guid") or link,
                version=f"{match.group(1)}.{match.group(2)}" if match else "",
                title=title,
                published_at=moment,
                url=link,
                body=body,
                prerelease=slug == "android-studio" and bool(PREVIEW_TITLE.search(title)),
            )
        )
    return sorted(releases, key=lambda r: r.published_at, reverse=True)


def fetch_feed(slug: str, url: str, etag: str | None) -> FetchResult:
    """피드에서 글 목록을 받는다. 저장해 둔 ETag를 보내 변경이 없으면 304로 끝낸다.

    Args:
        slug: 소스 slug
        url: 피드 주소
        etag: 지난번 응답의 ETag
    Returns:
        `FetchResult`. 변경이 없으면 `releases`가 `None`. VS Code 글의 `body`는 비어 있으며 `fill_bodies`로 채운다
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    response = httpx.get(url, headers=headers, timeout=TIMEOUT_SEC, follow_redirects=True)
    if response.status_code == 304:
        return FetchResult(etag=etag, releases=None)
    response.raise_for_status()
    return FetchResult(etag=response.headers.get("ETag"), releases=_entries(response.text, slug)[:MAX_ENTRIES])


def fill_bodies(slug: str, releases: list[Release]) -> None:
    """본문이 피드에 없는 소스(VS Code)의 글 페이지를 받아 `body`를 채운다. 실패한 글은 `body`를 비워 둔다.

    Args:
        slug: 소스 slug
        releases: 새 글 목록. 제자리에서 고친다
    """
    if slug != "vscode":
        return
    for release in releases:
        if release.body:
            continue
        try:
            page = httpx.get(release.url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SEC, follow_redirects=True)
            page.raise_for_status()
            release.body = html_to_markdown(page.text, "h3")
        except httpx.HTTPError as exc:
            logger.warning("feed %s %s: 본문 요청 실패 (%s)", slug, release.version, exc.__class__.__name__)
        time.sleep(PAGE_DELAY_SEC)