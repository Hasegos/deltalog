from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.POOL_SIZE,
    max_overflow=settings.MAX_OVERFLOW,
    pool_recycle=settings.POOL_RECYCLE,
    pool_timeout=settings.POOL_TIMEOUT,
    pool_pre_ping=settings.POOL_PRE_PING,
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """요청 하나에 쓸 DB 세션을 열고, 요청이 끝나면 닫는다.

    Yields:
        열린 DB 세션
    """
    with SessionLocal() as session:
        yield session