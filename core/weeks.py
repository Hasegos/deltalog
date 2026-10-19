from datetime import date, datetime, timedelta

from core.constants.page import KST


def monday_of(day: date) -> date:
    """그 날이 속한 주의 월요일을 돌려준다."""
    return day - timedelta(days=day.weekday())


def week_bounds(monday: date) -> tuple[datetime, datetime]:
    """그 주(월요일 0시 ~ 다음 월요일 0시, 한국 시간)의 시작(포함)과 끝(미포함)을 돌려준다."""
    start = datetime(monday.year, monday.month, monday.day, tzinfo=KST)
    return start, start + timedelta(days=7)