from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db.session import get_db
from schemas.release_schema import ReleaseDetailResponse, ReleaseResponse
from services.web import release_service

router = APIRouter()


@router.get("/{slug}", response_model=list[ReleaseResponse])
def list_releases(slug: str, limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)) -> list[dict]:
    """도구의 릴리스를 게시일 최신순으로 돌려준다.

    Args:
        slug: 소스 slug
        limit: 최대 개수
        db: 요청에 쓸 DB 세션
    Returns:
        릴리스 목록
    Raises:
        HTTPException: 그런 도구가 없을 때 (404)
    """
    releases = release_service.list_releases_json(db, slug, limit)
    if releases is None:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다")
    return releases


@router.get("/{slug}/{key}", response_model=ReleaseDetailResponse)
def get_release(slug: str, key: str, db: Session = Depends(get_db)) -> dict:
    """릴리스 하나와 그 항목 전체를 돌려준다.

    Args:
        slug: 소스 slug
        key: 버전 (버전이 없는 글은 글 ID)
        db: 요청에 쓸 DB 세션
    Returns:
        릴리스와 항목
    Raises:
        HTTPException: 그런 릴리스가 없을 때 (404)
    """
    release = release_service.release_json(db, slug, key)
    if release is None:
        raise HTTPException(status_code=404, detail="릴리스를 찾을 수 없습니다")
    return release