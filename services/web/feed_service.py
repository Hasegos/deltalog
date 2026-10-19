from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from crud import entry_crud, news_crud
from services.web.release_service import release_path

FEED_LIMIT = 30


def _date(moment: datetime) -> str:
    return format_datetime(moment.astimezone(timezone.utc))


def build_feed(db: Session, base: str, tools: list[str] | None = None, companies: list[str] | None = None, min_importance: int = 1) -> str:
    """릴리스와 공식 소식을 섞어 최신순 RSS 2.0 문서를 만든다.

    - 릴리스는 요약된 글 중 최신 `FEED_LIMIT`개이고, 주소는 이 사이트의 릴리스 상세 페이지, 설명은 가장 중요한 항목 한 줄이다.
    - 소식은 요약된 글 중 최신 `FEED_LIMIT`개이고, 주소는 제작사 원문, 설명은 한국어 요약이다.
    - `tools`만 주면 릴리스만, `companies`만 주면 소식만, 둘 다 주면 둘 다, 둘 다 비면 모두 넣는다.

    Args:
        db: DB 세션
        base: 사이트 주소 (끝 `/` 없음)
        tools: 릴리스 소스 slug 목록
        companies: 소식 제작사 이름 목록
        min_importance: 이 중요도 이상(릴리스는 그 중요도 이상 항목이 있는 글, 소식은 글)만 넣는다
    Returns:
        RSS XML 문자열
    """
    tools, companies = tools or [], companies or []
    entries = []
    if tools or not companies:
        pairs = entry_crud.list_summarized_entries(db, FEED_LIMIT, tools, min_importance if min_importance > 1 else 0)
        tops = entry_crud.top_items(db, [e.id for e, _ in pairs], "all", "", "", 1)
        for entry, source in pairs:
            link = base + release_path(source.slug, entry)
            headline = next((i.summary_ko for i in tops.get(entry.id, []) if i.summary_ko), "")
            entries.append((entry.published_at, f"{source.name} {entry.version or entry.title}", link, link, headline))
    if companies or not tools:
        for article in news_crud.list_for_feed(db, companies, min_importance, FEED_LIMIT):
            entries.append((article.published_at, f"[{article.company}] {article.title_ko or article.title}", article.url, article.url, article.summary_ko or ""))
    entries.sort(key=lambda e: e[0], reverse=True)
    items = "".join(
        f"<item><title>{escape(title)}</title><link>{escape(link)}</link><guid isPermaLink=\"true\">{escape(guid)}</guid>"
        f"<pubDate>{_date(moment)}</pubDate><description>{escape(text)}</description></item>"
        for moment, title, link, guid, text in entries[:FEED_LIMIT]
    )
    built = _date(entries[0][0]) if entries else _date(datetime.now(timezone.utc))
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Deltalog</title><link>{escape(base)}/</link>"
        "<description>AI 코딩 도구와 IDE의 릴리스 노트와 제작사 공식 소식을 한국어로 요약해 모읍니다.</description>"
        f"<language>ko</language><lastBuildDate>{built}</lastBuildDate>{items}</channel></rss>"
    )
