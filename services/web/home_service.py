from datetime import datetime, time, timedelta
from math import ceil
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from core.constants.news import NEWS_HOME_COUNT
from core.constants.page import IMPORTANT_MIN, KST, PAGE_SIZE, SHOWN_ITEMS, WEEK_BOX_DAYS
from core.constants.taxonomy import CATEGORIES, SEVERITY, TOPICS
from crud import entry_crud, feed_status_crud, item_crud, news_crud
from services.web.deadline_service import build_soon
from services.web.release_service import release_path

TABS = [("all", "전체", "전체"), ("imp", "중요 4+", "중요"), ("risk", "breaking · 보안", "주의")]
WEEKDAYS = "월화수목금토일"
HIGHLIGHTS = 4


def _url(params: dict[str, str], **override: str | None) -> str:
    """현재 필터에 조건 하나를 바꾼 주소를 만든다. 이미 같은 값이면 그 조건을 뺀다.

    Args:
        params: 현재 필터
        override: 바꿀 조건. 값이 `None`이면 그 조건을 뺀다
    Returns:
        `/` 또는 `/?...` 주소
    """
    merged = dict(params)
    for key, value in override.items():
        if value is None or merged.get(key) == value:
            merged.pop(key, None)
        else:
            merged[key] = value
    return "/?" + urlencode(merged) if merged else "/"


def _week_start(now: datetime) -> datetime:
    """이번 주 월요일 00:00(한국 시간)을 돌려준다.

    Args:
        now: 기준 시각
    Returns:
        그 주 월요일 00:00
    """
    monday = now.astimezone(KST).date() - timedelta(days=now.astimezone(KST).weekday())
    return datetime.combine(monday, time.min, tzinfo=KST)


def _day_label(day: datetime, now: datetime) -> str:
    """날짜 구분선에 쓸 이름을 돌려준다.

    Args:
        day: 게시 시각
        now: 기준 시각
    Returns:
        `오늘`, `어제`, 아니면 `10월 10일 (토)` 꼴
    """
    gap = (now.astimezone(KST).date() - day.astimezone(KST).date()).days
    if gap == 0:
        return "오늘"
    if gap == 1:
        return "어제"
    local = day.astimezone(KST)
    return f"{local.month}월 {local.day}일 ({WEEKDAYS[local.weekday()]})"


def _ago(moment: datetime, now: datetime) -> str:
    """게시 시각이 지금으로부터 얼마나 전인지 짧게 돌려준다.

    Args:
        moment: 게시 시각
        now: 기준 시각
    Returns:
        `방금`, `3시간 전`, `어제`, `5일 전`, `3개월 전` 중 하나
    """
    seconds = max(0, int((now - moment).total_seconds()))
    if seconds < 3600:
        return "방금"
    if seconds < 86400:
        return f"{seconds // 3600}시간 전"
    days = seconds // 86400
    if days == 1:
        return "어제"
    if days < 60:
        return f"{days}일 전"
    return f"{days // 30}개월 전"


def _checked(db: Session, now: datetime) -> str:
    """릴리스 소스를 마지막으로 확인한 시각을 `N분 전` 글로 돌려준다. 기록이 없으면 빈 문자열이다."""
    moment = feed_status_crud.latest_ok(db, "release")
    return _ago(moment, now) if moment else ""


