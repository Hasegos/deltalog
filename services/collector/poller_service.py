from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.source import GITHUB_TAG_PATTERNS
from core.constants.news import NEWS_EXPIRED_REASON, NEWS_FEEDS, NEWS_MAX_AGE_DAYS, NEWS_PROMPT_VERSION
from core.logger import get_logger
from crud import entry_crud, news_crud
from db.session import SessionLocal
from models.entry_model import Entry
from models.news_model import News
from models.source_model import Source
from services.collector import (
    antigravity_service,
    dated_changelog_service,
    feed_service,
    github_release_service,
    jetbrains_service,
    news_service,
    openai_changelog_service,
    status_service,
    windsurf_service,
)
from services.collector.github_release_service import FetchResult
from services.collector.splitter_service import split_items

logger = get_logger("poller")


def poll_source(db: Session, source: Source) -> int:
    """소스 하나(GitHub 릴리스, RSS 피드, JetBrains API, Windsurf · Antigravity · OpenAI · Anthropic · Gemini API 변경 로그 페이지)를 한 번 가져와 새 글을 저장한다.

    ETag가 같으면 아무것도 저장하지 않는다. 이미 있는 `(소스, external_id)`와, 설정이 꺼져 있으면 프리릴리스는 건너뛴다.
    저장이 실패하면 되돌리고 ETag도 갱신하지 않아 다음 번에 다시 시도한다.

    Args:
        db: DB 세션
        source: `kind`가 `github_release`, `rss`, `html`인 소스
    Returns:
        새로 저장한 글 개수
    """
    result = _fetch(source)
    now = datetime.now(timezone.utc)

    if result.releases is None:
        source.last_polled_at = now
        db.commit()
        logger.info("poll %s: 변경 없음 (304)", source.slug)
        return 0

    candidates = [r for r in result.releases if source.include_prerelease or not r.prerelease]
    known = entry_crud.existing_external_ids(db, source.id, [r.external_id for r in candidates])
    added = 0
    fresh = list({r.external_id: r for r in candidates if r.external_id not in known}.values())
    if source.kind == "rss":
        feed_service.fill_bodies(source.slug, fresh)
    for release in fresh:
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


def _fetch(source: Source) -> FetchResult:
    """소스 종류에 맞는 수집기로 글 목록을 받는다.

    Args:
        source: `kind`가 `github_release`, `rss`, `html`인 소스
    Returns:
        `FetchResult`
    """
    if source.kind == "rss":
        return feed_service.fetch_feed(source.slug, source.feed_url, source.etag)
    if source.kind == "html":
        # kind는 DB 제약 때문에 html 하나를 같이 쓰고, 페이지 모양은 slug로 가른다
        if source.slug in dated_changelog_service.PAGES:
            return dated_changelog_service.fetch_releases(source.feed_url, source.slug)
        if source.slug == "openai-api":
            return openai_changelog_service.fetch_releases(source.feed_url, source.etag)
        if source.slug == "windsurf":
            return windsurf_service.fetch_releases(source.feed_url)
        if source.slug in antigravity_service.PANELS:
            return antigravity_service.fetch_releases(source.feed_url, source.name, antigravity_service.PANELS[source.slug], source.etag)
        return jetbrains_service.fetch_releases(source.feed_url, source.name)
    return github_release_service.fetch_releases(source.repo, source.etag, settings.GITHUB_TOKEN, GITHUB_TAG_PATTERNS.get(source.slug, ""))


