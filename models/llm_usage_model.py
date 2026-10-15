from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.base_class import Base


class LlmUsage(Base):
    """제공자별 하루 호출 수. 하루는 Google의 한도 초기화 기준인 태평양 시간 자정에 바뀐다."""

    __tablename__ = "llm_usage"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, server_default="0")