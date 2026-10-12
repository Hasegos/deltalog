from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class Entry(Base):
    """소스가 낸 글 하나. 릴리스는 태그 하나, 뉴스는 기사 하나다."""

    __tablename__ = "entry"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_entry_source_external"),
        CheckConstraint("kind IN ('release', 'news')", name="ck_entry_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    external_id: Mapped[str] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    url: Mapped[str] = mapped_column(Text)
    is_prerelease: Mapped[bool] = mapped_column(Boolean, server_default=false())
    body_raw: Mapped[str] = mapped_column(Text)