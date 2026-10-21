import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from core.config import settings
from core.constants.news import NEWS_BODY_CHARS, NEWS_MAX_AGE_DAYS, NEWS_MAX_ENTRIES
from services.collector.feed_service import ATOM, CONTENT, _date, _text

DC_DATE = "{http://purl.org/dc/elements/1.1/}date"
_etags: dict[str, str] = {}


@dataclass
class Article:
    """피드에서 읽은 공식 발표 글 하나. `published_at`이 피드에 없으면 `None`이다."""

    url: str
    title: str
    published_at: datetime | None
    body: str


def canonical_url(url: str) -> str:
    """주소에서 추적용 쿼리(`utm_*` 등)와 `#` 뒷부분, 끝의 `/`를 떼어 같은 글이 한 주소가 되게 한다.

    Args:
        url: 피드의 글 주소
    Returns:
        정리한 주소
    """
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "ref"))])
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", query, ""))


def to_text(html: str) -> str:
    """HTML 본문을 태그 없는 글로 바꾸고 `NEWS_BODY_CHARS`자로 자른다.

    Args:
        html: 피드의 본문(HTML 또는 글)
    Returns:
        공백을 정리한 글
    """
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()[:NEWS_BODY_CHARS]


def _articles(xml: str) -> list[Article]:
    """Atom이나 RSS 본문에서 글 목록을 읽는다. 날짜를 읽을 수 없는 글은 `published_at`을 `None`으로 둔다."""
    root = ET.fromstring(xml)
    found: list[Article] = []
    for node in root.iter(f"{ATOM}entry") if root.tag.startswith(ATOM) else root.iter("item"):
        title = to_text(_text(node, f"{ATOM}title", "title"))
        link_node = next((n for n in node.findall(f"{ATOM}link") if n.get("rel", "alternate") == "alternate"), None)
        link = link_node.get("href", "") if link_node is not None else _text(node, "link")
        if not title or not link.startswith(("https://", "http://")):
            continue
        stamp = _text(node, f"{ATOM}published", f"{ATOM}updated", "pubDate", DC_DATE)
        try:
            moment = _date(stamp) if stamp else None
        except ValueError:
            moment = None
        body = to_text(_text(node, f"{CONTENT}encoded", f"{ATOM}content", "description", f"{ATOM}summary"))
        found.append(Article(url=canonical_url(link), title=title, published_at=moment, body=body))
    return found


