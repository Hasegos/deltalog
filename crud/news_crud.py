from datetime import datetime, timedelta

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.orm import Session

from core.constants.news import NEWS_EXPIRED_REASON, NEWS_PROMPT_VERSION, NEWS_TYPES
from core.constants.page import IMPORTANT_MIN
from models.news_model import News


def existing_urls(db: Session, urls: list[str]) -> set[str]:
    """이미 저장된 글 주소를 돌려준다.

    Args:
        db: DB 세션
        urls: 확인할 주소
    Returns:
        그중 이미 있는 주소
    """
    return set(db.scalars(select(News.url).where(News.url.in_(urls))))


def add_news(db: Session, rows: list[News]) -> None:
    """새 글을 저장 대기로 넣는다. 커밋은 부르는 쪽이 한다.

    Args:
        db: DB 세션
        rows: 새 글
    """
    db.add_all(rows)


def list_pending(db: Session, limit: int) -> list[News]:
    """요약을 기다리는 글(`pending`, 이전 프롬프트 버전으로 처리된 `done`과 `skipped`. 오래된 글이라 걸러둔 `skipped`는 다시 요약하지 않는다)을 돌려준다. 실패한 적이 있는 글은 뒤로 미루고 나머지는 최신순이다.

    Args:
        db: DB 세션
        limit: 최대 개수
    Returns:
        글 목록
    """
    old = and_(News.status.in_(("done", "skipped")), News.prompt_version != NEWS_PROMPT_VERSION, or_(News.reason.is_(None), News.reason != NEWS_EXPIRED_REASON))
    stmt = select(News).where(or_(News.status == "pending", old)).order_by(News.attempts, News.published_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def requeue_failed(db: Session, max_attempts: int) -> int:
    """실패한 글 중 시도 횟수가 `max_attempts` 미만인 것을 `pending`으로 되돌린다.

    Args:
        db: DB 세션
        max_attempts: 이 횟수에 이른 글은 되돌리지 않는다
    Returns:
        되돌린 글 수
    """
    result = db.execute(update(News).where(News.status == "failed", News.attempts < max_attempts).values(status="pending"))
    db.commit()
    return result.rowcount


def _filter(stmt: Select, company: str, tab: str, topic: str, q: str = "") -> Select:
    """요약이 끝난 글만 남기고 화면 필터 조건을 덧붙인다.

    Args:
        stmt: `News` 조회문
        company: 제작사 이름. 빈 문자열이면 거르지 않는다
        tab: `all`, `imp`, 또는 뉴스 분류 값 (`model`, `pricing`, `security` 등)
        topic: 주제. 빈 문자열이면 거르지 않는다
        q: 검색어. 화면에 보이는 한국어 제목, 요약, 주제, 제작사에서 부분 일치를 찾는다. 빈 문자열이면 거르지 않는다
    Returns:
        조건이 붙은 조회문
    """
    stmt = stmt.where(News.status == "done")
    if company:
        stmt = stmt.where(News.company == company)
    if tab == "imp":
        stmt = stmt.where(News.importance >= IMPORTANT_MIN)
    elif tab in NEWS_TYPES:
        stmt = stmt.where(News.news_type == tab)
    if topic:
        stmt = stmt.where(News.topic == topic)
    if q:
        columns = (func.coalesce(News.title_ko, News.title), News.summary_ko, News.topic, News.company)
        stmt = stmt.where(or_(*(func.coalesce(col, "").icontains(q, autoescape=True) for col in columns)))
    return stmt


def list_news(db: Session, company: str, tab: str, topic: str, limit: int, offset: int = 0, q: str = "") -> list[News]:
    """조건에 맞는 글을 게시일 최신순으로 돌려준다.

    Args:
        db: DB 세션
        company, tab, topic: 화면 필터 (`_filter` 참고)
        limit: 한 쪽에 담을 최대 개수
        offset: 건너뛸 개수
        q: 검색어
    Returns:
        글 목록
    """
    stmt = _filter(select(News), company, tab, topic, q).order_by(News.published_at.desc(), News.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def count_news(db: Session, company: str, tab: str, topic: str, q: str = "") -> int:
    """조건에 맞는 글 개수를 돌려준다.

    Args:
        db: DB 세션
        company, tab, topic, q: 화면 필터와 검색어 (`_filter` 참고)
    Returns:
        글 개수
    """
    return db.scalar(_filter(select(func.count(News.id)), company, tab, topic, q)) or 0


def list_near(db: Session, company: str, moment: datetime, days: int, min_importance: int, limit: int) -> list[News]:
    """제작사가 `moment` 앞뒤 `days`일 안에 낸 요약 완료 소식을 중요도 높은 순, 같으면 `moment`에 가까운 순으로 돌려준다.

    Args:
        db: DB 세션
        company: 제작사 이름
        moment: 기준 시각
        days: 앞뒤로 볼 날수
        min_importance: 이 중요도 이상만
        limit: 최대 개수
    Returns:
        글 목록
    """
    span = timedelta(days=days)
    stmt = select(News).where(
        News.status == "done",
        News.company == company,
        News.importance >= min_importance,
        News.published_at >= moment - span,
        News.published_at <= moment + span,
    )
    found = list(db.scalars(stmt))
    found.sort(key=lambda n: (-(n.importance or 0), abs(n.published_at - moment)))
    return found[:limit]


def get_done(db: Session, news_id: int) -> News | None:
    """요약이 끝난 소식 하나를 ID로 찾는다.

    Args:
        db: DB 세션
        news_id: 소식 ID
    Returns:
        글. 없거나 아직 요약되지 않았으면 `None`
    """
    return db.scalar(select(News).where(News.id == news_id, News.status == "done"))


def list_done_dates(db: Session) -> list[tuple[int, datetime]]:
    """요약이 끝난 모든 소식의 `(ID, 게시 시각)`을 최신순으로 돌려준다. 사이트맵에 쓴다."""
    return [(row[0], row[1]) for row in db.execute(select(News.id, News.published_at).where(News.status == "done").order_by(News.published_at.desc()))]


def count_by_company(db: Session) -> dict[str, int]:
    """요약이 끝난 글의 제작사별 개수를 돌려준다.

    Args:
        db: DB 세션
    Returns:
        제작사 이름별 개수
    """
    stmt = select(News.company, func.count(News.id)).where(News.status == "done").group_by(News.company)
    return {company: count for company, count in db.execute(stmt).all()}


def headline(db: Session, since: datetime) -> News | None:
    """지정한 시각 이후 글 중 중요도가 가장 높고 최신인 글(중요도 5)을 돌려준다.

    Args:
        db: DB 세션
        since: 이 시각 이후(포함)에 게시된 글만 본다
    Returns:
        중요도 5인 글. 없으면 `None`
    """
    stmt = select(News).where(News.status == "done", News.importance == 5, News.published_at >= since).order_by(News.published_at.desc()).limit(1)
    return db.scalars(stmt).first()


def count_since(db: Session, since: datetime) -> int:
    """지정한 시각 이후에 게시된 요약 완료 글 개수를 돌려준다.

    Args:
        db: DB 세션
        since: 이 시각 이후(포함)
    Returns:
        글 개수
    """
    return db.scalar(select(func.count(News.id)).where(News.status == "done", News.published_at >= since)) or 0


def latest_published(db: Session) -> datetime | None:
    """요약이 끝난 글 중 가장 최근 게시 시각을 돌려준다.

    Args:
        db: DB 세션
    Returns:
        게시 시각. 글이 없으면 `None`
    """
    return db.scalar(select(func.max(News.published_at)).where(News.status == "done"))


def count_pending(db: Session) -> int:
    """요약을 기다리는(`pending`) 글 개수를 돌려준다."""
    return db.scalar(select(func.count(News.id)).where(News.status == "pending")) or 0


def list_for_feed(db: Session, companies: list[str], min_importance: int, limit: int) -> list[News]:
    """RSS에 넣을 요약이 끝난 글을 최신순으로 돌려준다.

    Args:
        db: DB 세션
        companies: 이 제작사의 글만. 비우면 모든 제작사
        min_importance: 이 중요도 이상인 글만
        limit: 최대 개수
    Returns:
        글 목록
    """
    stmt = select(News).where(News.status == "done")
    if min_importance > 1:
        stmt = stmt.where(News.importance >= min_importance)
    if companies:
        stmt = stmt.where(News.company.in_(companies))
    return list(db.scalars(stmt.order_by(News.published_at.desc(), News.id.desc()).limit(limit)))