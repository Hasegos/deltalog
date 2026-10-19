from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from core.constants.deadline import DEADLINE_KINDS, DEADLINE_PAST_DAYS, DEADLINE_PROVIDERS, DEADLINE_SOON_DAYS
from core.constants.page import KST
from crud import deadline_crud
from models.deadline_model import Deadline

WEEKDAYS = "월화수목금토일"


def _ymd(day: date) -> str:
    return f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"


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


def _escape(text: str) -> str:
    """iCalendar 글 값에서 `\\`, `;`, `,`, 줄바꿈을 이스케이프한다."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCalendar 줄을 75바이트 안으로 접는다. 한글 글자는 중간에서 자르지 않는다."""
    out, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 74:
            out.append(current)
            current, size = " ", 1
        current += char
        size += width
    out.append(current)
    return "\r\n".join(out)


def render_ics(db: Session, base: str, now: datetime | None = None) -> str:
    """종료 일정을 iCalendar(`.ics`) 문서로 만든다. 종료일에 하루 종일 일정이 하나씩 생긴다 (구독하면 캘린더에 자동으로 들어간다).

    Args:
        db: DB 세션
        base: 사이트 주소 (끝 `/` 없음)
        now: 기준 시각. 비우면 현재
    Returns:
        `\\r\\n`으로 이은 iCalendar 문서
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    host = urlsplit(base).netloc or "deltalog"
    today = now.astimezone(KST).date()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Deltalog//Deadlines//KO",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Deltalog 종료 일정",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    for item in deadline_crud.list_since(db, today - timedelta(days=DEADLINE_PAST_DAYS)):
        parts = [item.summary_ko]
        if item.replacement:
            parts.append(f"대체: {item.replacement}")
        parts.append(f"원문: {item.source_url}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:deadline-{item.id}@{host}",
            f"DTSTAMP:{now:%Y%m%dT%H%M%SZ}",
            f"DTSTART;VALUE=DATE:{item.deadline:%Y%m%d}",
            f"DTEND;VALUE=DATE:{item.deadline + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(f'[{item.provider}] {item.name} 종료')}",
            f"DESCRIPTION:{_escape(chr(10).join(parts))}",
            f"URL:{item.source_url}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"