from sqlalchemy import CheckConstraint, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class Item(Base):
    """요약 단위 하나. 릴리스는 본문의 항목 하나, 뉴스는 기사 하나가 들어간다."""

    __tablename__ = "item"
    __table_args__ = (
        UniqueConstraint("entry_id", "seq", name="uq_item_entry_seq"),
        CheckConstraint(
            "category IS NULL OR category IN ('feature', 'bugfix', 'breaking', 'security', 'other')",
            name="ck_item_category",
        ),
        CheckConstraint(
            "importance IS NULL OR importance BETWEEN 1 AND 5", name="ck_item_importance"
        ),
        CheckConstraint("status IN ('pending', 'done', 'failed')", name="ck_item_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("entry.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(String(50))
    importance: Mapped[int | None] = mapped_column(SmallInteger)
    summary_ko: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="pending", index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")