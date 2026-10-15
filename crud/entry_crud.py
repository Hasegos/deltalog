from collections import defaultdict
from datetime import datetime

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import Session

from core.constants.page import IMPORTANT_MIN
from models.entry_model import Entry
from models.item_model import Item
from models.source_model import Source


def existing_external_ids(db: Session, source_id: int, external_ids: list[str]) -> set[str]:
    """이미 저장된 글의 `external_id`만 골라 돌려준다.

    Args:
        db: DB 세션
        source_id: 소스 ID
        external_ids: 확인할 `external_id` 목록
    Returns:
        그중 이미 저장된 것
    """
    if not external_ids:
        return set()
    stmt = select(Entry.external_id).where(Entry.source_id == source_id, Entry.external_id.in_(external_ids))
    return set(db.scalars(stmt))


def add_entry(db: Session, entry: Entry, item_texts: list[str]) -> None:
    """글 하나와 그 항목들을 세션에 더한다. 커밋은 부르는 쪽이 한다.

    Args:
        db: DB 세션
        entry: 저장할 글
        item_texts: 항목 원문 목록. 순서대로 `seq` 1부터 붙는다
    """
    db.add(entry)
    db.flush()
    db.add_all(Item(entry_id=entry.id, seq=i, raw_text=text) for i, text in enumerate(item_texts, start=1))


def has_versions(db: Session, source_id: int) -> bool:
    """소스의 글 중 버전이 있는 글이 있는지 알려준다.

    Args:
        db: DB 세션
        source_id: 소스 ID
    Returns:
        버전이 있으면 `True`
    """
    return db.scalar(select(Entry.id).where(Entry.source_id == source_id, Entry.version != "", Entry.version.is_not(None)).limit(1)) is not None


