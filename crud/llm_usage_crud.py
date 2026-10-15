from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models.llm_usage_model import LlmUsage

PACIFIC = ZoneInfo("America/Los_Angeles")


def today() -> date:
    """Google 한도 초기화 기준(태평양 시간)의 오늘 날짜를 돌려준다."""
    return datetime.now(PACIFIC).date()


def calls_today(db: Session, provider: str) -> int:
    """제공자의 오늘 호출 수를 돌려준다.

    Args:
        db: DB 세션
        provider: `gemini` 등
    Returns:
        오늘 호출 수. 기록이 없으면 0
    """
    return db.scalar(select(LlmUsage.calls).where(LlmUsage.day == today(), LlmUsage.provider == provider)) or 0


def add_call(db: Session, provider: str) -> None:
    """제공자의 오늘 호출 수를 1 올리고 바로 커밋한다. 호출이 실패해도 한도에는 센다.

    Args:
        db: DB 세션
        provider: `gemini` 등
    """
    stmt = insert(LlmUsage).values(day=today(), provider=provider, calls=1)
    db.execute(stmt.on_conflict_do_update(index_elements=["day", "provider"], set_={"calls": LlmUsage.calls + 1}))
    db.commit()