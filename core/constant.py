from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))

CATEGORIES = {
    "feature": ("+", "신기능"),
    "bugfix": ("~", "수정"),
    "breaking": ("!", "breaking"),
    "security": ("◆", "보안"),
    "other": ("·", "기타"),
}

TOPICS = ["에이전트", "MCP·플러그인", "훅", "보안·권한", "성능", "UI"]

SOURCES = [
    {"slug": "claude-code", "name": "Claude Code", "kind": "github_release", "repo": "anthropics/claude-code"},
    {"slug": "codex", "name": "Codex", "kind": "github_release", "repo": "openai/codex"},
    {"slug": "gemini-cli", "name": "Gemini CLI", "kind": "github_release", "repo": "google-gemini/gemini-cli"},
    {"slug": "vscode", "name": "VS Code", "kind": "rss", "feed_url": "https://code.visualstudio.com/feed.xml"},
    {"slug": "cursor", "name": "Cursor", "kind": "rss", "feed_url": "https://cursor.com/changelog/rss.xml"},
    {"slug": "android-studio", "name": "Android Studio", "kind": "html", "feed_url": "https://developer.android.com/studio/releases"},
    {"slug": "jetbrains", "name": "JetBrains", "kind": "html", "feed_url": "https://www.jetbrains.com/idea/whatsnew/"},
]

PAGE_SIZE = 20
SPARK_WEEKS = 8
MIN_WEEK = -52
IMPORTANT_MIN = 4