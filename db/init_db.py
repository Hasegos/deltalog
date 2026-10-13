from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import settings
from core.constant import SOURCES
from db.base import Base, Source
from db.session import engine


def init_db() -> None:
    """`AUTO_CREATE_TABLES`가 켜져 있으면 테이블이 없을 때 만들고, `source`가 비어 있으면 릴리스 소스 7곳을 넣는다."""
    if not settings.AUTO_CREATE_TABLES:
        return
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if session.scalar(select(Source.id).limit(1)) is None:
            session.add_all(Source(**row) for row in SOURCES)
            session.commit()