def _meta(html: str, key: str) -> str:
    """`<meta property|name="key" content="...">`의 content를 돌려준다. 속성 순서가 달라도 읽고, 없으면 빈 글이다."""
    found = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(key)}"[^>]*content="([^"]*)"', html) or re.search(
        rf'<meta[^>]+content="([^"]*)"[^>]*(?:property|name)="{re.escape(key)}"', html
    )
    return unescape(found.group(1)).strip() if found else ""


def _published(html: str) -> datetime | None:
    """HTML의 `datePublished`(JSON-LD)나 `article:published_time` 메타에서 게시일을 읽는다. 없으면 `None`이다."""
    found = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
    stamp = found.group(1) if found else _meta(html, "article:published_time")
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def page_date(url: str) -> datetime | None:
    """글 페이지의 `datePublished`(JSON-LD)나 `article:published_time` 메타에서 게시일을 읽는다. 읽지 못하면 `None`이다.

    피드에 날짜가 없는 소스(Google Developers Blog)에서 첫 수집 시각 대신 실제 게시일을 쓰려고 쓴다.

    Args:
        url: 글 주소
    Returns:
        게시일(UTC). 요청이 실패하거나 날짜를 못 찾으면 `None`
    """
    try:
        response = httpx.get(url, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=settings.FEED_TIMEOUT_SEC, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return _published(response.text)


def _conditional_get(url: str) -> httpx.Response | None:
    """지난번 ETag를 보내 주소를 받는다. 변경이 없으면 `None`을 돌려준다.

    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    headers = {"User-Agent": settings.COLLECTOR_USER_AGENT}
    if url in _etags:
        headers["If-None-Match"] = _etags[url]
    response = httpx.get(url, headers=headers, timeout=settings.FEED_TIMEOUT_SEC, follow_redirects=True)
    if response.status_code == 304:
        return None
    response.raise_for_status()
    if response.headers.get("ETag"):
        _etags[url] = response.headers["ETag"]
    return response


def fetch_feed(url: str) -> list[Article] | None:
    """피드에서 최근 글을 받는다. 지난번 ETag를 보내 변경이 없으면 `None`을 돌려준다.

    `NEWS_MAX_AGE_DAYS`보다 오래된 글은 빼고 최신순으로 `NEWS_MAX_ENTRIES`개까지 돌려준다.

    Args:
        url: 피드 주소
    Returns:
        최신순 글 목록. 변경이 없으면 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했거나 응답이 비었을 때 (JetBrains 피드가 가끔 빈 본문을 준다)
    """
    response = _conditional_get(url)
    if response is None:
        return None
    if not response.text.strip():
        _etags.pop(url, None)  # 빈 응답의 ETag를 기억하면 다음부터 304만 받아 영영 비어 보인다
        raise httpx.ReadError("빈 응답")
    oldest = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    fresh = [a for a in _articles(response.text) if a.published_at is None or a.published_at >= oldest]
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(fresh, key=lambda a: a.published_at or far, reverse=True)[:NEWS_MAX_ENTRIES]


def fetch_listing(feed: dict) -> list[str] | None:
    """피드가 없는 제작사의 최근 글 주소를 받는다 (`NEWS_FEEDS`의 `kind` 참고).

    sitemap은 `lastmod`가 `NEWS_MAX_AGE_DAYS`보다 오래된 주소를 빼고 최신순으로, index는 나온 순서대로 `NEWS_MAX_ENTRIES`개까지 돌려준다.

    Args:
        feed: `slug`, `kind`, `url`, `prefix`를 가진 한 줄
    Returns:
        글 주소 목록. 변경이 없으면 `None`
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    response = _conditional_get(feed["url"])
    if response is None:
        return None
    prefix = feed["prefix"]

    def is_article(link: str) -> bool:
        return link.startswith(prefix) and len(link) > len(prefix) and "/" not in link[len(prefix) :]

    if feed["kind"] == "index":
        links = dict.fromkeys(canonical_url(urljoin(feed["url"], h)) for h in re.findall(r'href="([^"]+)"', response.text))
        return [link for link in links if is_article(link)][:NEWS_MAX_ENTRIES]
    oldest = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    floor = datetime.min.replace(tzinfo=timezone.utc)
    found: list[tuple[datetime, str]] = []
    for loc, stamp in re.findall(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", response.text):
        link = canonical_url(loc)
        try:
            moment = _date(stamp) if stamp else None
        except ValueError:
            moment = None
        if is_article(link) and (moment is None or moment >= oldest):
            found.append((moment or floor, link))
    return [link for _, link in sorted(found, reverse=True)[:NEWS_MAX_ENTRIES]]


def fetch_page(url: str) -> Article | None:
    """글 페이지 하나를 읽어 제목, 게시일, 본문 앞부분을 돌려준다. 읽지 못하거나 제목이 없으면 `None`이다.

    제목은 `og:title`(없으면 `<title>`)에서 `| 회사 이름` 꼬리를 뗀 것이다. 본문은 `nav` · `header` · `footer`를 뺀 글에서 `og:description`이 나오는 곳부터 쓰고, 글 안에 없으면 앞에 붙인다.

    Args:
        url: 글 주소
    Returns:
        글. 게시일을 못 읽으면 `published_at`이 `None`
    """
    try:
        response = httpx.get(url, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=settings.FEED_TIMEOUT_SEC, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    html = response.text
    title = _meta(html, "og:title")
    if not title:
        found = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        title = to_text(found.group(1)) if found else ""
    title = re.sub(r"\s+[|\\·•–—-]\s+(?:Cursor|Anthropic|xAI|SpaceXSI)\s*$", "", title).strip()
    if not title:
        return None
    body = to_text(re.sub(r"(?is)<(nav|header|footer).*?</>", " ", html))
    summary = _meta(html, "og:description")
    if summary:
        at = body.find(summary[:40])
        body = body[at:] if at >= 0 else f"{summary} {body}"[:NEWS_BODY_CHARS]
    return Article(url=url, title=title, published_at=_published(html), body=body)