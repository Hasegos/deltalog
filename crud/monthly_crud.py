from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.constants.monthly import MONTHLY_DEADLINE_DAYS, MONTHLY_PENDING_GRACE_DAYS
from core.constants.page import IMPORTANT_MIN, KST
from core.months import month_bounds, prev_month
from crud import weekly_crud
from models.deadline_model import Deadline
from models.entry_model import Entry
from models.item_model import Item
from models.monthly_model import MonthlyDraft
from models.news_model import News
from models.source_model import Source

OTHER_TOPIC = "기타"


def _in_month(start: datetime, end: datetime) -> tuple:
    """프리릴리스가 아닌 릴리스 글 중 그 기간에 올라온 것만 고르는 조건이다."""
    return Entry.kind == "release", Entry.is_prerelease.is_(False), Entry.published_at >= start, Entry.published_at < end


def _span(db: Session, start: datetime, end: datetime) -> dict:
    """한 기간의 도구별 릴리스 수와 요약이 끝난 항목 수, 주제별 항목 수를 센다.

    Args:
        db: DB 세션
        start: 기간 시작(포함)
        end: 기간 끝(미포함)
    Returns:
        `{"tools": {slug: {...}}, "topics": {주제: 개수}}`. breaking · 보안 · 중요 항목은 서로 따로 센 항목 수다
    """
    tools: dict[str, dict] = {}
    releases = (
        select(Source.slug, Source.name, func.count(Entry.id))
        .join(Source, Entry.source_id == Source.id)
        .where(*_in_month(start, end))
        .group_by(Source.id, Source.slug, Source.name)
    )
    for slug, name, count in db.execute(releases).all():
        tools[slug] = {"slug": slug, "name": name, "releases": count, "breaking": 0, "security": 0, "important": 0}
    items = (
        select(
            Source.slug,
            func.count(Item.id).filter(Item.category == "breaking"),
            func.count(Item.id).filter(Item.category == "security"),
            func.count(Item.id).filter(Item.importance >= IMPORTANT_MIN),
        )
        .join(Entry, Item.entry_id == Entry.id)
        .join(Source, Entry.source_id == Source.id)
        .where(Item.status == "done", *_in_month(start, end))
        .group_by(Source.slug)
    )
    for slug, breaking, security, important in db.execute(items).all():
        if slug in tools:
            tools[slug].update(breaking=breaking, security=security, important=important)
    topic_rows = (
        select(Item.topic, func.count(Item.id))
        .join(Entry, Item.entry_id == Entry.id)
        .where(Item.status == "done", Item.category.in_(("feature", "breaking")), *_in_month(start, end))
        .group_by(Item.topic)
    )
    topics: dict[str, int] = {}
    for topic, count in db.execute(topic_rows).all():
        key = (topic or "").strip() or OTHER_TOPIC
        topics[key] = topics.get(key, 0) + count
    return {"tools": tools, "topics": topics}


def stats(db: Session, month: date, today: date | None = None) -> dict:
    """한 달(한국 시간 1일 0시 ~ 다음 달 1일 0시)의 월간 리포트 숫자를 모은다. 지난달 값을 함께 센다.

    릴리스는 프리릴리스를 뺀 `release` 글이고, 항목은 요약이 끝난(`done`) 것만 센다.

    Args:
        db: DB 세션
        month: 그 달 1일
        today: 종료 예정 일정을 셀 기준 날짜(한국 시간). 비우면 오늘
    Returns:
        `month`, `releases`, `prev_releases`, `releases_delta_pct`(지난달이 0이면 `None`), `breaking`, `prev_breaking`, `security`,
        `prev_security`, `tools_active`, `by_tool`(릴리스 수 내림차순 전체), `topics`(이번 달 항목 수 내림차순), `deadlines_60d`
    """
    today = today or datetime.now(KST).date()
    now = _span(db, *month_bounds(month))
    before = _span(db, *month_bounds(prev_month(month)))
    by_tool = sorted(now["tools"].values(), key=lambda t: (-t["releases"], t["name"]))
    releases = sum(t["releases"] for t in by_tool)
    prev_releases = sum(t["releases"] for t in before["tools"].values())
    topics = [{"topic": t, "n": now["topics"].get(t, 0), "prev": before["topics"].get(t, 0)} for t in now["topics"].keys() | before["topics"].keys()]
    topics.sort(key=lambda r: (-r["n"], -r["prev"], r["topic"]))
    deadlines = db.scalar(
        select(func.count(Deadline.id)).where(Deadline.deadline >= today, Deadline.deadline <= today + timedelta(days=MONTHLY_DEADLINE_DAYS))
    )
    return {
        "month": month.strftime("%Y-%m"),
        "releases": releases,
        "prev_releases": prev_releases,
        "releases_delta_pct": round(100 * (releases - prev_releases) / prev_releases) if prev_releases else None,
        "breaking": sum(t["breaking"] for t in by_tool),
        "prev_breaking": sum(t["breaking"] for t in before["tools"].values()),
        "security": sum(t["security"] for t in by_tool),
        "prev_security": sum(t["security"] for t in before["tools"].values()),
        "tools_active": len(by_tool),
        "by_tool": by_tool,
        "topics": topics,
        "deadlines_60d": deadlines or 0,
    }


