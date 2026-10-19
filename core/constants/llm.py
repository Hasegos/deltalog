# ──────────────────────────────────────
# 1. 요약 호출
# ──────────────────────────────────────
# 프롬프트를 고치면 PROMPT_VERSION도 올린다 (`item.prompt_version`에 기록된다).
# 이전 버전으로 요약된 항목은 다음 `summarize`에서 다시 요약된다.
PROMPT_VERSION = "v5"
MAX_ITEM_CHARS = 700
SUMMARY_MAX_CHARS = 160
# 서버에 연결하는 단계의 제한 시간(초). 읽기 제한(`GEMINI_TIMEOUT`)과 따로 짧게 둔다.
CONNECT_TIMEOUT = 5