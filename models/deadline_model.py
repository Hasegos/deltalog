from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class Deadline(Base):
    """제공사가 공식 문서에 예고한 모델 · API · 기능의 종료 일정 하나."""

    __tablename__ = "deadline"
    __table_args__ = (UniqueConstraint("provider", "name", "deadline", name="uq_deadline_provider_name_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))
    deadline: Mapped[date] = mapped_column(Date, index=True)
    deprecated_on: Mapped[date | None] = mapped_column(Date)
    replacement: Mapped[str | None] = mapped_column(Text)
    summary_ko: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    source_slug: Mapped[str] = mapped_column(String(40))
    prompt_version: Mapped[str] = mapped_column(String(20))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadlinePage(Base):
    """종료 일정 문서의 마지막 확인 기록. 내용 해시가 같으면 Gemini를 다시 부르지 않는다."""

    __tablename__ = "deadline_page"

    slug: Mapped[str] = mapped_column(String(40), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(20))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))