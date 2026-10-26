import json
from datetime import timezone
from urllib.parse import quote

from sqlalchemy.orm import Session

from core.constants.news import RELATED_DAYS, RELATED_LIMIT, RELATED_MIN_IMPORTANCE, TOOL_COMPANY
from core.constants.page import KST, THIN_MAX_CHARS, THIN_MAX_IMPORTANCE
from core.constants.source import TOOL_KO_NAMES
from core.constants.taxonomy import CATEGORIES, SEVERITY
from crud import entry_crud, item_crud, news_crud
from models.entry_model import Entry

DESCRIPTION_CHARS = 150
DESCRIPTION_LINES = 3


def release_label(name: str, version: str) -> str:
    """도구 이름과 버전(없으면 글 제목)을 이은 표시 이름. 버전 자리에 이미 도구 이름이 있으면(`Android Studio Rabbit 1 now available`) 다시 붙이지 않는다."""
    return version if name.lower() in version.lower() else f"{name} {version}"


def is_thin(done: int, chars: int, importance: int) -> bool:
    """릴리스 페이지에 색인할 만한 내용이 없는지 판정한다. 페이지의 `noindex`와 사이트맵 제외가 같은 규칙을 쓴다.

    Args:
        done: 요약이 끝난 항목 수
        chars: 요약이 끝난 항목의 요약 글자 합계
        importance: 요약이 끝난 항목의 가장 높은 중요도
    Returns:
        요약된 항목이 없거나, 요약이 `THIN_MAX_CHARS`자 미만이고 최고 중요도가 `THIN_MAX_IMPORTANCE` 이하이면 `True`
    """
    return done == 0 or (chars < THIN_MAX_CHARS and importance <= THIN_MAX_IMPORTANCE)


def release_path(slug: str, entry: Entry) -> str:
    """릴리스 상세 페이지 주소를 만든다. 버전이 없는 글(Cursor, Android Studio)은 글 ID를 쓴다.

    Args:
        slug: 소스 slug
        entry: 글
    Returns:
        `/releases/<slug>/<버전 또는 글 ID>`
    """
    return f"/releases/{slug}/{quote(entry.version or str(entry.id), safe='')}"


def _json_ld(data: dict) -> str:
    """JSON-LD를 `<script>` 안에 넣어도 안전한 문자열로 만든다."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _breadcrumb(base: str, crumbs: list[tuple[str, str]]) -> dict:
    """홈에서 시작하는 `BreadcrumbList` JSON-LD를 만든다. 화면의 경로 표시와 같은 순서다.

    Args:
        base: 사이트 주소 (끝 `/` 없음)
        crumbs: `(이름, 경로)` 목록. 홈은 넣지 않는다
    Returns:
        JSON-LD dict
    """
    names = [("홈", "/")] + crumbs
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i, "name": n, "item": f"{base}{p}"} for i, (n, p) in enumerate(names, 1)],
    }


def build_release(db: Session, slug: str, key: str, base: str) -> dict | None:
    """릴리스 상세 페이지에 필요한 값을 만든다.

    Args:
        db: DB 세션
        slug: 소스 slug
        key: 버전 또는 글 ID
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
    Returns:
        템플릿에 넘길 값. 글이 없으면 `None`. 얇은 페이지(`is_thin`)이면 `noindex`가 참이다
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

    total_rows = sum(len(g["rows"]) for g in groups)
    mix = [{"key": g["key"], "label": g["label"], "n": len(g["rows"]), "pct": round(100 * len(g["rows"]) / total_rows, 1)} for g in groups] if total_rows >= 2 else []

    done = [i for i in items if i.status == "done" and i.summary_ko]
    top = sorted(done, key=lambda i: (-(i.importance or 0), i.seq))[:DESCRIPTION_LINES]
    version = entry.version or entry.title
    name = source.name
    summary_text = "; ".join(i.summary_ko for i in top)
    label = release_label(name, version)
    description = f"{label} 변경 사항 {len(items)}개 한국어 요약. {summary_text}".strip()
    if len(description) > DESCRIPTION_CHARS:
        description = description[: DESCRIPTION_CHARS - 1].rstrip() + "…"

    path = release_path(slug, entry)
    published = entry.published_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    older, newer = entry_crud.neighbor_entries(db, entry)
    company = TOOL_COMPANY.get(slug, "")
    related = news_crud.list_near(db, company, entry.published_at, RELATED_DAYS, RELATED_MIN_IMPORTANCE, RELATED_LIMIT) if company else []
    return {
        "company": company,
        "related_days": RELATED_DAYS,
        "news": [
            {"id": n.id, "title": n.title_ko or n.title, "url": n.url if n.url.startswith(("https://", "http://")) else "#", "date": n.published_at.astimezone(KST).strftime("%Y-%m-%d")}
            for n in related
        ],
        "name": name,
        "slug": slug,
        "version": version,
        "label": label,
        "has_version": bool(entry.version),
        "date": entry.published_at.astimezone(KST).strftime("%Y-%m-%d"),
        "url": entry.url if entry.url.startswith(("https://", "http://")) else "",
        "prerelease": entry.is_prerelease,
        "groups": groups,
        "mix": mix,
        "breaking": len(by_category.get("breaking", [])),
        "security": len(by_category.get("security", [])),
        "total": len(items),
        "done": len(done),
        "older": {"label": older.version or older.title, "path": release_path(slug, older)} if older else None,
        "newer": {"label": newer.version or newer.title, "path": release_path(slug, newer)} if newer else None,
        "seo_title": f"{label} 변경 사항 한국어 요약 · Deltalog",
        "seo_desc": description,
        "seo_type": "article",
        "og_path": f"/og{path}.png",
        "noindex": is_thin(len(done), sum(len(i.summary_ko) for i in done), max((i.importance or 0 for i in done), default=0)),
        "jsonld": _json_ld(
            [
                {
                "@context": "https://schema.org",
                "@type": "TechArticle",
                "headline": f"{label} 변경 사항",
                "description": description,
                "inLanguage": "ko",
                "datePublished": published,
                "dateModified": published,
                "mainEntityOfPage": f"{base}{path}",
                "isBasedOn": entry.url,
                "about": {"@type": "SoftwareApplication", "name": name, **({"softwareVersion": version} if entry.version else {})},
                "author": {"@type": "Organization", "name": "Deltalog"},
                "publisher": {"@type": "Organization", "name": "Deltalog", "url": base},
                },
                _breadcrumb(base, [("릴리스", "/releases"), (name, f"/releases/{slug}"), (version, path)]),
            ]
        ),
    }


