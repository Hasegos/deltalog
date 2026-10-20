from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from core.constants.taxonomy import CATEGORIES, SEVERITY
from crud import entry_crud, item_crud, news_crud
from services.web.release_service import release_path

FEED_LIMIT = 30
FEED_TOP = 3


def _date(moment: datetime) -> str:
    return format_datetime(moment.astimezone(timezone.utc))


def _release_html(stats: dict, top: list) -> str:
    """릴리스 한 건의 설명(HTML)을 만든다. 유형별 개수 한 줄, 중요한 항목 `FEED_TOP`개, 나머지 개수 순이다.

    Args:
        stats: `entry_crud.entry_stats`의 글 하나 값
        top: 중요도 높은 순 항목
    Returns:
        HTML 조각 (RSS에 넣을 때 이스케이프한다)
    """
    counts = [f"{CATEGORIES[key][1]} {stats['categories'][key]}" for key in SEVERITY if stats["categories"].get(key)]
    risky = any(stats["categories"].get(key) for key in ("breaking", "security"))
    shown = [i.summary_ko for i in top if i.summary_ko][:FEED_TOP]
    html = f"<p>{'⚠ ' if risky else ''}{escape(' · '.join(counts))}</p>" if counts else ""
    if shown:
        html += "<ul>" + "".join(f"<li>{escape(text)}</li>" for text in shown) + "</ul>"
    rest = stats["count"] - len(shown)
    return html + (f"<p>외 {rest}개</p>" if shown and rest > 0 else "")


def _title(db: Session, tools: list[str], companies: list[str], min_importance: int) -> str:
    """필터에 맞는 피드 제목을 만든다. 필터가 없으면 `Deltalog`다. 여러 구독을 한 리더에 넣어도 구분되게 한다."""
    names = {s.slug: s.name for s in item_crud.list_sources(db)}
    parts = [names.get(t, t) for t in tools] + companies
    title = "Deltalog" + (f" · {', '.join(parts)}" if parts else "")
    return title + (f" · 중요도 {min_importance}+" if min_importance > 1 else "")


def build_feed(db: Session, base: str, tools: list[str] | None = None, companies: list[str] | None = None, min_importance: int = 1) -> str:
    """릴리스와 공식 소식을 섞어 최신순 RSS 2.0 문서를 만든다.

    - 릴리스는 요약된 글 중 최신 `FEED_LIMIT`개이고, 주소는 이 사이트의 릴리스 상세 페이지, 설명은 유형별 개수, 중요한 항목 3개, 나머지 개수(HTML)다.
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
        ids = [e.id for e, _ in pairs]
        tops = entry_crud.top_items(db, ids, "all", "", "", FEED_TOP)
        stats = entry_crud.entry_stats(db, ids)
        for entry, source in pairs:
            link = base + release_path(source.slug, entry)
            entries.append((entry.published_at, f"{source.name} {entry.version or entry.title}", link, link, _release_html(stats[entry.id], tops.get(entry.id, []))))
    if companies or not tools:
        for article in news_crud.list_for_feed(db, companies, min_importance, FEED_LIMIT):
            entries.append((article.published_at, f"[{article.company}] {article.title_ko or article.title}", article.url, article.url, escape(article.summary_ko or "")))
    entries.sort(key=lambda e: e[0], reverse=True)
    items = "".join(
        f"<item><title>{escape(title)}</title><link>{escape(link)}</link><guid isPermaLink=\"true\">{escape(guid)}</guid>"
        f"<pubDate>{_date(moment)}</pubDate><description>{escape(html)}</description></item>"
        for moment, title, link, guid, html in entries[:FEED_LIMIT]
    )
    built = _date(entries[0][0]) if entries else _date(datetime.now(timezone.utc))
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{escape(_title(db, tools, companies, min_importance))}</title><link>{escape(base)}/</link>"
        "<description>AI 코딩 도구와 IDE의 릴리스 노트와 제작사 공식 소식을 한국어로 요약해 모읍니다.</description>"
        f"<language>ko</language><lastBuildDate>{built}</lastBuildDate>{items}</channel></rss>"
    )