def pending_count(db: Session, month: date, now: datetime) -> int:
    """그 달에 올라온 글 중 요약을 기다리는 릴리스 항목과 소식의 합을 돌려준다. 달이 끝나고 `MONTHLY_PENDING_GRACE_DAYS`일이 지나면 더 기다리지 않으므로 0이다.

    Args:
        db: DB 세션
        month: 그 달 1일
        now: 지금 시각
    Returns:
        기다려야 할 개수
    """
    start, end = month_bounds(month)
    if now >= end + timedelta(days=MONTHLY_PENDING_GRACE_DAYS):
        return 0
    return weekly_crud.count_pending(db, start, end)


def release_items(db: Session, month: date, limit: int) -> list[tuple[Item, Entry, Source]]:
    """그 달 릴리스(프리릴리스 제외)의 요약 완료 항목 중 중요도가 높거나 breaking · 보안인 것을 중요도 순으로 돌려준다.

    Args:
        db: DB 세션
        month: 그 달 1일
        limit: 최대 개수
    Returns:
        `(항목, 글, 소스)` 목록
    """
    start, end = month_bounds(month)
    stmt = (
        select(Item, Entry, Source)
        .join(Entry, Item.entry_id == Entry.id)
        .join(Source, Entry.source_id == Source.id)
        .where(
            Item.status == "done",
            or_(Item.importance >= IMPORTANT_MIN, Item.category.in_(("breaking", "security"))),
            *_in_month(start, end),
        )
        .order_by(Item.importance.desc(), Entry.published_at.desc(), Item.id)
        .limit(limit)
    )
    return [tuple(row) for row in db.execute(stmt).all()]


def news_items(db: Session, month: date, limit: int) -> list[News]:
    """그 달 요약 완료 소식 중 중요도가 높은 것을 중요도 순으로 돌려준다."""
    start, end = month_bounds(month)
    stmt = (
        select(News)
        .where(News.status == "done", News.importance >= IMPORTANT_MIN, News.published_at >= start, News.published_at < end)
        .order_by(News.importance.desc(), News.published_at.desc(), News.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def get_draft(db: Session, month: date) -> MonthlyDraft | None:
    """그 달의 월간 리포트 초안을 돌려준다. 없으면 `None`."""
    return db.get(MonthlyDraft, month)


def save_draft(db: Session, month: date, stats: dict, draft: dict, model: str | None, prompt_version: str) -> None:
    """월간 리포트 초안을 저장한다. 같은 달이 있으면 덮어쓴다. 커밋은 부르는 쪽이 한다.

    Args:
        db: DB 세션
        month: 그 달 1일
        stats: 만든 시점에 고정한 숫자
        draft: 제목 후보 · 흐름 · 고른 변경 · 할 일
        model: 쓴 모델 이름
        prompt_version: 프롬프트 버전
    """
    row = db.get(MonthlyDraft, month)
    if row is None:
        db.add(MonthlyDraft(month=month, stats=stats, draft=draft, model=model, prompt_version=prompt_version))
        return
    row.stats, row.draft, row.model, row.prompt_version = stats, draft, model, prompt_version