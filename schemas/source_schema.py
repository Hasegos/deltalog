from pydantic import BaseModel


class SourceResponse(BaseModel):
    """수집 소스 하나와 그 항목 개수."""

    slug: str
    name: str
    kind: str
    count: int