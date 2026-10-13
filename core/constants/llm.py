# ──────────────────────────────────────
# 1. 요약 호출
# ──────────────────────────────────────
# 프롬프트를 고치면 PROMPT_VERSION도 올린다 (`item.prompt_version`에 기록된다).
# 이전 버전으로 요약된 항목은 다음 `summarize`에서 다시 요약된다.
PROMPT_VERSION = "v3"
BATCH_SIZE = 8
MAX_ITEM_CHARS = 700
SUMMARY_MAX_CHARS = 120