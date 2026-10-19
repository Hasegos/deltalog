from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class News(Base):
    """제작사가 직접 낸 공식 발표 글 하나와 그 한국어 요약. 릴리스(`entry`, `item`)와 따로 둔다."""

    __tablename__ = "news"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'done', 'failed', 'skipped')", name="ck_news_status"),
        CheckConstraint("importance IS NULL OR importance BETWEEN 1 AND 5", name="ck_news_importance"),
        Index("ix_news_status_published", "status", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(30), index=True)
    feed: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    body_raw: Mapped[str] = mapped_column(Text)
    title_ko: Mapped[str | None] = mapped_column(Text)
    summary_ko: Mapped[str | None] = mapped_column(Text)
    news_type: Mapped[str | None] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(String(50))
    importance: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(10), server_default="pending")
    reason: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")