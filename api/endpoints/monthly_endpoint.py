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
        HTTPException: 형식이 틀렸거나 아직 끝나지 않은 달일 때 (400)
    """
    first = parse_month(month)
    now = datetime.now(timezone.utc)
    if first is None or not monthly_service.is_finished(first, now):
        raise HTTPException(status_code=400, detail="끝난 달(YYYY-MM)만 만들 수 있습니다")
    return PlainTextResponse(monthly_service.build_draft(db, first, now))