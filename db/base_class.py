from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 테이블 모델이 상속받는 부모 클래스."""