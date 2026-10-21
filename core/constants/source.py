# ──────────────────────────────────────
# 1. 수집 소스
# ──────────────────────────────────────
# 시작 시 `source` 테이블에 맞춘다. 없는 slug는 넣고, 있는 slug는 이름, 종류, 주소, 프리릴리스 설정을 이 값으로 고친다 (`db/init_db.py`).
JETBRAINS_API = "https://data.services.jetbrains.com/products/releases"
SOURCES = [
    {"slug": "claude-code", "name": "Claude Code", "kind": "github_release", "repo": "anthropics/claude-code"},
    {"slug": "codex", "name": "Codex", "kind": "github_release", "repo": "openai/codex"},
    {"slug": "gemini-cli", "name": "Gemini CLI", "kind": "github_release", "repo": "google-gemini/gemini-cli"},
    {"slug": "copilot-cli", "name": "GitHub Copilot CLI", "kind": "github_release", "repo": "github/copilot-cli"},
    {"slug": "opencode", "name": "OpenCode", "kind": "github_release", "repo": "anomalyco/opencode"},
    {"slug": "cline", "name": "Cline", "kind": "github_release", "repo": "cline/cline"},
    {"slug": "zed", "name": "Zed", "kind": "github_release", "repo": "zed-industries/zed"},
    {"slug": "qwen-code", "name": "Qwen Code", "kind": "github_release", "repo": "QwenLM/qwen-code"},
    {"slug": "goose", "name": "Goose", "kind": "github_release", "repo": "aaif-goose/goose"},
    {"slug": "kilo-code", "name": "Kilo Code", "kind": "github_release", "repo": "Kilo-Org/kilocode"},
    {"slug": "anthropic-api", "name": "Anthropic API", "kind": "html", "feed_url": "https://platform.claude.com/docs/en/release-notes/overview.md"},
    {"slug": "gemini-api", "name": "Gemini API", "kind": "html", "feed_url": "https://ai.google.dev/gemini-api/docs/changelog.md.txt"},
    {"slug": "openai-api", "name": "OpenAI API", "kind": "html", "feed_url": "https://developers.openai.com/api/docs/changelog"},
    {"slug": "windsurf", "name": "Windsurf (Devin Desktop)", "kind": "html", "feed_url": "https://docs.devin.ai/desktop/changelog.md"},
    {"slug": "antigravity", "name": "Antigravity", "kind": "html", "feed_url": "https://antigravity.google/docs/changelog"},
    {"slug": "antigravity-ide", "name": "Antigravity IDE", "kind": "html", "feed_url": "https://antigravity.google/docs/changelog"},
    {"slug": "antigravity-cli", "name": "Antigravity CLI", "kind": "html", "feed_url": "https://antigravity.google/docs/changelog"},
    {"slug": "antigravity-sdk", "name": "Antigravity SDK", "kind": "html", "feed_url": "https://antigravity.google/docs/changelog"},
    {"slug": "vscode", "name": "VS Code", "kind": "rss", "feed_url": "https://code.visualstudio.com/feed.xml"},
    {"slug": "cursor", "name": "Cursor", "kind": "rss", "feed_url": "https://cursor.com/changelog/rss.xml"},
    {"slug": "kiro", "name": "Kiro", "kind": "rss", "feed_url": "https://kiro.dev/changelog/feed.rss"},
    {
        "slug": "android-studio",
        "name": "Android Studio",
        "kind": "rss",
        "feed_url": "https://androidstudio.googleblog.com/feeds/posts/default?max-results=20",
        "include_prerelease": True,
    },
    {"slug": "intellij-idea", "name": "IntelliJ IDEA", "kind": "html", "feed_url": f"{JETBRAINS_API}?code=IIU&latest=false&type=release"},
    {"slug": "pycharm", "name": "PyCharm", "kind": "html", "feed_url": f"{JETBRAINS_API}?code=PCP&latest=false&type=release"},
    {"slug": "webstorm", "name": "WebStorm", "kind": "html", "feed_url": f"{JETBRAINS_API}?code=WS&latest=false&type=release"},
]
# 한국어로 많이 검색하는 이름. 도구별 목록 페이지의 설명 · 소개 문장에만 덧붙인다 (검색어와 맞추려는 용도)
TOOL_KO_NAMES = {
    "claude-code": "클로드 코드",
    "codex": "코덱스",
    "gemini-cli": "제미나이 CLI",
    "copilot-cli": "깃허브 코파일럿 CLI",
    "cursor": "커서",
    "windsurf": "윈드서프",
    "intellij-idea": "인텔리제이",
    "pycharm": "파이참",
    "webstorm": "웹스톰",
    "android-studio": "안드로이드 스튜디오",
}
# 한 저장소에 여러 제품의 릴리스가 섞여 있을 때 소스에 넣을 태그만 거른다 (slug별 정규식, 태그 앞에서부터 맞춘다)
GITHUB_TAG_PATTERNS = {"cline": r"v\d", "qwen-code": r"v\d", "kilo-code": r"v\d"}
# 피드가 없어 변경 로그 페이지를 직접 읽는 소스(Windsurf, Antigravity)의 요청 제한 시간(초)과 한 번에 읽을 최대 릴리스 수
SCRAPE_TIMEOUT_SEC = 30
SCRAPE_MAX_RELEASES = 15