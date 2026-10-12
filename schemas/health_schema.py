from pydantic import BaseModel


class HealthResponse(BaseModel):
    """`/health` 응답."""

    status: str
    db: str
