# ──────────────────────────────────────
# 1. 수집 소스
# ──────────────────────────────────────
# `source` 테이블이 비어 있을 때 시작 시 넣는 값이다 (`db/init_db.py`).
SOURCES = [
    {"slug": "claude-code", "name": "Claude Code", "kind": "github_release", "repo": "anthropics/claude-code"},
    {"slug": "codex", "name": "Codex", "kind": "github_release", "repo": "openai/codex"},
    {"slug": "gemini-cli", "name": "Gemini CLI", "kind": "github_release", "repo": "google-gemini/gemini-cli"},
    {"slug": "vscode", "name": "VS Code", "kind": "rss", "feed_url": "https://code.visualstudio.com/feed.xml"},
    {"slug": "cursor", "name": "Cursor", "kind": "rss", "feed_url": "https://cursor.com/changelog/rss.xml"},
    {"slug": "android-studio", "name": "Android Studio", "kind": "html", "feed_url": "https://developer.android.com/studio/releases"},
    {"slug": "jetbrains", "name": "JetBrains", "kind": "html", "feed_url": "https://www.jetbrains.com/idea/whatsnew/"},
]