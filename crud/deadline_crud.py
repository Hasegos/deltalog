from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.deadline_model import Deadline, DeadlinePage


def get_page(db: Session, slug: str) -> DeadlinePage | None:
    """종료 일정 문서의 마지막 확인 기록을 돌려준다. 없으면 `None`."""
    return db.get(DeadlinePage, slug)


def save_page(db: Session, slug: str, content_hash: str, prompt_version: str, extracted: bool) -> None:
    """종료 일정 문서의 확인 기록을 저장한다. `extracted`가 참이면 이번에 일정을 뽑았다는 뜻이다. 커밋은 부르는 쪽이 한다.

    Args:
        db: DB 세션
        slug: 문서 slug
        content_hash: 문서 내용 해시
        prompt_version: 일정을 뽑을 때 쓴 프롬프트 버전
        extracted: 이번에 일정을 새로 뽑았는지
    """
    now = datetime.now(timezone.utc)
    page = db.get(DeadlinePage, slug)
    if page is None:
        db.add(DeadlinePage(slug=slug, content_hash=content_hash, prompt_version=prompt_version, checked_at=now, extracted_at=now))
        return
    page.checked_at = now
    if extracted:
        page.content_hash, page.prompt_version, page.extracted_at = content_hash, prompt_version, now


def upsert(db: Session, provider: str, rows: list[Deadline]) -> int:
    """뽑은 종료 일정을 저장한다. 같은 `(제공사, 이름, 종료일)`이 있으면 내용을 갱신하고 없으면 더한다. 커밋은 부르는 쪽이 한다.

    Args:
        db: DB 세션
        provider: 제공사 이름
        rows: 뽑은 일정
    Returns:
        새로 더한 개수
    """
    known = {(d.name, d.deadline): d for d in db.scalars(select(Deadline).where(Deadline.provider == provider))}
    now = datetime.now(timezone.utc)
    added = 0
    for row in rows:
        old = known.get((row.name, row.deadline))
        if old is None:
            db.add(row)
            known[(row.name, row.deadline)] = row
            added += 1
            continue
        old.kind, old.deprecated_on, old.replacement, old.summary_ko = row.kind, row.deprecated_on, row.replacement, row.summary_ko
        old.source_url, old.source_slug, old.prompt_version, old.last_seen_at = row.source_url, row.source_slug, row.prompt_version, now
    return added


def list_since(db: Session, since: date, provider: str = "") -> list[Deadline]:
    """종료일이 `since` 이후인 일정을 종료일 빠른 순으로 돌려준다.

    Args:
        db: DB 세션
        since: 이 날짜 이후(포함)
        provider: 제공사 필터. 빈 문자열이면 거르지 않는다
    Returns:
        일정 목록
    """
    stmt = select(Deadline).where(Deadline.deadline >= since)
    if provider:
        stmt = stmt.where(Deadline.provider == provider)
    return list(db.scalars(stmt.order_by(Deadline.deadline, Deadline.provider, Deadline.name)))


def count_by_provider(db: Session, since: date) -> dict[str, int]:
    """종료일이 `since` 이후인 일정의 제공사별 개수를 돌려준다."""
    stmt = select(Deadline.provider, func.count(Deadline.id)).where(Deadline.deadline >= since).group_by(Deadline.provider)
    return {provider: count for provider, count in db.execute(stmt).all()}


def latest_seen(db: Session) -> datetime | None:
    """가장 최근에 일정을 확인한 시각을 돌려준다. 일정이 없으면 `None`."""
    return db.scalar(select(func.max(Deadline.last_seen_at)))