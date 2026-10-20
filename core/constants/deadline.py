# ──────────────────────────────────────
# 종료 일정 (모델 · API 폐기 안내 문서)
# ──────────────────────────────────────
# 제공사가 공식 문서에 표로 모아 두는 폐기 일정 페이지. 페이지 내용이 바뀐 때만 Gemini로 일정을 뽑는다.
DEADLINE_SOURCES = [
    {"slug": "anthropic-models", "provider": "Anthropic", "url": "https://platform.claude.com/docs/en/about-claude/model-deprecations"},
    {"slug": "openai-api", "provider": "OpenAI", "url": "https://developers.openai.com/api/docs/deprecations"},
    {"slug": "gemini-api", "provider": "Google", "url": "https://ai.google.dev/gemini-api/docs/deprecations"},
]
DEADLINE_PROVIDERS = ["Anthropic", "OpenAI", "Google"]
DEADLINE_KINDS = {"model": "모델", "api": "API", "feature": "기능", "other": "기타"}
DEADLINE_PROMPT_VERSION = "d1"
DEADLINE_CHUNK_CHARS = 7000
DEADLINE_PAST_DAYS = 30
DEADLINE_SOON_DAYS = 30
DEADLINE_HOME_COUNT = 3
DEADLINE_SUMMARY_MAX = 120
DEADLINE_CHART_WEEKS = 12    # 종료 일정 막대 그래프가 보여줄 앞으로의 주 수