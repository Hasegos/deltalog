# ──────────────────────────────────────
# 1. 뉴스 소스
# ──────────────────────────────────────
# `kind`가 없으면 RSS/Atom 피드다. 피드가 없는 제작사는 `kind`로 글 주소 목록을 얻고 글 페이지를 직접 읽는다.
# - sitemap: `url`의 sitemap.xml에서 `prefix`로 시작하는 주소(하위 경로 없음)를 `lastmod` 최신순으로 쓴다
# - index: `url`의 HTML 링크 중 `prefix`로 시작하는 주소(하위 경로 없음)를 나온 순서대로 쓴다
NEWS_FEEDS = [
    {"slug": "anthropic", "company": "Anthropic", "kind": "sitemap", "url": "https://www.anthropic.com/sitemap.xml", "prefix": "https://www.anthropic.com/news/"},
    {"slug": "cursor-blog", "company": "Cursor", "kind": "index", "url": "https://cursor.com/blog", "prefix": "https://cursor.com/blog/"},
    {"slug": "xai", "company": "xAI", "kind": "sitemap", "url": "https://x.ai/sitemap.xml", "prefix": "https://x.ai/news/"},
    {"slug": "openai", "company": "OpenAI", "url": "https://openai.com/news/rss.xml"},
    {"slug": "google-ai", "company": "Google", "url": "https://blog.google/technology/ai/rss/"},
    {"slug": "google-dev", "company": "Google", "url": "https://developers.googleblog.com/feeds/posts/default"},
    {"slug": "microsoft-vs", "company": "Microsoft", "url": "https://devblogs.microsoft.com/visualstudio/feed/"},
    {"slug": "jetbrains", "company": "JetBrains", "url": "https://blog.jetbrains.com/feed/"},
    {"slug": "jetbrains-ai", "company": "JetBrains", "url": "https://blog.jetbrains.com/ai/feed/"},
]
NEWS_COMPANIES = ["Anthropic", "OpenAI", "Google", "Microsoft", "JetBrains", "Cursor", "xAI"]


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