from sqlalchemy import select
from sqlalchemy.orm import Session

from models.entry_model import Entry
from models.item_model import Item


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