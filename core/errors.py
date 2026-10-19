from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.constants.error import API_ERROR_DETAIL, DEFAULT_ERROR, ERROR_PAGES
from core.logger import get_logger
from core.templates import templates

logger = get_logger("app")
PLAIN_SUFFIXES = (".txt", ".xml", ".ico")


def is_api(request: Request) -> bool:
    """`/api` 아래 요청인지 본다. 이 경로의 오류는 JSON으로 답한다."""
    return request.url.path.lower().startswith("/api")


def error_response(request: Request, status: int) -> Response:
    """오류 화면(`error.html`)을 돌려준다. `.txt`, `.xml`, `.ico` 경로는 화면 없이 짧은 글만 돌려준다.

    Args:
        request: 요청
        status: 응답 상태 코드
    Returns:
        오류 응답
    """
    if request.url.path.lower().endswith(PLAIN_SUFFIXES):
        return PlainTextResponse("Not Found" if status == 404 else "Error", status_code=status)
    title, message = ERROR_PAGES.get(status, DEFAULT_ERROR)
    context = {"status": status, "title": title, "message": message}
    return templates.TemplateResponse(request, "error.html", context, status_code=status)


async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
    """없는 경로, 허용하지 않는 메서드, 직접 던진 `HTTPException`을 처리한다. `/api`는 JSON, 그 밖은 오류 화면이다.

    Args:
        request: 요청
        exc: 발생한 예외
    Returns:
        오류 응답
    """
    if is_api(request):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    return error_response(request, exc.status_code)


async def validation_error(request: Request, exc: RequestValidationError) -> Response:
    """쿼리나 경로 값이 형식에 맞지 않을 때를 처리한다. `/api`는 FastAPI 기본 JSON(422), 그 밖은 400 오류 화면이다.

    Args:
        request: 요청
        exc: 발생한 예외
    Returns:
        오류 응답
    """
    if is_api(request):
        return await request_validation_exception_handler(request, exc)
    return error_response(request, 400)


async def unhandled_error(request: Request, exc: Exception) -> Response:
    """처리하지 못한 예외를 로그(스택 포함, 요청 내용 제외)에 남기고 500으로 답한다.

    Args:
        request: 요청
        exc: 발생한 예외
    Returns:
        500 응답
    """
    logger.exception("처리하지 못한 오류: %s %s", request.method, request.url.path)
    if is_api(request):
        return JSONResponse({"detail": API_ERROR_DETAIL}, status_code=500)
    return error_response(request, 500)


def register_exception_handlers(app: FastAPI) -> None:
    """앱에 전역 예외 처리를 등록한다.

    Args:
        app: 앱 인스턴스
    """
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(Exception, unhandled_error)
