"""seed sources

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SOURCES = [
    {"slug": "claude-code", "name": "Claude Code", "kind": "github_release", "repo": "anthropics/claude-code", "feed_url": None},
    {"slug": "codex", "name": "Codex", "kind": "github_release", "repo": "openai/codex", "feed_url": None},
    {"slug": "gemini-cli", "name": "Gemini CLI", "kind": "github_release", "repo": "google-gemini/gemini-cli", "feed_url": None},
    {"slug": "vscode", "name": "VS Code", "kind": "rss", "repo": None, "feed_url": "https://code.visualstudio.com/feed.xml"},
    {"slug": "cursor", "name": "Cursor", "kind": "rss", "repo": None, "feed_url": "https://cursor.com/changelog/rss.xml"},
    {"slug": "android-studio", "name": "Android Studio", "kind": "html", "repo": None, "feed_url": "https://developer.android.com/studio/releases"},
    {"slug": "jetbrains", "name": "JetBrains", "kind": "html", "repo": None, "feed_url": "https://www.jetbrains.com/idea/whatsnew/"},
]


def upgrade() -> None:
    """릴리스 소스 7곳을 `source` 테이블에 넣는다."""
    source = sa.table(
        "source",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("kind", sa.String),
        sa.column("repo", sa.String),
        sa.column("feed_url", sa.Text),
    )
    op.bulk_insert(source, SOURCES)


def downgrade() -> None:
    """넣었던 소스 7곳을 지운다."""
    slugs = ", ".join(f"'{s['slug']}'" for s in SOURCES)
    op.execute(f"DELETE FROM source WHERE slug IN ({slugs})")