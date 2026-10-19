from datetime import date, timedelta

from sqlalchemy.orm import Session

from core.constants.weekly import WEEKLY_NEWS_LIMIT, WEEKLY_NEWS_MIN, WEEKLY_RELEASE_LIMIT, WEEKLY_RELEASE_MIN
from core.weeks import monday_of, week_bounds
from crud import weekly_crud
from services.web.release_service import release_path


def parse_week(text: str) -> date | None:
    """`YYYY-MM-DD` 글을 그 날이 속한 주의 월요일로 바꾼다. 형식이 틀리면 `None`이다."""
    try:
        return monday_of(date.fromisoformat(text))
    except ValueError:
        return None


def _range_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return f"{monday.month}월 {monday.day}일 ~ {sunday.month}월 {sunday.day}일"


def build_weekly(db: Session, monday: date | None) -> dict | None:
    """주간 요약 화면에 필요한 값을 만든다.

    Args:
        db: DB 세션
        monday: 보여줄 주의 월요일. `None`이면 가장 최근 주
    Returns:
        템플릿에 넘길 값. 그 주의 요약이 없으면 `None`. 요약이 하나도 없을 때 `monday`가 `None`이면 `{"digest": None}`이다
    """
    digest = weekly_crud.latest(db) if monday is None else weekly_crud.get(db, monday)
    if digest is None:
        return {"digest": None} if monday is None else None
    weeks = weekly_crud.list_weeks(db)
    start, end = week_bounds(digest.week_start)
    groups: dict[str, list[dict]] = {}
    for item, entry, source in weekly_crud.release_items(db, start, end, WEEKLY_RELEASE_MIN, WEEKLY_RELEASE_LIMIT):
        groups.setdefault(source.name, []).append(
            {"label": entry.version or entry.title, "url": release_path(source.slug, entry), "summary": item.summary_ko or "", "importance": item.importance}
        )
    news = [
        {"company": n.company, "title": n.title_ko or n.title, "summary": n.summary_ko or "", "url": n.url, "importance": n.importance}
        for n in weekly_crud.news_items(db, start, end, WEEKLY_NEWS_MIN, WEEKLY_NEWS_LIMIT)
    ]
    keys = [w.week_start for w in weeks]
    pos = keys.index(digest.week_start) if digest.week_start in keys else -1
    return {
        "digest": digest,
        "range": _range_label(digest.week_start),
        "releases": [{"name": name, "rows": rows} for name, rows in groups.items()],
        "news": news,
        "newer": keys[pos - 1].isoformat() if pos > 0 else "",
        "older": keys[pos + 1].isoformat() if 0 <= pos < len(keys) - 1 else "",
        "weeks": [
            {"key": w.week_start.isoformat(), "range": _range_label(w.week_start), "headline": w.headline, "active": w.week_start == digest.week_start}
            for w in weeks
        ],
    }