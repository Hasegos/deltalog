from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.session import get_db
from schemas.health_schema import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """앱과 DB 연결 상태를 돌려준다.

    Args:
        db: 요청에 쓸 DB 세션
    Returns:
        앱과 DB가 모두 정상일 때 `status`와 `db`가 `ok`인 응답
    Raises:
        HTTPException: DB에 닿지 않을 때 503
    """
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="db unavailable") from exc
    return HealthResponse(status="ok", db="ok")
