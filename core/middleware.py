from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from core.config import settings
from core.logger import get_logger, log_event

logger = get_logger("api")


def client_ip(request: Request) -> str:
    """접속자 IP를 돌려준다. `TRUST_PROXY`가 켜져 있으면 Cloudflare가 항상 덮어써 넣는 `CF-Connecting-IP`를 쓴다 (`X-Forwarded-For`의 첫 값은 방문자가 위조할 수 있어 쓰지 않는다).

    Args:
        request: 요청
    Returns:
        IP 문자열. 알 수 없으면 `-`
    """
    if settings.TRUST_PROXY:
        real = request.headers.get("cf-connecting-ip", "").strip()
        if real:
            return real
    return request.client.host if request.client else "-"


async def trailing_slash(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """읽기 요청의 끝 `/`를 떼어 영구(301) 이동시킨다. 검색엔진이 `/news/`와 `/news`를 한 주소로 합치게 하는 용도다.

    Args:
        request: 요청
        call_next: 다음 처리
    Returns:
        이동 응답 또는 다음 처리의 응답
    """
    path = request.url.path
    if request.method in ("GET", "HEAD") and len(path) > 1 and path.endswith("/") and not path.startswith(("/api", "/static", "/mcp")):
        target = path.rstrip("/") or "/"
        return RedirectResponse(target + (f"?{request.url.query}" if request.url.query else ""), status_code=301)
    return await call_next(request)


async def metrics_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """`/metrics`를 서버 안에서 직접 오는 수집(Prometheus)에만 열고, Cloudflare를 거친 요청(`CF-Connecting-IP`가 있는 요청)에는 404를 돌려준다.

    Args:
        request: 요청
        call_next: 다음 처리
    Returns:
        응답
    """
    if request.url.path == "/metrics" and request.headers.get("cf-connecting-ip"):
        return Response(status_code=404)
    return await call_next(request)


async def access_log(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """요청 1건을 `api.log`에 남긴다. `/static`과 `/metrics` 요청은 남기지 않는다.

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
        if not request.url.path.startswith(("/static", "/metrics")):
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


async def api_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """`/api` 아래 모든 응답(404 포함)에 색인 금지와 캐시 금지 헤더를 붙인다. 끝 `/`가 있는 주소는 리다이렉트로 API 존재가 드러나지 않게 바로 404로 돌려준다.

    Args:
        request: 요청
        call_next: 다음 처리
    Returns:
        헤더가 붙은 응답
    """
    in_api = request.url.path.lower().startswith("/api")
    if in_api and request.url.path.endswith("/"):
        return Response(status_code=404, headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"})
    response = await call_next(request)
    if in_api:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Cache-Control"] = "no-store"
    return response