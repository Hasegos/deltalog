from datetime import timedelta, timezone

# ──────────────────────────────────────
# 1. 시간대
# ──────────────────────────────────────
KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────
# 2. 화면 · 목록
# ──────────────────────────────────────
PAGE_SIZE = 20
SHOWN_ITEMS = 10
SPARK_WEEKS = 8
IMPORTANT_MIN = 4
THIN_MAX_CHARS = 250  # 릴리스 페이지의 요약 글자 합계가 이보다 적고 최고 중요도가 THIN_MAX_IMPORTANCE 이하이면 얇은 페이지(noindex, 사이트맵 제외)
THIN_MAX_IMPORTANCE = 3
WEEK_BOX_DAYS = 7