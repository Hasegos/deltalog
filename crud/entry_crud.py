from collections import defaultdict

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import Session, defer

from core.constant import IMPORTANT_MIN
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
        q: 검색어. 도구 이름, 버전, 제목이나 항목의 요약, 주제에서 부분 일치를 찾는다
    Returns:
        조건이 붙은 조회문
    """
    if tool:
        stmt = stmt.where(Source.slug == tool)
    conditions = _item_conditions(tab, category, topic)
    if conditions:
        stmt = stmt.where(exists().where(Item.entry_id == Entry.id, *conditions))
    if q:
        in_items = exists().where(
            Item.entry_id == Entry.id,
            Item.summary_ko.icontains(q, autoescape=True) | Item.topic.icontains(q, autoescape=True),
        )
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
    db: Session, entry_ids: list[int], tab: str, category: str, topic: str, per_entry: int
) -> dict[int, list[Item]]:
    """글마다 화면에 펼쳐 보일 항목을 중요도 높은 순으로 최대 `per_entry`개 돌려준다.

    요약이 끝난 항목이 먼저 오고, 같으면 중요도가 높은 항목, 그다음 원문 순서다. 원문(`raw_text`)은 읽지 않는다.

    Args:
        db: DB 세션
        entry_ids: 글 ID 목록
        tab, category, topic: 화면 필터 (`_item_conditions` 참고)
        per_entry: 글마다 가져올 최대 개수
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
        .options(defer(Item.raw_text))
        .order_by(Item.entry_id, ranked.c.rn)
    )
    for item in db.scalars(stmt):
        result[item.entry_id].append(item)
    return result