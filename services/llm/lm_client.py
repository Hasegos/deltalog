import time
from dataclasses import dataclass
from time import perf_counter

import httpx

from core.config import settings
from core.constants.llm import CONNECT_TIMEOUT
from core.logger import get_logger, log_event

logger = get_logger("llm")
_last_call = 0.0


class LlmUnavailable(Exception):
    """Gemini에 닿지 못했거나 설정이 맞지 않아 요청 자체를 보낼 수 없을 때."""


class LlmRateLimited(LlmUnavailable):
    """Gemini가 한도 초과(429)로 거절했을 때. 항목은 그대로 두고 나중에 다시 시도한다."""


class LlmBudgetExhausted(LlmUnavailable):
    """오늘 쓸 수 있는 호출 수(`GEMINI_DAILY_LIMIT`)를 모두 썼을 때."""


@dataclass
class Completion:
    """모델 답 본문과, 실제로 쓴 모델 이름."""

    content: str
    model: str


HINTS = {401: "GEMINI_API_KEY가 없거나 틀렸습니다", 403: "GEMINI_API_KEY 권한이 없습니다", 404: "GEMINI_MODEL 이름이 맞지 않습니다"}


def _throttle() -> None:
    """분당 호출 수(`GEMINI_RPM`)를 넘지 않게 앞 호출과 간격을 둔다."""
    global _last_call
    if settings.GEMINI_RPM <= 0:
        return
    wait = _last_call + 60 / settings.GEMINI_RPM + 1 - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def complete(messages: list[dict], schema: dict) -> Completion:
    """Gemini의 OpenAI 호환 `/chat/completions`를 불러 답 본문을 돌려준다. HTTP만 다루고 내용은 보지 않는다.

    서버가 JSON 스키마 출력(`response_format`)을 받아들이지 않으면(400) 스키마 없이 한 번 더 보낸다.

    Args:
        messages: `{"role", "content"}` 목록
        schema: 답이 따라야 할 JSON 스키마
    Returns:
        답 본문(`choices[0].message.content`)과 쓴 모델 이름
    Raises:
        LlmRateLimited: 429를 받았을 때
        LlmUnavailable: 키나 모델이 비어 있거나, 서버에 닿지 못하거나, 401 · 403 · 404 · 5xx를 받았을 때
    """
    if not settings.GEMINI_API_KEY or not settings.GEMINI_MODEL:
        raise LlmUnavailable("GEMINI_API_KEY와 GEMINI_MODEL을 .env에 설정하세요")
    params = {"temperature": settings.LLM_TEMPERATURE, "top_p": settings.LLM_TOP_P, "max_tokens": settings.GEMINI_MAX_TOKENS}
    if settings.GEMINI_REASONING_EFFORT:
        params["reasoning_effort"] = settings.GEMINI_REASONING_EFFORT
    url = settings.GEMINI_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.GEMINI_API_KEY}"}
    body = {
        "model": settings.GEMINI_MODEL,
        "messages": messages,
        **params,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "release_summary", "strict": True, "schema": schema},
        },
    }

    _throttle()
    started = perf_counter()
    event = {"provider": "gemini", "model": settings.GEMINI_MODEL, "schema": True}
    timeout = httpx.Timeout(settings.GEMINI_TIMEOUT, connect=CONNECT_TIMEOUT)
    try:
        response = httpx.post(url, json=body, headers=headers, timeout=timeout)
        if response.status_code == 400:
            del body["response_format"]
            event["schema"] = False
            response = httpx.post(url, json=body, headers=headers, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        log_event(logger, event="call", ok=False, http=code, ms=round((perf_counter() - started) * 1000), **event)
        if code == 429:
            raise LlmRateLimited("Gemini 한도 초과(429)") from exc
        raise LlmUnavailable(f"Gemini 응답 {code} {HINTS.get(code, '')}".strip()) from exc
    except httpx.HTTPError as exc:
        log_event(logger, event="call", ok=False, error=exc.__class__.__name__, ms=round((perf_counter() - started) * 1000), **event)
        raise LlmUnavailable(f"Gemini에 닿지 못했습니다 ({exc.__class__.__name__})") from exc

    data = response.json()
    usage = data.get("usage") or {}
    choice = data["choices"][0]
    content = choice["message"]["content"] or ""
    finish = choice.get("finish_reason")
    log_event(
        logger,
        event="call",
        ok=True,
        http=response.status_code,
        ms=round((perf_counter() - started) * 1000),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        finish=finish,
        **event,
    )
    if finish == "length":
        log_event(logger, event="truncated", chars=len(content), head=content[:300], tail=content[-300:], **event)
    return Completion(content=content, model=settings.GEMINI_MODEL)