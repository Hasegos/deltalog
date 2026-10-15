import secrets

from fastapi import Header, HTTPException

from core.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """`/api/*` 요청의 `X-API-Key` 헤더를 `API_KEY` 설정과 대조한다. 설정이 비어 있으면 API 전체가 꺼진다.

    키가 없거나 틀리면 404를 돌려 API가 있는지 알 수 없게 한다. 비교는 상수 시간으로 한다.

    Args:
        x_api_key: 요청 헤더 값
    Raises:
        HTTPException: API가 꺼져 있거나 키가 맞지 않을 때 (404)
    """
    if not settings.API_KEY or not x_api_key or not secrets.compare_digest(x_api_key.encode(), settings.API_KEY.encode()):
        raise HTTPException(status_code=404, detail="Not Found")