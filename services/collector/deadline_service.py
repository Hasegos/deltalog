import hashlib
import re
from html import unescape

import httpx

from core.config import settings
from core.constants.deadline import DEADLINE_CHUNK_CHARS


def _row(match: re.Match) -> str:
    """표의 한 행을 `칸 | 칸 | 칸` 한 줄로 만든다. 칸 안에서 줄이 바뀌어도 한 줄에 둔다."""
    cells = re.split(r"(?i)<t[dh]\b[^>]*>", match.group(0))
    parts = [re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", cell))).strip() for cell in cells]
    return "\n" + " | ".join(part for part in parts if part) + "\n"


def to_lines(html: str) -> str:
    """폐기 안내 문서 HTML을 줄 단위 글로 바꾼다. 표의 한 행은 `칸 | 칸 | 칸`의 한 줄이 되고, 같은 줄이 이어서 반복되면 하나만 남긴다.

    Args:
        html: 문서 HTML
    Returns:
        줄바꿈으로 이어 붙인 글
    """
    text = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer)\b.*?</\1>", " ", html)
    text = re.sub(r"(?is)<tr\b.*?</tr>", _row, text)
    text = re.sub(r"(?i)</(tr|p|li|h[1-6]|div|section)\s*>|<br\s*/?>", "\n", text)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    lines: list[str] = []
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip(" |")
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def fetch_text(url: str) -> str:
    """폐기 안내 문서를 받아 줄 단위 글로 돌려준다.

    Args:
        url: 문서 주소
    Returns:
        줄 단위 글
    Raises:
        httpx.HTTPError: 요청이 실패했을 때
    """
    response = httpx.get(url, headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=settings.FEED_TIMEOUT_SEC, follow_redirects=True)
    response.raise_for_status()
    return to_lines(response.text)


def content_hash(text: str) -> str:
    """글의 SHA-256 해시를 돌려준다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunks(text: str, size: int = DEADLINE_CHUNK_CHARS) -> list[str]:
    """글을 줄 경계에서 `size`자 안팎으로 나눈다. 표의 행이 한 줄이라 행이 잘리지 않는다.

    Args:
        text: 줄 단위 글
        size: 한 조각의 최대 글자 수 (한 줄이 더 길면 그 줄 하나가 한 조각이다)
    Returns:
        조각 목록
    """
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.split("\n"):
        if current and length + len(line) + 1 > size:
            pieces.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        pieces.append("\n".join(current))
    return pieces