import json
from datetime import timezone
from urllib.parse import quote

from sqlalchemy.orm import Session

from core.constants.page import KST
from core.constants.taxonomy import CATEGORIES, SEVERITY
from crud import entry_crud
from models.entry_model import Entry

DESCRIPTION_CHARS = 150
DESCRIPTION_LINES = 3


def release_path(slug: str, entry: Entry) -> str:
    """릴리스 상세 페이지 주소를 만든다. 버전이 없는 글(Cursor, Android Studio)은 글 ID를 쓴다.

    Args:
        slug: 소스 slug
        entry: 글
    Returns:
        `/r/<slug>/<버전 또는 글 ID>`
    """
    return f"/r/{slug}/{quote(entry.version or str(entry.id), safe='')}"


def _json_ld(data: dict) -> str:
    """JSON-LD를 `<script>` 안에 넣어도 안전한 문자열로 만든다."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def build_release(db: Session, slug: str, key: str, base: str) -> dict | None:
    """릴리스 상세 페이지에 필요한 값을 만든다.

    Args:
        db: DB 세션
        slug: 소스 slug
        key: 버전 또는 글 ID
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
    Returns:
        템플릿에 넘길 값. 글이 없으면 `None`. 요약된 항목이 하나도 없으면 `noindex`가 참이다
    """
    found = entry_crud.get_entry_by_key(db, slug, key)
    if found is None:
        return None
    entry, source = found
    items = entry_crud.list_entry_items(db, entry.id)
    by_category: dict[str, list] = {}
    for item in items:
        by_category.setdefault(item.category if item.category in CATEGORIES else "other", []).append(item)

    groups = []
    for category in SEVERITY:
        rows = sorted(by_category.get(category, []), key=lambda i: (-(i.importance or 0), i.seq))
        if rows:
            symbol, label = CATEGORIES[category]
            groups.append(
                {
                    "key": category,
                    "symbol": symbol,
                    "label": label,
                    "rows": [
                        {"summary": i.summary_ko, "raw": i.raw_text, "topic": i.topic, "importance": i.importance or 0}
                        for i in rows
                    ],
                }
            )

    done = [i for i in items if i.status == "done" and i.summary_ko]
    top = sorted(done, key=lambda i: (-(i.importance or 0), i.seq))[:DESCRIPTION_LINES]
    version = entry.version or entry.title
    name = source.name
    summary_text = "; ".join(i.summary_ko for i in top)
    description = f"{name} {version} 변경 사항 {len(items)}개 한국어 요약. {summary_text}".strip()
    if len(description) > DESCRIPTION_CHARS:
        description = description[: DESCRIPTION_CHARS - 1].rstrip() + "…"

    path = release_path(slug, entry)
    published = entry.published_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    older, newer = entry_crud.neighbor_entries(db, entry)
    return {
        "name": name,
        "slug": slug,
        "version": version,
        "has_version": bool(entry.version),
        "date": entry.published_at.astimezone(KST).strftime("%Y-%m-%d"),
        "url": entry.url if entry.url.startswith(("https://", "http://")) else "",
        "prerelease": entry.is_prerelease,
        "groups": groups,
        "total": len(items),
        "done": len(done),
        "older": {"label": older.version or older.title, "path": release_path(slug, older)} if older else None,
        "newer": {"label": newer.version or newer.title, "path": release_path(slug, newer)} if newer else None,
        "seo_title": f"{name} {version} 변경 사항 한국어 요약 · Deltalog",
        "seo_desc": description,
        "seo_type": "article",
        "noindex": not done,
        "jsonld": _json_ld(
            {
                "@context": "https://schema.org",
                "@type": "TechArticle",
                "headline": f"{name} {version} 변경 사항",
                "description": description,
                "inLanguage": "ko",
                "datePublished": published,
                "dateModified": published,
                "mainEntityOfPage": f"{base}{path}",
                "isBasedOn": entry.url,
                "about": {"@type": "SoftwareApplication", "name": name, "softwareVersion": version},
                "author": {"@type": "Organization", "name": "Deltalog"},
                "publisher": {"@type": "Organization", "name": "Deltalog", "url": base},
            }
        ),
    }


def sitemap_urls(db: Session) -> list[tuple[str, str]]:
    """사이트맵에 넣을 릴리스 상세 페이지 주소와 게시일을 돌려준다. 요약된 항목이 있는 글만 넣는다.

    Args:
        db: DB 세션
    Returns:
        `(경로, 게시일 YYYY-MM-DD)` 목록. 최신순
    """
    return [
        (release_path(source.slug, entry), entry.published_at.astimezone(timezone.utc).strftime("%Y-%m-%d"))
        for entry, source in entry_crud.list_summarized_entries(db)
    ]