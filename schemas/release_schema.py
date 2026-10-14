from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReleaseItemResponse(BaseModel):
    """릴리스에 속한 변경 항목 하나."""

    model_config = ConfigDict(from_attributes=True)

    seq: int
    category: str | None
    topic: str | None
    importance: int | None
    summary_ko: str | None
    raw_text: str
    status: str


class ReleaseResponse(BaseModel):
    """릴리스 하나. `page`는 사람이 보는 상세 페이지 경로다."""

    tool: str
    version: str
    title: str
    published_at: datetime
    url: str
    prerelease: bool
    item_count: int
    page: str


class ReleaseDetailResponse(ReleaseResponse):
    """릴리스 하나와 그 항목 전체."""

    items: list[ReleaseItemResponse]