INDEX_ROWS = 5
MAX_LIST = 300


def _rows(db: Session, slug: str, entries: list[Entry]) -> list[dict]:
    """글 목록을 릴리스 목록 화면의 행으로 바꾼다. 행마다 가장 중요한 요약 한 줄을 붙인다."""
    ids = [e.id for e in entries]
    stats = entry_crud.entry_stats(db, ids)
    tops = entry_crud.top_items(db, ids, "all", "", "", 1)
    return [
        {
            "version": e.version or e.title,
            "path": release_path(slug, e),
            "date": e.published_at.astimezone(KST).strftime("%Y-%m-%d"),
            "count": stats[e.id]["count"],
            "headline": next((i.summary_ko for i in tops.get(e.id, []) if i.summary_ko), ""),
            "prerelease": e.is_prerelease,
        }
        for e in entries
    ]


def build_release_index(db: Session, slug: str, base: str) -> dict | None:
    """릴리스 목록 화면의 값을 만든다. `slug`가 비면 도구마다 최근 몇 개를, 있으면 그 도구의 전체를 보여준다.

    Args:
        db: DB 세션
        slug: 소스 slug 또는 빈 문자열
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
    Returns:
        템플릿에 넘길 값. 그런 도구가 없으면 `None`
    """
    sources = item_crud.list_sources(db)
    if slug:
        sources = [s for s in sources if s.slug == slug]
        if not sources:
            return None
    groups = []
    for source in sources:
        entries = entry_crud.list_source_entries(db, source.id, MAX_LIST if slug else INDEX_ROWS)
        if entries:
            groups.append({"name": source.name, "slug": source.slug, "rows": _rows(db, source.slug, entries), "more": not slug})
    if slug and groups:
        name, rows = groups[0]["name"], groups[0]["rows"]
        ko_name = TOOL_KO_NAMES.get(slug)
        label = f"{name}({ko_name})" if ko_name else name
        title = f"{name} 업데이트 내역 · 릴리스 노트 한국어 요약 · Deltalog"
        desc = f"{label}의 최근 릴리스 {len(rows)}개 업데이트 내역과 변경 사항을 한국어로 요약했습니다. 최신 버전은 {rows[0]['version']}입니다."
    else:
        name = label = ""
        title = "릴리스 목록 · AI 코딩 도구별 최근 릴리스와 변경 사항 한국어 요약 · Deltalog"
        desc = "도구별 최근 릴리스와 변경 사항 한국어 요약으로 바로 가는 목록입니다."
    crumbs = [("릴리스", "/releases")] + ([(name, f"/releases/{slug}")] if name else [])
    return {"name": name, "label": label, "slug": slug, "groups": groups, "seo_title": title, "seo_desc": desc, "jsonld": _json_ld(_breadcrumb(base, crumbs))}


def list_releases_json(db: Session, slug: str, limit: int) -> list[dict] | None:
    """API용 릴리스 목록을 만든다.

    Args:
        db: DB 세션
        slug: 소스 slug
        limit: 최대 개수
    Returns:
        릴리스 요약 목록(최신순). 그런 도구가 없으면 `None`
    """
    source = next((s for s in item_crud.list_sources(db) if s.slug == slug), None)
    if source is None:
        return None
    entries = entry_crud.list_source_entries(db, source.id, limit)
    stats = entry_crud.entry_stats(db, [e.id for e in entries])
    return [_release_json(slug, e, stats[e.id]["count"]) for e in entries]


def release_json(db: Session, slug: str, key: str) -> dict | None:
    """API용 릴리스 하나와 그 항목을 만든다.

    Args:
        db: DB 세션
        slug: 소스 slug
        key: 버전 또는 글 ID
    Returns:
        릴리스 값과 `items`. 없으면 `None`
    """
    found = entry_crud.get_entry_by_key(db, slug, key)
    if found is None:
        return None
    entry, _ = found
    items = entry_crud.list_entry_items(db, entry.id)
    return {**_release_json(slug, entry, len(items)), "items": items}


def _release_json(slug: str, entry: Entry, count: int) -> dict:
    return {
        "tool": slug,
        "version": entry.version or "",
        "title": entry.title,
        "published_at": entry.published_at,
        "url": entry.url,
        "prerelease": entry.is_prerelease,
        "item_count": count,
        "page": release_path(slug, entry),
    }