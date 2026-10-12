from datetime import datetime, time, timedelta
from math import ceil
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from core.constant import CATEGORIES, IMPORTANT_MIN, KST, PAGE_SIZE, TOPICS
from crud import item_crud

WEEKDAYS = "월화수목금토일"
TABS = [("all", "전체", "전체"), ("imp", "중요 4+", "중요"), ("risk", "breaking · 보안", "주의")]


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


def _page_numbers(page: int, pages: int) -> list[int | None]:
    """쪽 번호 목록을 만든다. 첫 쪽, 끝 쪽, 현재 쪽 앞뒤 2쪽만 넣고 건너뛴 곳은 `None`으로 둔다.

    Args:
        page: 현재 쪽
        pages: 전체 쪽 수
    Returns:
        쪽 번호와 생략 표시(`None`)가 섞인 목록
    """
    shown = sorted({1, pages, *range(max(1, page - 2), min(pages, page + 2) + 1)})
    result: list[int | None] = []
    for n in shown:
        if result and n - result[-1] > 1:
            result.append(None)
        result.append(n)
    return result


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

    sources = item_crud.list_sources(db)
    per_source = item_crud.count_items_by_source(db)
    tools = [
        {
            "slug": s.slug,
            "name": s.name,
            "count": per_source.get(s.id, 0),
            "active": s.slug == tool,
            "href": _url(params, tool=s.slug),
        }
        for s in sources
    ]

    start = _week_start(now)
    week_counts = item_crud.count_categories_since(db, start, now)
    week = {
        "label": f"{start:%m-%d} ({WEEKDAYS[start.weekday()]}) ~",
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

    no_tab = {k: v for k, v in params.items() if k != "tab"}
    tabs = [
        {
            "label": label,
            "short": short,
            "count": item_crud.count_items(db, tool, key, category, topic, q),
            "active": key == tab,
            "href": _url(no_tab, tab=None if key == "all" else key),
        }
        for key, label, short in TABS
    ]

    topics = [{"name": t, "active": t == topic, "href": _url(params, topic=t)} for t in TOPICS]

    rows = []
    last_date = ""
    matched = next(t["count"] for t in tabs if t["active"])
    pages = max(1, ceil(matched / PAGE_SIZE))
    page = min(page, pages)
    pager = {
        "page": page,
        "pages": pages,
        "prev": _url(params, page=str(page - 1) if page > 2 else None) if page > 1 else None,
        "next": _url(params, page=str(page + 1)) if page < pages else None,
        "numbers": [
            None if n is None else {"n": n, "on": n == page, "href": _url(params, page=str(n) if n > 1 else None)}
            for n in _page_numbers(page, pages)
        ],
    }

    for item, entry, source in item_crud.list_items(db, tool, tab, category, topic, q, PAGE_SIZE, (page - 1) * PAGE_SIZE):
        date = entry.published_at.astimezone(KST).strftime("%m-%d")
        symbol, label = CATEGORIES.get(item.category, ("", ""))
        rows.append(
            {
                "date": date,
                "show_date": date != last_date,
                "name": source.name,
                "version": entry.version or entry.title,
                "summary": item.summary_ko,
                "status": item.status,
                "category": item.category or "",
                "symbol": symbol,
                "type_label": label,
                "importance": item.importance or 0,
                "topic": item.topic,
                "url": entry.url if entry.url.startswith(("https://", "http://")) else "#",
            }
        )
        last_date = date

    active = []
    if tool:
        active.append({"label": next((t["name"] for t in tools if t["active"]), tool), "href": _url(params, tool=tool)})
    if topic:
        active.append({"label": topic, "href": _url(params, topic=topic)})

    return {
        "tools": tools,
        "total": sum(t["count"] for t in tools),
        "all_href": _url(params, tool=None),
        "week": week,
        "tabs": tabs,
        "topics": topics,
        "topic": topic,
        "rows": rows,
        "pager": pager,
        "q": q,
        "hidden": {k: v for k, v in params.items() if k != "q"},
        "active": active,
        "important_min": IMPORTANT_MIN,
    }