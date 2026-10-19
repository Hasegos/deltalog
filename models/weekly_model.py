from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class WeeklyDigest(Base):
    """한 주(월~일, 한국 시간)의 주간 요약. 제목과 개요는 Gemini가 쓰고, 목록은 화면을 그릴 때 DB에서 다시 뽑는다."""

    __tablename__ = "weekly_digest"

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    headline: Mapped[str] = mapped_column(Text)
    overview: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())