def poll_all() -> int:
    """GitHub 릴리스, RSS, JetBrains 소스를 모두 한 번씩 가져온다. 소스 하나가 실패해도 나머지는 계속한다.

    Returns:
        새로 저장한 글의 전체 개수
    """
    total = 0
    with SessionLocal() as db:
        sources = list(db.scalars(select(Source).where(Source.kind.in_(("github_release", "rss", "html"))).order_by(Source.id)))
        for source in sources:
            try:
                total += poll_source(db, source)
                status_service.record(source.slug, source.name, "release", True)
            except httpx.HTTPError as exc:
                db.rollback()
                logger.warning("poll %s: 요청 실패 (%s)", source.slug, exc.__class__.__name__)
                status_service.record(source.slug, source.name, "release", False, exc.__class__.__name__)
            except Exception as exc:
                db.rollback()
                logger.exception("poll %s: 저장 실패", source.slug)
                status_service.record(source.slug, source.name, "release", False, exc.__class__.__name__)
    return total


def poll_news_feed(db: Session, feed: dict) -> int:
    """공식 발표 피드 하나를 한 번 가져와 새 글을 요약 대기로 저장한다. 이미 있는 주소는 건너뛰고, 저장이 실패하면 호출한 쪽이 되돌린다.

    Args:
        db: DB 세션
        feed: `NEWS_FEEDS`의 한 줄 (`slug`, `company`, `url`)
    Returns:
        새로 저장한 글 개수
    """
    if feed.get("kind"):
        urls = news_service.fetch_listing(feed)
        if urls is None:
            articles = None
        else:
            # 글 페이지는 DB에 없는 주소만 읽는다. 30일을 넘어 저장하지 않은 글은 다음에 또 읽는다 (ponytail: 주소 목록이 20개로 제한돼 있어 요청이 많지 않다)
            seen = news_crud.existing_urls(db, urls)
            articles = [a for a in (news_service.fetch_page(u) for u in urls if u not in seen) if a]
    else:
        articles = news_service.fetch_feed(feed["url"])
    if articles is None:
        logger.info("news %s: 변경 없음 (304)", feed["slug"])
        return 0
    known = news_crud.existing_urls(db, [a.url for a in articles])
    now = datetime.now(timezone.utc)
    fresh = list({a.url: a for a in articles if a.url not in known}.values())
    oldest = now - timedelta(days=NEWS_MAX_AGE_DAYS)
    for a in fresh:
        if a.published_at is None and not feed.get("kind"):
            a.published_at = news_service.page_date(a.url)
    expired = [a for a in fresh if a.published_at is not None and a.published_at < oldest]
    fresh = [a for a in fresh if a not in expired]
    news_crud.add_news(
        db,
        [
            News(company=feed["company"], feed=feed["slug"], url=a.url, title=a.title, published_at=a.published_at or now, body_raw=a.body)
            for a in fresh
        ]
        # 오래된 글은 걸러둔 글로 남겨 다음 폴링에서 글 페이지를 또 읽지 않게 한다
        + [
            News(company=feed["company"], feed=feed["slug"], url=a.url, title=a.title, published_at=a.published_at, body_raw="", status="skipped", reason=NEWS_EXPIRED_REASON, prompt_version=NEWS_PROMPT_VERSION)
            for a in expired
        ],
    )
    db.commit()
    logger.info("news %s: 받은 %d건, 새 글 %d건", feed["slug"], len(articles), len(fresh))
    return len(fresh)


def poll_news() -> int:
    """공식 발표 피드를 모두 한 번씩 가져온다. 피드 하나가 실패해도 나머지는 계속한다.

    Returns:
        새로 저장한 글의 전체 개수
    """
    total = 0
    with SessionLocal() as db:
        for feed in NEWS_FEEDS:
            label = f"{feed['company']} ({feed['slug']})"
            try:
                total += poll_news_feed(db, feed)
                status_service.record(feed["slug"], label, "news", True)
            except httpx.HTTPError as exc:
                db.rollback()
                logger.warning("news %s: 요청 실패 (%s)", feed["slug"], exc.__class__.__name__)
                status_service.record(feed["slug"], label, "news", False, exc.__class__.__name__)
            except Exception as exc:
                db.rollback()
                logger.exception("news %s: 저장 실패", feed["slug"])
                status_service.record(feed["slug"], label, "news", False, exc.__class__.__name__)
    return total