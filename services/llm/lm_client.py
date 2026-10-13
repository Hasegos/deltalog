from time import perf_counter

import httpx

from core.config import settings
from core.logger import get_logger, log_event

logger = get_logger("llm")


class LlmUnavailable(Exception):
    """LM Studio에 닿지 못했거나 설정이 맞지 않아 요청 자체를 보낼 수 없을 때."""


def complete(messages: list[dict], schema: dict) -> str:
    """OpenAI 호환 `/chat/completions`를 불러 답 본문을 문자열로 돌려준다. HTTP만 다루고 내용은 보지 않는다.

    서버가 JSON 스키마 출력(`response_format`)을 받아들이지 않으면(400) 스키마 없이 한 번 더 보낸다.

    Args:
        messages: `{"role", "content"}` 목록
        schema: 답이 따라야 할 JSON 스키마
    Returns:
        답 본문(`choices[0].message.content`)
    Raises:
        LlmUnavailable: 주소나 모델이 비어 있거나, 서버에 닿지 못하거나, 401 · 404 · 5xx를 받았을 때
    """
    if not settings.LM_STUDIO_BASE_URL or not settings.LM_STUDIO_MODEL:
        raise LlmUnavailable("LM_STUDIO_BASE_URL과 LM_STUDIO_MODEL을 .env에 설정하세요")

    headers = {"Authorization": f"Bearer {settings.LM_STUDIO_API_KEY}"} if settings.LM_STUDIO_API_KEY else {}
    url = settings.LM_STUDIO_BASE_URL.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.LM_STUDIO_MODEL,
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE,
        "top_p": settings.LLM_TOP_P,
        "top_k": settings.LLM_TOP_K,
        "repeat_penalty": settings.LLM_REPEAT_PENALTY,
        "max_tokens": settings.LLM_MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "release_summary", "strict": True, "schema": schema},
        },
    }

    started = perf_counter()
    event = {"model": settings.LM_STUDIO_MODEL, "schema": True}
    try:
        response = httpx.post(url, json=body, headers=headers, timeout=settings.LM_STUDIO_TIMEOUT)
        if response.status_code == 400:
            del body["response_format"]
            event["schema"] = False
            response = httpx.post(url, json=body, headers=headers, timeout=settings.LM_STUDIO_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hint = {401: "LM_STUDIO_API_KEY가 없거나 틀렸습니다", 404: "LM_STUDIO_MODEL 이름이 LM Studio에 없습니다"}.get(code, "")
        log_event(logger, event="call", ok=False, http=code, ms=round((perf_counter() - started) * 1000), **event)
        raise LlmUnavailable(f"LM Studio 응답 {code} {hint}".strip()) from exc
    except httpx.HTTPError as exc:
        log_event(logger, event="call", ok=False, error=exc.__class__.__name__, ms=round((perf_counter() - started) * 1000), **event)
        raise LlmUnavailable(f"LM Studio에 닿지 못했습니다 ({exc.__class__.__name__})") from exc

    data = response.json()
    usage = data.get("usage") or {}
    log_event(
        logger,
        event="call",
        ok=True,
        http=response.status_code,
        ms=round((perf_counter() - started) * 1000),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        **event,
    )
    return data["choices"][0]["message"]["content"] or ""