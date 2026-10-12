from datetime import datetime

from pydantic import BaseModel


class ItemResponse(BaseModel):
    """목록의 항목 하나. 요약 전이면 `category`, `topic`, `importance`, `summary_ko`는 `None`이다."""

    id: int
    source: str
    version: str | None
    title: str
    url: str
    published_at: datetime
    category: str | None
    topic: str | None
    importance: int | None
    summary_ko: str | None
    status: str


class ItemListResponse(BaseModel):
    """항목 목록 한 쪽."""

    items: list[ItemResponse]
    total: int
    page: int
    pages: int
    page_size: int