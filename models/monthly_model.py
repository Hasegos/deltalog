from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class MonthlyDraft(Base):
    """한 달(한국 시간)의 월간 리포트 초안. 숫자(`stats`)는 만든 시점에 고정하고, 제목 후보 · 흐름 · 고른 변경 · 할 일(`draft`)은 Gemini가 쓴다. 운영자가 고쳐 쓰는 재료일 뿐 그대로 공개하지 않는다."""

    __tablename__ = "monthly_draft"

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    stats: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    draft: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())