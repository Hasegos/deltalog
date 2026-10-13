from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from core.constants.page import IMPORTANT_MIN
from models.entry_model import Entry
from models.item_model import Item
from models.source_model import Source


def _filter(
    stmt: Select, tool: str, tab: str, category: str, topic: str, q: str
) -> Select:
    """항목 조회문에 화면 필터 조건을 덧붙인다.

    Args:
        stmt: `item`, `entry`, `source`가 조인된 조회문
        tool: 소스 slug. 빈 문자열이면 거르지 않는다
        tab: `all`, `imp`(중요), `risk`(breaking · 보안)
        category: 유형 값. 빈 문자열이면 거르지 않는다
        topic: 주제 값. 빈 문자열이면 거르지 않는다
        q: 검색어. 요약, 도구 이름, 버전, 주제에서 부분 일치를 찾는다
    Returns:
        조건이 붙은 조회문
    """
    if tool:
        stmt = stmt.where(Source.slug == tool)
    if tab == "imp":
        stmt = stmt.where(Item.importance >= IMPORTANT_MIN)
    elif tab == "risk":
        stmt = stmt.where(Item.category.in_(("breaking", "security")))
    if category:
        stmt = stmt.where(Item.category == category)
    if topic:
        stmt = stmt.where(Item.topic == topic)
    if q:
        stmt = stmt.where(
            Item.summary_ko.icontains(q, autoescape=True)
            | Source.name.icontains(q, autoescape=True)
            | Entry.version.icontains(q, autoescape=True)
            | Entry.title.icontains(q, autoescape=True)
            | Item.topic.icontains(q, autoescape=True)
        )
    return stmt


def list_items(
    db: Session, tool: str, tab: str, category: str, topic: str, q: str, limit: int, offset: int = 0
) -> list[tuple[Item, Entry, Source]]:
    """조건에 맞는 항목을 게시일 최신순으로 돌려준다.

    Args:
        db: DB 세션
        tool, tab, category, topic, q: 화면 필터 (`_filter` 참고)
        limit: 한 쪽에 담을 최대 개수
        offset: 건너뛸 개수
    Returns:
        `(항목, 글, 소스)` 묶음 목록
    """
    stmt = (
        select(Item, Entry, Source)
        .join(Entry, Item.entry_id == Entry.id)
        .join(Source, Entry.source_id == Source.id)
    )
    stmt = _filter(stmt, tool, tab, category, topic, q)
    stmt = stmt.order_by(Entry.published_at.desc(), Entry.id.desc(), Item.seq).limit(limit).offset(offset)
    return [tuple(row) for row in db.execute(stmt).all()]


def count_items(db: Session, tool: str, tab: str, category: str, topic: str, q: str) -> int:
    """조건에 맞는 항목 개수를 돌려준다.

    Args:
        db: DB 세션
        tool, tab, category, topic, q: 화면 필터 (`_filter` 참고)
    Returns:
        항목 개수
    """
    stmt = (
        select(func.count(Item.id))
        .select_from(Item)
        .join(Entry, Item.entry_id == Entry.id)
        .join(Source, Entry.source_id == Source.id)
    )
    return db.scalar(_filter(stmt, tool, tab, category, topic, q)) or 0


def list_pending_items(db: Session, limit: int) -> list[tuple[Item, Entry, Source]]:
    """요약을 기다리는 항목을 최신 글부터, 글 안에서는 원문 순서로 돌려준다.

    Args:
        db: DB 세션
        limit: 최대 개수
    Returns:
        `(항목, 글, 소스)` 묶음 목록
    """
    stmt = (
        select(Item, Entry, Source)
        .join(Entry, Item.entry_id == Entry.id)
        .join(Source, Entry.source_id == Source.id)
        .where(Item.status == "pending")
        .order_by(Entry.published_at.desc(), Entry.id.desc(), Item.seq)
        .limit(limit)
    )
    return [tuple(row) for row in db.execute(stmt).all()]


def list_sources(db: Session) -> list[Source]:
    """소스를 등록 순서대로 돌려준다.

    Args:
        db: DB 세션
    Returns:
        소스 목록
    """
    return list(db.scalars(select(Source).order_by(Source.id)))


def count_items_by_source(db: Session) -> dict[int, int]:
    """소스별 항목 개수를 돌려준다.

    Args:
        db: DB 세션
    Returns:
        소스 ID별 개수. 항목이 없는 소스는 들어 있지 않다
    """
    stmt = (
        select(Entry.source_id, func.count(Item.id))
        .join(Item, Item.entry_id == Entry.id)
        .group_by(Entry.source_id)
    )
    return {source_id: count for source_id, count in db.execute(stmt).all()}


def count_categories_since(db: Session, since: datetime, until: datetime) -> dict[str, int]:
    """지정한 기간에 게시된 항목을 유형별로 센다.

    Args:
        db: DB 세션
        since: 이 시각 이후(포함)에 게시된 글의 항목만 센다
        until: 이 시각 이전(포함)에 게시된 글의 항목만 센다. 미래 날짜 글을 빼는 데 쓴다
    Returns:
        유형별 개수. 유형이 아직 없는(요약 전) 항목은 세지 않는다
    """
    stmt = (
        select(Item.category, func.count(Item.id))
        .join(Entry, Item.entry_id == Entry.id)
        .where(Entry.published_at >= since, Entry.published_at <= until, Item.category.is_not(None))
        .group_by(Item.category)
    )
    return {category: count for category, count in db.execute(stmt).all()}


def count_items_by_topic(db: Session) -> dict[str, int]:
    """주제별 항목 개수를 돌려준다.

    Args:
        db: DB 세션
    Returns:
        주제별 개수. 주제가 아직 없는(요약 전) 항목은 세지 않는다
    """
    stmt = (
        select(Item.topic, func.count(Item.id))
        .where(Item.topic.is_not(None))
        .group_by(Item.topic)
    )
    return {topic: count for topic, count in db.execute(stmt).all()}


def list_entry_times_since(db: Session, since: datetime) -> list[tuple[int, datetime]]:
    """지정한 시각 이후에 게시된 글의 소스와 게시 시각을 돌려준다.

    Args:
        db: DB 세션
        since: 이 시각 이후(포함)에 게시된 글만 돌려준다
    Returns:
        `(소스 ID, 게시 시각)` 목록
    """
    stmt = select(Entry.source_id, Entry.published_at).where(Entry.published_at >= since)
    return [(source_id, published_at) for source_id, published_at in db.execute(stmt).all()]


def list_topic_times_since(db: Session, since: datetime) -> list[tuple[str, datetime]]:
    """지정한 시각 이후에 게시된 글의 항목을 주제와 게시 시각으로 돌려준다.

    Args:
        db: DB 세션
        since: 이 시각 이후(포함)에 게시된 글의 항목만 돌려준다
    Returns:
        `(주제, 게시 시각)` 목록. 주제가 아직 없는(요약 전) 항목은 들어 있지 않다
    """
    stmt = (
        select(Item.topic, Entry.published_at)
        .join(Entry, Item.entry_id == Entry.id)
        .where(Entry.published_at >= since, Item.topic.is_not(None))
    )
    return [(topic, published_at) for topic, published_at in db.execute(stmt).all()]