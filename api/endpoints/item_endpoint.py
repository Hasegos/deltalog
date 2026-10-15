from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.session import get_db
from schemas.item_schema import ItemListResponse
from services.web import item_service

router = APIRouter()


@router.get("", response_model=ItemListResponse)
def list_items(
    tool: str = "",
    tab: Literal["all", "imp", "risk"] = "all",
    category: str = Query("", alias="type"),
    topic: str = "",
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> ItemListResponse:
    """조건에 맞는 항목을 게시일 최신순으로 한 쪽씩 돌려준다.

    Args:
        tool: 소스 slug
        tab: `all`, `imp`(중요), `risk`(breaking · 보안)
        category: 유형 (`type` 쿼리 값)
        topic: 주제
        q: 검색어
        page: 쪽 번호 (1부터)
        db: 요청에 쓸 DB 세션
    Returns:
        항목 목록과 쪽 정보
    """
    return item_service.list_page(db, tool, tab, category, topic, q.strip(), page)