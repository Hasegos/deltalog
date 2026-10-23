from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from core.config import settings
from core.constants.page import KST
from core.constants.status import ALERT_AFTER_FAILURES, STALE_FACTOR, STATUS_GROUPS
from crud import feed_status_crud, item_crud, news_crud
from services.collector import price_check_service
from services.web.home_service import _ago


def _interval(group: str) -> int:
    """묶음의 정상 수집 주기(분)를 돌려준다."""
    return {"release": settings.POLL_INTERVAL_MIN, "news": settings.NEWS_POLL_INTERVAL_MIN, "deadline": settings.DEADLINE_POLL_INTERVAL_MIN}.get(group, 60)


def _price(now: datetime) -> dict | None:
    """가격 자동 대조의 마지막 결과를 화면 값으로 만든다. 아직 한 번도 돌지 않았으면 `None`이다."""
    last = price_check_service.latest()
    if last["checked_at"] is None:
        return None
    rows = [
        {"provider": provider, "checked": r["checked"], "error": r["error"], "issues": r["items"], "state": "error" if r["error"] else "stale" if r["items"] else "ok"}
        for provider, r in last["providers"].items()
    ]
    return {"checked": _ago(last["checked_at"], now), "interval": settings.PRICE_CHECK_INTERVAL_MIN, "rows": rows, "bad": sum(r["state"] != "ok" for r in rows)}


def build_status(db: Session, now: datetime | None = None) -> dict:
    """수집 현황 화면에 필요한 값을 만든다.

    상태는 연속 실패가 `ALERT_AFTER_FAILURES`번 이상이면 `error`, 마지막 성공이 정상 주기의 `STALE_FACTOR`배보다 오래됐으면 `stale`, 아니면 `ok`다.

    Args:
        db: DB 세션
        now: 기준 시각. 비우면 현재 시각
    Returns:
        템플릿에 넘길 값
    """
    now = now or datetime.now(KST)
    groups = {key: [] for key in STATUS_GROUPS}
    bad = 0
    for row in feed_status_crud.list_all(db):
        if row.group_name not in groups:
            continue
        limit = timedelta(minutes=_interval(row.group_name) * STALE_FACTOR)
        if row.failures >= ALERT_AFTER_FAILURES:
            state = "error"
        elif row.last_ok_at is None or now - row.last_ok_at > limit:
            state = "stale"
        else:
            state = "ok"
        bad += state != "ok"
        groups[row.group_name].append(
            {
                "label": row.label,
                "state": state,
                "state_label": {"ok": "정상", "stale": "지연", "error": "오류"}[state],
                "checked": _ago(row.last_ok_at, now) if row.last_ok_at else "기록 없음",
                "failures": row.failures,
            }
        )
    return {
        "groups": [{"title": STATUS_GROUPS[key], "interval": _interval(key), "rows": rows} for key, rows in groups.items() if rows],
        "price": _price(now),
        "bad": bad,
        "pending_items": item_crud.count_pending_items(db),
        "pending_news": news_crud.count_pending(db),
    }