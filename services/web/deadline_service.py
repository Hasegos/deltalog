from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from core.constants.deadline import DEADLINE_HOME_COUNT, DEADLINE_KINDS, DEADLINE_PAST_DAYS, DEADLINE_PROVIDERS, DEADLINE_SOON_DAYS
from core.constants.page import KST
from crud import deadline_crud
from models.deadline_model import Deadline

WEEKDAYS = "월화수목금토일"


def _ymd(day: date) -> str:
    return f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"


ECHO_CHARS = 8    # 이름을 빼고 남은 요약이 이 글자 수 이하면 이름만 되풀이한 것으로 보고 숨긴다 (예: "X가 종료된다")


def _row(item: Deadline, today: date) -> dict:
    """일정 하나를 화면에 쓸 값으로 바꾼다. `badge`는 종료까지 남은 날(`D-12`), 오늘이면 `오늘`, 지났으면 `3일 전`이다."""
    delta = (item.deadline - today).days
    badge = "오늘" if delta == 0 else f"D-{delta}" if delta > 0 else f"{-delta}일 전"
    return {
        "provider": item.provider,
        "name": item.name,
        "kind": DEADLINE_KINDS.get(item.kind, ""),
        "date": item.deadline.isoformat(),
        "date_label": _ymd(item.deadline),
        "badge": badge,
        "soon": 0 <= delta <= DEADLINE_SOON_DAYS,
        "past": delta < 0,
        "summary": item.summary_ko,
        "echo": len(item.summary_ko.replace(item.name, "").strip(" .")) <= ECHO_CHARS,
        "replacement": item.replacement or "",
        "announced": item.deprecated_on.isoformat() if item.deprecated_on else "",
        "url": item.source_url,
    }


def build_deadlines(db: Session, provider: str, today: date | None = None) -> dict:
    """종료 일정 화면에 필요한 값을 만든다. 곧 종료(`DEADLINE_SOON_DAYS`일 이내), 이후(월별), 최근 종료(`DEADLINE_PAST_DAYS`일 이내) 순으로 묶는다.

    Args:
        db: DB 세션
        provider: 제공사 필터. 목록에 없으면 거르지 않는다
        today: 기준 날짜(한국 시간). 비우면 오늘
    Returns:
        템플릿에 넘길 값
    """
    today = today or datetime.now(KST).date()
    provider = provider if provider in DEADLINE_PROVIDERS else ""
    since = today - timedelta(days=DEADLINE_PAST_DAYS)
    rows = [_row(item, today) for item in deadline_crud.list_since(db, since, provider)]
    counts = deadline_crud.count_by_provider(db, today)
    soon = [r for r in rows if r["soon"]]
    past = sorted((r for r in rows if r["past"]), key=lambda r: r["date"], reverse=True)
    later: dict[str, list[dict]] = {}
    for r in rows:
        if not r["soon"] and not r["past"]:
            later.setdefault(f"{r['date'][:4]}년 {int(r['date'][5:7])}월", []).append(r)
    sections = []
    if soon:
        sections.append({"title": f"곧 종료 · {DEADLINE_SOON_DAYS}일 이내", "rows": soon, "key": "soon"})
    sections += [{"title": title, "rows": group, "key": "later"} for title, group in later.items()]
    if past:
        sections.append({"title": f"최근 종료 · {DEADLINE_PAST_DAYS}일 이내", "rows": past, "key": "past"})
    return {
        "providers": [
            {"name": name, "count": counts.get(name, 0), "active": name == provider, "href": "/deadlines" if name == provider else f"/deadlines?provider={name}"}
            for name in DEADLINE_PROVIDERS
        ],
        "total": sum(counts.values()),
        "all_active": not provider,
        "sections": sections,
        "filtered": bool(provider),
        "upcoming": sum(1 for r in rows if not r["past"]),
    }


def build_soon(db: Session, today: date | None = None) -> list[dict]:
    """홈에 보여줄 곧 종료되는 일정(`DEADLINE_SOON_DAYS`일 이내) 중 가장 빠른 `DEADLINE_HOME_COUNT`건을 돌려준다.

    Args:
        db: DB 세션
        today: 기준 날짜(한국 시간). 비우면 오늘
    Returns:
        `_row`와 같은 값의 목록. 없으면 빈 목록
    """
    today = today or datetime.now(KST).date()
    return [_row(item, today) for item in deadline_crud.list_range(db, today, today + timedelta(days=DEADLINE_SOON_DAYS), DEADLINE_HOME_COUNT)]