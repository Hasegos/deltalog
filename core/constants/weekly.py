# ──────────────────────────────────────
# 주간 요약
# ──────────────────────────────────────
# 한 주(월~일, 한국 시간)가 끝나면 주요 릴리스와 소식을 모아 Gemini가 한 줄 제목과 개요를 쓴다. 목록은 DB에서 그대로 보여준다.
WEEKLY_PROMPT_VERSION = "w1"
WEEKLY_RELEASE_MIN = 4
WEEKLY_RELEASE_LIMIT = 20
WEEKLY_NEWS_MIN = 3
WEEKLY_NEWS_LIMIT = 10
WEEKLY_MIN_LINES = 3
WEEKLY_BACKFILL_WEEKS = 4
WEEKLY_PENDING_GRACE_DAYS = 3
WEEKLY_HEADLINE_MAX = 50
WEEKLY_OVERVIEW_MIN = 60
WEEKLY_OVERVIEW_MAX = 450