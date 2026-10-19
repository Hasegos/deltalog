from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class FeedStatus(Base):
    """수집 대상(릴리스 소스, 소식 피드, 종료 일정 문서) 하나의 마지막 수집 결과. `/status`와 알림에 쓴다."""

    __tablename__ = "feed_status"

    slug: Mapped[str] = mapped_column(String(60), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    group_name: Mapped[str] = mapped_column(String(20))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_try_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    alerted: Mapped[bool] = mapped_column(Boolean, server_default="false")