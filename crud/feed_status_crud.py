from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.constants.status import ALERT_AFTER_FAILURES
from models.feed_status_model import FeedStatus


def record(db: Session, slug: str, label: str, group: str, ok: bool, error: str | None = None) -> str | None:
    """수집 한 번의 결과를 기록한다. 성공하면 실패 횟수를 0으로 되돌리고, 실패하면 1 올린다. 커밋은 부르는 쪽이 한다.

    Args:
        db: DB 세션
        slug: 수집 대상 slug
        label: 화면에 보일 이름
        group: 묶음 (`release`, `news`, `deadline`)
        ok: 성공했는지
        error: 실패했을 때 오류 종류 이름
    Returns:
        알려야 할 전환. 연속 실패가 `ALERT_AFTER_FAILURES`번에 이르면 `down`, 알린 뒤 다시 성공하면 `up`, 그 밖에는 `None`
    """
    now = datetime.now(timezone.utc)
    row = db.get(FeedStatus, slug)
    if row is None:
        row = FeedStatus(slug=slug, label=label, group_name=group, last_try_at=now, failures=0, alerted=False)
        db.add(row)
    row.label, row.group_name, row.last_try_at = label, group, now
    if ok:
        row.last_ok_at, row.failures, row.error = now, 0, None
        if row.alerted:
            row.alerted = False
            return "up"
        return None
    row.failures = (row.failures or 0) + 1
    row.error = error
    if row.failures >= ALERT_AFTER_FAILURES and not row.alerted:
        row.alerted = True
        return "down"
    return None


def list_all(db: Session) -> list[FeedStatus]:
    """모든 수집 대상의 마지막 결과를 묶음, 이름 순으로 돌려준다."""
    return list(db.scalars(select(FeedStatus).order_by(FeedStatus.group_name, FeedStatus.label)))


def latest_ok(db: Session, group: str) -> datetime | None:
    """묶음에서 가장 최근에 수집에 성공한 시각을 돌려준다. 기록이 없으면 `None`."""
    return db.scalar(select(func.max(FeedStatus.last_ok_at)).where(FeedStatus.group_name == group))