def build_home(
    db: Session, tool: str, tab: str, category: str, topic: str, q: str, page: int = 1, now: datetime | None = None
) -> dict:
    """홈 화면에 필요한 값을 모두 만든다.

    Args:
        db: DB 세션
        tool: 소스 slug 필터
        tab: `all`, `imp`, `risk`
        category: 유형 필터
        topic: 주제 필터
        q: 검색어
        page: 쪽 번호. 전체 쪽 수를 넘으면 마지막 쪽으로 본다
        now: 기준 시각. 비우면 현재 시각
    Returns:
        템플릿에 넘길 값
    """
    now = now or datetime.now(KST)
    tab = tab if tab in ("imp", "risk") else "all"
    params = {
        key: value
        for key, value in (("tool", tool), ("tab", tab if tab != "all" else ""), ("type", category), ("topic", topic), ("q", q))
        if value
    }

    since = now - timedelta(days=WEEK_BOX_DAYS)
    sources = item_crud.list_sources(db)
    per_source = entry_crud.count_entries_by_source(db)
    latest = entry_crud.latest_per_source(db, since)
    tools = []
    for s in sources:
        entry, recent = latest.get(s.id, (None, 0))
        tools.append(
            {
                "slug": s.slug,
                "name": s.name,
                "count": per_source.get(s.id, 0),
                "active": s.slug == tool,
                "href": _url(params, tool=s.slug),
                "version": (entry.version or entry.title) if entry else "",
                "ago": _ago(entry.published_at, now) if entry else "",
                "recent": recent,
                "ready": entry is not None,
                "ts": entry.published_at.timestamp() if entry else 0,
            }
        )
    status_tools = sorted(tools, key=lambda t: -t["ts"])

    week_counts = entry_crud.count_entries_by_category_since(db, since, now)
    week = {
        "label": f"{since:%m-%d} ~ {now:%m-%d}",
        "news": news_crud.count_since(db, since),
        "pending": item_crud.count_pending_items(db),
        "checked": _checked(db, now),
        "cats": [
            {
                "key": key,
                "symbol": CATEGORIES[key][0],
                "label": CATEGORIES[key][1],
                "count": week_counts.get(key, 0),
                "active": key == category,
                "href": _url(params, type=key),
            }
            for key in ("feature", "bugfix", "breaking", "security")
        ],
    }

    highlights = []
    latest_news = []
    deadline_soon = []
    if not (tool or tab != "all" or category or topic or q):
        deadline_soon = build_soon(db)
        latest_news = [
            {"company": n.company, "title": n.title_ko or n.title, "ago": _ago(n.published_at, now), "url": n.url if n.url.startswith(("https://", "http://")) else "#"}
            for n in news_crud.list_news(db, "", "all", "", NEWS_HOME_COUNT)
        ]
        for item, entry, source in item_crud.list_highlights(db, HIGHLIGHTS):
            symbol, label = CATEGORIES.get(item.category, ("", ""))
            highlights.append(
                {
                    "summary": item.summary_ko,
                    "raw": item.raw_text,
                    "category": item.category,
                    "symbol": symbol,
                    "type_label": label,
                    "importance": item.importance or 0,
                    "topic": item.topic,
                    "name": source.name,
                    "version": entry.version or entry.title,
                    "ago": _ago(entry.published_at, now),
                    "url": entry.url if entry.url.startswith(("https://", "http://")) else "#",
                    "path": release_path(source.slug, entry),
                }
            )

    no_tab = {k: v for k, v in params.items() if k != "tab"}
    tabs = [
        {
            "label": label,
            "short": short,
            "count": entry_crud.count_entries(db, tool, key, category, topic, q),
            "active": key == tab,
            "href": _url(no_tab, tab=None if key == "all" else key),
        }
        for key, label, short in TABS
    ]

    topics = [{"name": t, "active": t == topic, "href": _url(params, topic=t)} for t in TOPICS]

    rows = []
    last_day = ""
    matched = next(t["count"] for t in tabs if t["active"])
    pages = max(1, ceil(matched / PAGE_SIZE))
    page = min(page, pages)
    more = _url(params, page=str(page + 1)) if page < pages else None

    entries = entry_crud.list_entries(db, tool, tab, category, topic, q, PAGE_SIZE, (page - 1) * PAGE_SIZE)
    ids = [entry.id for entry, _ in entries]
    stats = entry_crud.entry_stats(db, ids)
    shown = entry_crud.top_items(db, ids, tab, category, topic, SHOWN_ITEMS, q)
    hits = entry_crud.entry_hits(db, ids, q)
    needle = q.lower()

    for entry, source in entries:
        day = entry.published_at.astimezone(KST).strftime("%Y-%m-%d")
        stat = stats[entry.id]
        top = next((c for c in SEVERITY if c in stat["categories"]), "")
        symbol, label = CATEGORIES.get(top, ("", ""))
        items = [
            {
                "summary": item.summary_ko,
                "raw": item.raw_text,
                "hit": bool(q) and needle in f"{item.summary_ko or ''} {item.topic or ''} {item.raw_text}".lower(),
                "raw_only": bool(q)
                and needle not in f"{item.summary_ko or ''} {item.topic or ''}".lower()
                and needle in item.raw_text.lower(),
                "symbol": CATEGORIES.get(item.category, ("", ""))[0],
                "category": item.category or "",
                "importance": item.importance or 0,
                "topic": item.topic,
            }
            for item in shown[entry.id]
        ]
        lines = [i for i in items if i["summary"] or i["hit"]]
        headline = next((i["summary"] or i["raw"] for i in lines), None)
        rows.append(
            {
                "day": day,
                "show_day": day != last_day,
                "day_label": _day_label(entry.published_at, now),
                "name": source.name,
                "version": entry.version or entry.title,
                "ago": _ago(entry.published_at, now),
                "count": stat["count"],
                "done": stat["done"],
                "headline": headline,
                "lines": lines,
                "hits": hits.get(entry.id, 0),
                "hidden_count": max(0, stat["count"] - len(items)),
                "category": top,
                "symbol": symbol,
                "type_label": label,
                "cats": [
                    {"key": key, "symbol": CATEGORIES[key][0], "count": stat["categories"][key]}
                    for key in SEVERITY
                    if key in stat["categories"] and key != "other"
                ],
                "importance": stat["importance"],
                "url": entry.url if entry.url.startswith(("https://", "http://")) else "#",
                "path": release_path(source.slug, entry),
            }
        )
        last_day = day

    active = []
    if tool:
        active.append({"label": next((t["name"] for t in tools if t["active"]), tool), "href": _url(params, tool=tool)})
    if topic:
        active.append({"label": topic, "href": _url(params, topic=topic)})

    return {
        "tools": tools,
        "status_tools": status_tools,
        "total": sum(t["count"] for t in tools),
        "all_href": _url(params, tool=None),
        "week": week,
        "highlights": highlights,
        "latest_news": latest_news,
        "deadline_soon": deadline_soon,
        "tabs": tabs,
        "topics": topics,
        "topic": topic,
        "rows": rows,
        "more": more,
        "q": q,
        "hidden": {k: v for k, v in params.items() if k != "q"},
        "active": active,
        "important_min": IMPORTANT_MIN,
    }