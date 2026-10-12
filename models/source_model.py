from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class Source(Base):
    """수집 대상 하나. 소스 추가는 이 테이블에 행을 넣는 것으로 끝낸다."""

    __tablename__ = "source"
    __table_args__ = (
        CheckConstraint("kind IN ('github_release', 'rss', 'html')", name="ck_source_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))
    repo: Mapped[str | None] = mapped_column(String(200))
    feed_url: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    include_prerelease: Mapped[bool] = mapped_column(Boolean, server_default=false())