import re
from datetime import date, datetime

from core.constants.monthly import MONTHLY_MONTH_RE
from core.constants.page import KST


def parse_month(text: str) -> date | None:
    """`YYYY-MM` 글을 그 달 1일로 바꾼다. 형식이 틀리면 `None`이다."""
    if not re.fullmatch(MONTHLY_MONTH_RE, text):
        return None
    try:
        return date(int(text[:4]), int(text[5:]), 1)
    except ValueError:
        return None


def next_month(first: date) -> date:
    """다음 달 1일을 돌려준다."""
    return date(first.year + first.month // 12, first.month % 12 + 1, 1)


def prev_month(first: date) -> date:
    """지난달 1일을 돌려준다."""
    return date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)


def month_bounds(first: date) -> tuple[datetime, datetime]:
    """그 달(1일 0시 ~ 다음 달 1일 0시, 한국 시간)의 시작(포함)과 끝(미포함)을 돌려준다."""
    after = next_month(first)
    return datetime(first.year, first.month, 1, tzinfo=KST), datetime(after.year, after.month, 1, tzinfo=KST)