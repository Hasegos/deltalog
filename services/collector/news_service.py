import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def fetch_feed(url: str) -> list[Article] | None:
    """피드에서 최근 글을 받는다. 지난번 ETag를 보내 변경이 없으면 `None`을 돌려준다.

    `NEWS_MAX_AGE_DAYS`보다 오래된 글은 빼고 최신순으로 `NEWS_MAX_ENTRIES`개까지 돌려준다.

    Args:
        url: 피드 주소
    Returns:
        최신순 글 목록. 변경이 없으면 `None`
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
    oldest = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    fresh = [a for a in _articles(response.text) if a.published_at is None or a.published_at >= oldest]
    far = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(fresh, key=lambda a: a.published_at or far, reverse=True)[:NEWS_MAX_ENTRIES]