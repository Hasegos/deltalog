from sqlalchemy import select
from sqlalchemy.orm import Session

from db.base import Base, Source
from db.session import engine

SOURCES = [
    {"slug": "claude-code", "name": "Claude Code", "kind": "github_release", "repo": "anthropics/claude-code"},
    {"slug": "codex", "name": "Codex", "kind": "github_release", "repo": "openai/codex"},
    {"slug": "gemini-cli", "name": "Gemini CLI", "kind": "github_release", "repo": "google-gemini/gemini-cli"},
    {"slug": "vscode", "name": "VS Code", "kind": "rss", "feed_url": "https://code.visualstudio.com/feed.xml"},
    {"slug": "cursor", "name": "Cursor", "kind": "rss", "feed_url": "https://cursor.com/changelog/rss.xml"},
    {"slug": "android-studio", "name": "Android Studio", "kind": "html", "feed_url": "https://developer.android.com/studio/releases"},
    {"slug": "jetbrains", "name": "JetBrains", "kind": "html", "feed_url": "https://www.jetbrains.com/idea/whatsnew/"},
]


def init_db() -> None:
    """테이블이 없으면 만들고, `source`가 비어 있으면 릴리스 소스 7곳을 넣는다."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if session.scalar(select(Source.id).limit(1)) is None:
            session.add_all(Source(**row) for row in SOURCES)
            session.commit()