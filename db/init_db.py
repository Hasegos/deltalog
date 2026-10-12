from sqlalchemy import select
from sqlalchemy.orm import Session

from core.constant import SOURCES
from db.base import Base, Source
from db.session import engine


def init_db() -> None:
    """테이블이 없으면 만들고, `source`가 비어 있으면 릴리스 소스 7곳을 넣는다."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if session.scalar(select(Source.id).limit(1)) is None:
            session.add_all(Source(**row) for row in SOURCES)
            session.commit()