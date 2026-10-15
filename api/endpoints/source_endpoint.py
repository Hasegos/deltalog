from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.session import get_db
from schemas.source_schema import SourceResponse
from services.web import item_service

router = APIRouter()


@router.get("", response_model=list[SourceResponse])
def list_sources(db: Session = Depends(get_db)) -> list[SourceResponse]:
    """수집 소스와 소스별 항목 개수를 돌려준다.

    Args:
        db: 요청에 쓸 DB 세션
    Returns:
        소스 목록
    """
    return item_service.list_sources(db)