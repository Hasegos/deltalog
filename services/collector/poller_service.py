from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.logger import get_logger
from crud import entry_crud
from db.session import SessionLocal
from models.entry_model import Entry
from models.source_model import Source
from services.collector import github_release_service
from services.collector.splitter_service import split_items

logger = get_logger("poller")


def poll_source(db: Session, source: Source) -> int:
    """GitHub 릴리스 소스 하나를 한 번 가져와 새 글을 저장한다.

    ETag가 같으면 아무것도 저장하지 않는다. 이미 있는 `(소스, external_id)`와, 설정이 꺼져 있으면 프리릴리스는 건너뛴다.
    저장이 실패하면 되돌리고 ETag도 갱신하지 않아 다음 번에 다시 시도한다.

    Args:
        db: DB 세션
        source: `kind`가 `github_release`인 소스
    Returns:
        새로 저장한 글 개수
    """
    result = github_release_service.fetch_releases(source.repo, source.etag, settings.GITHUB_TOKEN)
    now = datetime.now(timezone.utc)

    if result.releases is None:
        source.last_polled_at = now
        db.commit()
        logger.info("poll %s: 변경 없음 (304)", source.slug)
        return 0

    candidates = [r for r in result.releases if source.include_prerelease or not r.prerelease]
    known = entry_crud.existing_external_ids(db, source.id, [r.external_id for r in candidates])
    added = 0
    for release in candidates:
        if release.external_id in known:
            continue
        entry = Entry(
            source_id=source.id,
            kind="release",
            external_id=release.external_id,
            version=release.version,
            title=release.title,
            published_at=release.published_at,
            url=release.url,
            is_prerelease=release.prerelease,
            body_raw=release.body,
        )
        entry_crud.add_entry(db, entry, split_items(release.body, release.title))
        added += 1

    source.etag = result.etag
    source.last_polled_at = now
    db.commit()
    logger.info("poll %s: 받은 %d건, 새 글 %d건", source.slug, len(result.releases), added)
    return added


def poll_all() -> int:
    """GitHub 릴리스 소스를 모두 한 번씩 가져온다. 소스 하나가 실패해도 나머지는 계속한다.

    Returns:
        새로 저장한 글의 전체 개수
    """
    total = 0
    with SessionLocal() as db:
        sources = list(db.scalars(select(Source).where(Source.kind == "github_release").order_by(Source.id)))
        for source in sources:
            try:
                total += poll_source(db, source)
            except httpx.HTTPError as exc:
                db.rollback()
                logger.warning("poll %s: 요청 실패 (%s)", source.slug, exc.__class__.__name__)
            except Exception:
                db.rollback()
                logger.exception("poll %s: 저장 실패", source.slug)
    return total