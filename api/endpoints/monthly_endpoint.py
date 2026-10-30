from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from core.months import parse_month
from db.session import get_db
from services.web import monthly_service

router = APIRouter()


@router.get("/draft/{month}", response_class=PlainTextResponse)
def get_draft(month: str, db: Session = Depends(get_db)) -> PlainTextResponse:
    """월간 리포트 초안을 `data/monthly/YYYY-MM.toml`에 저장할 수 있는 TOML 글로 돌려준다.

    Args:
        month: `YYYY-MM`
        db: 요청에 쓸 DB 세션
    Returns:
        TOML 글(`text/plain`). 검수 전(`reviewed = false`)이다
    Raises:
        HTTPException: 형식이 틀렸거나 아직 끝나지 않은 달일 때 (400). 달이 끝난 지 `MONTHLY_PENDING_GRACE_DAYS`일 안인데 요약 대기 항목이 남았을 때 (409)
    """
    first = parse_month(month)
    now = datetime.now(timezone.utc)
    if first is None or not monthly_service.is_finished(first, now):
        raise HTTPException(status_code=400, detail="끝난 달(YYYY-MM)만 만들 수 있습니다")
    waiting = monthly_service.pending_count(db, first, now)
    if waiting:
        raise HTTPException(status_code=409, detail=f"요약을 기다리는 항목이 {waiting}개 남아 있습니다")
    return PlainTextResponse(monthly_service.build_draft(db, first, now))