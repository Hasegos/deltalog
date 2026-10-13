from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.constants.source import SOURCES
from db.base import Base, Source
from db.session import engine

SYNC_FIELDS = ("name", "kind", "repo", "feed_url", "include_prerelease")


def init_db() -> None:
    """`AUTO_CREATE_TABLES`가 켜져 있으면 테이블을 만들고, `SOURCES`에 맞춰 `source`를 채운다. 없는 slug는 넣고 있는 slug는 값을 고친다."""
    if not settings.AUTO_CREATE_TABLES:
        return
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        existing = {s.slug: s for s in session.scalars(select(Source))}
        for row in SOURCES:
            source = existing.get(row["slug"])
            if source is None:
                session.add(Source(**row))
                continue
            for field in SYNC_FIELDS:
                setattr(source, field, row.get(field, getattr(source, field)))
        session.commit()