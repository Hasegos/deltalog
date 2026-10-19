from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.entry_model import Entry
from models.item_model import Item
from models.news_model import News
from models.source_model import Source
from models.weekly_model import WeeklyDigest


def get(db: Session, week_start: date) -> WeeklyDigest | None:
    """그 주의 주간 요약을 돌려준다. 없으면 `None`."""
    return db.get(WeeklyDigest, week_start)


def latest(db: Session) -> WeeklyDigest | None:
    """가장 최근 주의 주간 요약을 돌려준다. 없으면 `None`."""
    return db.scalars(select(WeeklyDigest).order_by(WeeklyDigest.week_start.desc()).limit(1)).first()


def list_weeks(db: Session, limit: int = 12) -> list[WeeklyDigest]:
    """주간 요약을 최근 주부터 돌려준다."""
    return list(db.scalars(select(WeeklyDigest).order_by(WeeklyDigest.week_start.desc()).limit(limit)))


def save(db: Session, week_start: date, headline: str, overview: str, model: str | None, prompt_version: str) -> None:
    """주간 요약을 저장한다. 같은 주가 있으면 덮어쓴다. 커밋은 부르는 쪽이 한다.

    Args:
        db: DB 세션
        week_start: 그 주 월요일
        headline: 한 줄 제목
        overview: 개요
        model: 쓴 모델 이름
        prompt_version: 프롬프트 버전
    """
    row = db.get(WeeklyDigest, week_start)
    if row is None:
        db.add(WeeklyDigest(week_start=week_start, headline=headline, overview=overview, model=model, prompt_version=prompt_version))
        return
    row.headline, row.overview, row.model, row.prompt_version = headline, overview, model, prompt_version


def release_items(db: Session, start: datetime, end: datetime, min_importance: int, limit: int) -> list[tuple[Item, Entry, Source]]:
    """기간 안에 올라온 글의 요약 완료 항목 중 중요도가 높은 것을 중요도 순으로 돌려준다.

    Args:
        db: DB 세션
        start: 기간 시작(포함)
        end: 기간 끝(미포함)
        min_importance: 이 중요도 이상만
        limit: 최대 개수
    Returns:
        `(항목, 글, 소스)` 목록
    """
    stmt = (
        select(Item, Entry, Source)
        .join(Entry, Item.entry_id == Entry.id)
        .join(Source, Entry.source_id == Source.id)
        .where(Item.status == "done", Item.importance >= min_importance, Entry.published_at >= start, Entry.published_at < end)
        .order_by(Item.importance.desc(), Entry.published_at.desc(), Item.seq)
        .limit(limit)
    )
    return [tuple(row) for row in db.execute(stmt).all()]


def news_items(db: Session, start: datetime, end: datetime, min_importance: int, limit: int) -> list[News]:
    """기간 안에 올라온 요약 완료 소식 중 중요도가 높은 것을 중요도 순으로 돌려준다."""
    stmt = (
        select(News)
        .where(News.status == "done", News.importance >= min_importance, News.published_at >= start, News.published_at < end)
        .order_by(News.importance.desc(), News.published_at.desc(), News.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def count_pending(db: Session, start: datetime, end: datetime) -> int:
    """기간 안에 올라온 글 중 아직 요약을 기다리는 릴리스 항목과 소식의 합을 돌려준다."""
    items = db.scalar(
        select(func.count(Item.id))
        .join(Entry, Item.entry_id == Entry.id)
        .where(Item.status == "pending", Entry.published_at >= start, Entry.published_at < end)
    )
    news = db.scalar(select(func.count(News.id)).where(News.status == "pending", News.published_at >= start, News.published_at < end))
    return (items or 0) + (news or 0)