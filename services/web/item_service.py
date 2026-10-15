from math import ceil

from sqlalchemy.orm import Session

from core.constants.page import PAGE_SIZE
from crud import item_crud
from schemas.item_schema import ItemListResponse, ItemResponse
from schemas.source_schema import SourceResponse


def list_page(
    db: Session, tool: str, tab: str, category: str, topic: str, q: str, page: int
) -> ItemListResponse:
    """조건에 맞는 항목 한 쪽을 만든다. 쪽 번호가 범위를 넘으면 마지막 쪽으로 본다.

    Args:
        db: DB 세션
        tool, tab, category, topic, q: 화면 필터 (`item_crud._filter` 참고)
        page: 쪽 번호 (1부터)
    Returns:
        항목 목록과 전체 개수, 쪽 정보
    """
    total = item_crud.count_items(db, tool, tab, category, topic, q)
    pages = max(1, ceil(total / PAGE_SIZE))
    page = min(page, pages)
    rows = item_crud.list_items(db, tool, tab, category, topic, q, PAGE_SIZE, (page - 1) * PAGE_SIZE)
    items = [
        ItemResponse(
            id=item.id,
            source=source.slug,
            version=entry.version,
            title=entry.title,
            url=entry.url,
            published_at=entry.published_at,
            category=item.category,
            topic=item.topic,
            importance=item.importance,
            summary_ko=item.summary_ko,
            status=item.status,
        )
        for item, entry, source in rows
    ]
    return ItemListResponse(items=items, total=total, page=page, pages=pages, page_size=PAGE_SIZE)


def list_sources(db: Session) -> list[SourceResponse]:
    """소스별 이름, 종류, 항목 개수를 만든다.

    Args:
        db: DB 세션
    Returns:
        소스 목록
    """
    counts = item_crud.count_items_by_source(db)
    return [
        SourceResponse(slug=s.slug, name=s.name, kind=s.kind, count=counts.get(s.id, 0))
        for s in item_crud.list_sources(db)
    ]