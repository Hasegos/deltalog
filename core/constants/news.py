# ──────────────────────────────────────
# 1. 뉴스 소스
# ──────────────────────────────────────
# 피드가 있는 제작사만 넣는다. Anthropic, Cursor, xAI는 피드가 없어 HTML 수집이 필요해 뒤로 미뤘다.
NEWS_FEEDS = [
    {"slug": "openai", "company": "OpenAI", "url": "https://openai.com/news/rss.xml"},
    {"slug": "google-ai", "company": "Google", "url": "https://blog.google/technology/ai/rss/"},
    {"slug": "google-dev", "company": "Google", "url": "https://developers.googleblog.com/feeds/posts/default"},
    {"slug": "microsoft-vs", "company": "Microsoft", "url": "https://devblogs.microsoft.com/visualstudio/feed/"},
    {"slug": "jetbrains", "company": "JetBrains", "url": "https://blog.jetbrains.com/feed/"},
    {"slug": "jetbrains-ai", "company": "JetBrains", "url": "https://blog.jetbrains.com/ai/feed/"},
]
NEWS_COMPANIES = ["OpenAI", "Google", "Microsoft", "JetBrains"]


# ──────────────────────────────────────
# 2. 뉴스 분류
# ──────────────────────────────────────
NEWS_TYPES = {
    "model": "모델",
    "product": "신제품·기능",
    "pricing": "요금·정책",
    "security": "보안",
    "partner": "파트너십",
    "other": "기타",
}
NEWS_TABS = [("all", "전체"), ("imp", "중요 4+"), ("model", "모델"), ("pricing", "요금·정책"), ("security", "보안")]


# ──────────────────────────────────────
# 3. 수집 · 요약 · 화면
# ──────────────────────────────────────
NEWS_MAX_ENTRIES = 20
NEWS_MAX_AGE_DAYS = 30
NEWS_BODY_CHARS = 3000
NEWS_PROMPT_CHARS = 1500
NEWS_BATCH_SIZE = 5
NEWS_TITLE_MAX = 90
NEWS_SUMMARY_MAX = 400
NEWS_PAGE_SIZE = 20
NEWS_PROMPT_VERSION = "n2"
HEADLINE_DAYS = 7
NEWS_HOME_COUNT = 3