def list_source_entries(db: Session, source_id: int, limit: int = 300) -> list[Entry]:
    """소스의 글을 게시일 최신순으로 돌려준다.

    Args:
        db: DB 세션
        source_id: 소스 ID
        limit: 최대 개수
    Returns:
        글 목록
    """
    stmt = select(Entry).where(Entry.source_id == source_id).order_by(Entry.published_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def latest_per_source(db: Session, since: datetime) -> dict[int, tuple[Entry, int]]:
    """소스마다 가장 최근 글과, `since` 이후에 나온 글 개수를 돌려준다.

    Args:
        db: DB 세션
        since: 이 시각 이후(포함)에 게시된 글을 센다
    Returns:
        소스 ID별 `(가장 최근 글, 최근 글 개수)`. 글이 하나도 없는 소스는 들어 있지 않다
    """
    newest = db.scalars(select(Entry).distinct(Entry.source_id).order_by(Entry.source_id, Entry.published_at.desc()))
    recent = dict(
        db.execute(select(Entry.source_id, func.count(Entry.id)).where(Entry.published_at >= since).group_by(Entry.source_id)).all()
    )
    return {entry.source_id: (entry, recent.get(entry.source_id, 0)) for entry in newest}


def count_entries_by_category_since(db: Session, since: datetime, until: datetime) -> dict[str, int]:
    """지정한 기간에 게시된 글을 유형별로 센다. 그 유형의 항목이 하나라도 있는 글을 센다.

    Args:
        db: DB 세션
        since: 이 시각 이후(포함)에 게시된 글만 센다
        until: 이 시각 이전(포함)에 게시된 글만 센다. 미래 날짜 글을 빼는 데 쓴다
    Returns:
        유형별 글 개수. 유형이 아직 없는(요약 전) 항목은 세지 않는다
    """
    stmt = (
        select(Item.category, func.count(func.distinct(Item.entry_id)))
        .join(Entry, Item.entry_id == Entry.id)
        .where(Entry.published_at >= since, Entry.published_at <= until, Item.category.is_not(None))
        .group_by(Item.category)
    )
    return {category: count for category, count in db.execute(stmt).all()}


def item_matches(q: str):
    """항목의 요약, 주제, 영어 원문 중 하나라도 검색어를 포함하는지 나타내는 조건을 만든다. 대소문자를 가리지 않고, 값이 비어 있어도 NULL이 아니라 참 · 거짓으로 나온다 (정렬에 쓰기 위해)."""
    return or_(
        func.coalesce(Item.summary_ko, "").icontains(q, autoescape=True),
        func.coalesce(Item.topic, "").icontains(q, autoescape=True),
        Item.raw_text.icontains(q, autoescape=True),
    )


def entry_hits(db: Session, entry_ids: list[int], q: str) -> dict[int, int]:
    """글마다 검색어와 일치하는 항목 개수를 돌려준다.

    Args:
        db: DB 세션
        entry_ids: 글 ID 목록
        q: 검색어
    Returns:
        글 ID별 일치 항목 수. 일치하는 항목이 없는 글은 들어 있지 않다
    """
    if not entry_ids or not q:
        return {}
    stmt = (
        select(Item.entry_id, func.count(Item.id))
        .where(Item.entry_id.in_(entry_ids), item_matches(q))
        .group_by(Item.entry_id)
    )
    return {entry_id: count for entry_id, count in db.execute(stmt).all()}


def _item_conditions(tab: str, category: str, topic: str) -> list:
    """항목에 걸 조건(탭, 유형, 주제)을 만든다. 조건이 없으면 빈 목록이다."""
    conditions = []
    if tab == "imp":
        conditions.append(Item.importance >= IMPORTANT_MIN)
    elif tab == "risk":
        conditions.append(Item.category.in_(("breaking", "security")))
    if category:
        conditions.append(Item.category == category)
    if topic:
        conditions.append(Item.topic == topic)
    return conditions


def _entry_filter(stmt: Select, tool: str, tab: str, category: str, topic: str, q: str) -> Select:
    """글 조회문에 화면 필터를 덧붙인다. 항목 조건은 "조건에 맞는 항목이 하나라도 있는 글"로 건다.

    Args:
        stmt: `entry`와 `source`가 조인된 조회문
        tool: 소스 slug. 빈 문자열이면 거르지 않는다
        tab: `all`, `imp`(중요), `risk`(breaking · 보안)
        category: 유형 값. 빈 문자열이면 거르지 않는다
        topic: 주제 값. 빈 문자열이면 거르지 않는다
        q: 검색어. 도구 이름, 버전, 제목이나 항목의 요약, 주제, 영어 원문에서 부분 일치를 찾는다
    Returns:
        조건이 붙은 조회문
    """
    if tool:
        stmt = stmt.where(Source.slug == tool)
    conditions = _item_conditions(tab, category, topic)
    if conditions:
        stmt = stmt.where(exists().where(Item.entry_id == Entry.id, *conditions))
    if q:
        in_items = exists().where(Item.entry_id == Entry.id, item_matches(q))
        stmt = stmt.where(
            Source.name.icontains(q, autoescape=True)
            | Entry.version.icontains(q, autoescape=True)
            | Entry.title.icontains(q, autoescape=True)
            | in_items
        )
    return stmt


def list_entries(
    db: Session, tool: str, tab: str, category: str, topic: str, q: str, limit: int, offset: int = 0
) -> list[tuple[Entry, Source]]:
    """조건에 맞는 글을 게시일 최신순으로 돌려준다.

    Args:
        db: DB 세션
        tool, tab, category, topic, q: 화면 필터 (`_entry_filter` 참고)
        limit: 한 쪽에 담을 최대 개수
        offset: 건너뛸 개수
    Returns:
        `(글, 소스)` 묶음 목록
    """
    stmt = select(Entry, Source).join(Source, Entry.source_id == Source.id)
    stmt = _entry_filter(stmt, tool, tab, category, topic, q)
    stmt = stmt.order_by(Entry.published_at.desc(), Entry.id.desc()).limit(limit).offset(offset)
    return [(entry, source) for entry, source in db.execute(stmt).all()]


def count_entries(db: Session, tool: str, tab: str, category: str, topic: str, q: str) -> int:
    """조건에 맞는 글 개수를 돌려준다.

    Args:
        db: DB 세션
        tool, tab, category, topic, q: 화면 필터 (`_entry_filter` 참고)
    Returns:
        글 개수
    """
    stmt = select(func.count(Entry.id)).select_from(Entry).join(Source, Entry.source_id == Source.id)
    return db.scalar(_entry_filter(stmt, tool, tab, category, topic, q)) or 0


def count_entries_by_source(db: Session) -> dict[int, int]:
    """소스별 글 개수를 돌려준다.

    Args:
        db: DB 세션
    Returns:
        소스 ID별 개수. 글이 없는 소스는 들어 있지 않다
    """
    stmt = select(Entry.source_id, func.count(Entry.id)).group_by(Entry.source_id)
    return {source_id: count for source_id, count in db.execute(stmt).all()}


def entry_stats(db: Session, entry_ids: list[int]) -> dict[int, dict]:
    """글마다 항목 개수, 요약 끝난 개수, 가장 높은 중요도, 유형별 개수를 모아 돌려준다.

    Args:
        db: DB 세션
        entry_ids: 글 ID 목록
    Returns:
        글 ID별 `{"count", "done", "importance", "categories"}`. `categories`는 유형별 개수
    """
    stats: dict[int, dict] = defaultdict(lambda: {"count": 0, "done": 0, "importance": 0, "categories": {}})
    if not entry_ids:
        return stats
    stmt = (
        select(
            Item.entry_id,
            Item.category,
            func.count(Item.id),
            func.count(Item.id).filter(Item.status == "done"),
            func.max(Item.importance),
        )
        .where(Item.entry_id.in_(entry_ids))
        .group_by(Item.entry_id, Item.category)
    )
    for entry_id, category, count, done, importance in db.execute(stmt).all():
        row = stats[entry_id]
        row["count"] += count
        row["done"] += done
        row["importance"] = max(row["importance"], importance or 0)
        if category:
            row["categories"][category] = row["categories"].get(category, 0) + count
    return stats


def top_items(
    db: Session, entry_ids: list[int], tab: str, category: str, topic: str, per_entry: int, q: str = ""
) -> dict[int, list[Item]]:
    """글마다 화면에 펼쳐 보일 항목을 중요도 높은 순으로 최대 `per_entry`개 돌려준다.

    검색어(`q`)가 있으면 일치하는 항목이 먼저 오고, 그다음은 요약이 끝난 항목, 중요도가 높은 항목, 원문 순서다. 원문(`raw_text`)도 함께 읽는다 (화면의 "원문" 비교용).

    Args:
        db: DB 세션
        entry_ids: 글 ID 목록
        tab, category, topic: 화면 필터 (`_item_conditions` 참고)
        per_entry: 글마다 가져올 최대 개수
        q: 검색어. 비어 있으면 쓰지 않는다
    Returns:
        글 ID별 항목 목록
    """
    result: dict[int, list[Item]] = defaultdict(list)
    if not entry_ids:
        return result
    ranked = (
        select(
            Item.id.label("id"),
            func.row_number()
            .over(
                partition_by=Item.entry_id,
                order_by=(
                    *((item_matches(q).desc(),) if q else ()),
                    (Item.status == "done").desc(),
                    Item.importance.desc().nulls_last(),
                    Item.seq,
                ),
            )
            .label("rn"),
        )
        .where(Item.entry_id.in_(entry_ids), *_item_conditions(tab, category, topic))
        .subquery()
    )
    stmt = (
        select(Item)
        .join(ranked, ranked.c.id == Item.id)
        .where(ranked.c.rn <= per_entry)
        .order_by(Item.entry_id, ranked.c.rn)
    )
    for item in db.scalars(stmt):
        result[item.entry_id].append(item)
    return result


def get_entry_by_key(db: Session, slug: str, key: str) -> tuple[Entry, Source] | None:
    """소스 slug와 버전(버전이 없는 글은 글 ID)으로 글 하나를 찾는다.

    Args:
        db: DB 세션
        slug: 소스 slug
        key: 버전 또는 글 ID
    Returns:
        `(글, 소스)`. 없으면 `None`. 같은 버전이 여럿이면 가장 최근 글
    """
    source = db.scalar(select(Source).where(Source.slug == slug))
    if source is None:
        return None
    entry = db.scalar(
        select(Entry).where(Entry.source_id == source.id, Entry.version == key).order_by(Entry.published_at.desc()).limit(1)
    )
    if entry is None and key.isdigit():
        entry = db.scalar(
            select(Entry).where(Entry.source_id == source.id, Entry.id == int(key), or_(Entry.version.is_(None), Entry.version == ""))
        )
    return (entry, source) if entry else None


def list_entry_items(db: Session, entry_id: int) -> list[Item]:
    """글의 항목을 순서대로 돌려준다.

    Args:
        db: DB 세션
        entry_id: 글 ID
    Returns:
        항목 목록 (`seq` 순)
    """
    return list(db.scalars(select(Item).where(Item.entry_id == entry_id).order_by(Item.seq)))


def neighbor_entries(db: Session, entry: Entry) -> tuple[Entry | None, Entry | None]:
    """같은 소스에서 바로 앞(더 오래된)과 바로 뒤(더 새로운) 글을 찾는다.

    Args:
        db: DB 세션
        entry: 기준 글
    Returns:
        `(더 오래된 글, 더 새로운 글)`. 없으면 `None`
    """
    same = Entry.source_id == entry.source_id
    older = db.scalar(select(Entry).where(same, Entry.published_at < entry.published_at).order_by(Entry.published_at.desc()).limit(1))
    newer = db.scalar(select(Entry).where(same, Entry.published_at > entry.published_at).order_by(Entry.published_at.asc()).limit(1))
    return older, newer


def list_summarized_entries(db: Session) -> list[tuple[Entry, Source]]:
    """요약이 끝난 항목이 하나라도 있는 글을 최신순으로 돌려준다 (사이트맵용).

    Args:
        db: DB 세션
    Returns:
        `(글, 소스)` 목록
    """
    has_done = exists().where(Item.entry_id == Entry.id, Item.status == "done")
    stmt = select(Entry, Source).join(Source, Source.id == Entry.source_id).where(has_done).order_by(Entry.published_at.desc())
    return [(entry, source) for entry, source in db.execute(stmt).all()]


def latest_published_per_source(db: Session) -> dict[int, datetime]:
    """소스마다 가장 최근 글의 게시일을 돌려준다 (사이트맵의 `lastmod`용).

    Args:
        db: DB 세션
    Returns:
        소스 ID별 가장 최근 게시일
    """
    stmt = select(Entry.source_id, func.max(Entry.published_at)).group_by(Entry.source_id)
    return {source_id: moment for source_id, moment in db.execute(stmt).all()}