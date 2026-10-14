from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import Request, Response

from core.config import settings
from core.logger import get_logger, log_event

logger = get_logger("api")


def client_ip(request: Request) -> str:
    """접속자 IP를 돌려준다. `TRUST_PROXY`가 켜져 있으면 프록시가 넣은 `X-Forwarded-For`의 첫 값을 쓴다.

    Args:
        request: 요청
    Returns:
        IP 문자열. 알 수 없으면 `-`
    """
    if settings.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "-"


async def access_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """요청 1건을 `api.log`에 남긴다. `/static`과 `/healthz` 요청은 남기지 않는다.

    Args:
        request: 요청
        call_next: 다음 처리
    Returns:
        응답
    """
    started = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        if not request.url.path.startswith(("/static", "/healthz")):
            log_event(
                logger,
                ip=client_ip(request),
                method=request.method,
                path=request.url.path,
                query=request.url.query,
                status=status,
                ms=round((perf_counter() - started) * 1000),
                ua=request.headers.get("user-agent", ""),
                ref=request.headers.get("referer", ""),
            )


async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """모든 응답에 기본 보안 헤더를 붙인다. HTTPS 강제(HSTS)는 프록시가 맡는다.

    Args:
        request: 요청
        call_next: 다음 처리
    Returns:
        헤더가 붙은 응답
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response