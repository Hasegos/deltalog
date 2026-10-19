import re

from sqlalchemy.orm import Session

from core.constants.page import IMPORTANT_MIN
from core.constants.taxonomy import CATEGORIES, SEVERITY
from crud import entry_crud, item_crud

LEVELS = (("key", "중요한 것만 (중요도 4 이상, breaking, 보안)"), ("all", "요약된 전부"))
MUST_CHECK = ("breaking", "security")
MUST_LIMIT = 5


def _row(item, entry) -> dict:
    """항목 하나를 화면에 쓸 값으로 바꾼다."""
    return {
        "summary": item.summary_ko,
        "raw": item.raw_text,
        "topic": item.topic,
        "importance": item.importance or 0,
        "version": entry.version,
        "url": entry.url,
    }


def version_key(version: str) -> tuple[int, ...]:
    """버전 문자열을 숫자 묶음으로 바꿔 크기를 비교할 수 있게 한다.

    Args:
        version: `2.1.296`, `1.141` 같은 버전
    Returns:
        `(2, 1, 296)` 같은 값. 숫자가 없으면 빈 값
    """
    return tuple(int(n) for n in re.findall(r"\d+", version))


def build_changes(db: Session, tool: str, version: str, level: str) -> dict:
    """"내 버전부터 최신까지" 바뀐 점 화면에 필요한 값을 만든다.

    버전이 있는 소스(GitHub 릴리스, VS Code)만 고를 수 있고, 입력한 버전보다 높은 릴리스의 요약을 유형별로 모은다.

    결과 맨 위에 요약(릴리스 수, 유형별 개수)과 "업그레이드 전 확인"(breaking · 보안 항목 최대 `MUST_LIMIT`개)을 둔다. 확인 목록은 범위와 상관없이 만든다.

    Args:
        db: DB 세션
        tool: 소스 slug. 비어 있으면 입력 폼만 보인다
        version: 지금 쓰는 버전
        level: `key`(중요한 것만) 또는 `all`
    Returns:
        템플릿에 넘길 값. `result`는 입력이 모두 있고 올바를 때만 있다
    """
    level = level if level == "all" else "key"
    versioned = [
        s for s in item_crud.list_sources(db) if entry_crud.has_versions(db, s.id)
    ]
    context = {
        "tools": [{"slug": s.slug, "name": s.name} for s in versioned],
        "tool": tool,
        "version": version,
        "level": level,
        "levels": LEVELS,
        "result": None,
        "error": "",
    }
    source = next((s for s in versioned if s.slug == tool), None)
    if not tool and not version:
        return context
    if source is None:
        context["error"] = "도구를 골라 주세요."
        return context
    current = version_key(version)
    if not current:
        context["error"] = "버전을 숫자로 입력해 주세요. 예: 2.1.290"
        return context

    entries = entry_crud.list_source_entries(db, source.id)
    newer = [e for e in entries if e.version and version_key(e.version) > current]
    oldest = min((version_key(e.version), e.version) for e in entries if e.version)[1]
    result = {
        "source": source.name,
        "newest": entries[0].version if entries else "",
        "oldest": oldest,
        "older_than_collected": current < version_key(oldest),
        "releases": len(newer),
        "pending": 0,
        "groups": [],
    }
    if newer:
        by_id = {e.id: e for e in newer}
        stats = entry_crud.entry_stats(db, list(by_id))
        result["pending"] = sum(s["count"] - s["done"] for s in stats.values())
        all_items = item_crud.list_done_items(db, list(by_id), key_only=False)
        items = [i for i in all_items if level == "all" or i.importance and i.importance >= IMPORTANT_MIN or i.category in MUST_CHECK]
        result["counts"] = [
            {"key": key, "symbol": CATEGORIES[key][0], "label": CATEGORIES[key][1], "count": sum(1 for i in all_items if i.category == key)}
            for key in SEVERITY
            if any(i.category == key for i in all_items)
        ]
        must = [i for i in all_items if i.category in MUST_CHECK]
        must.sort(key=lambda i: (MUST_CHECK.index(i.category), -(i.importance or 0), -by_id[i.entry_id].published_at.timestamp(), i.seq))
        result["must"] = [{**_row(i, by_id[i.entry_id]), "key": i.category, "symbol": CATEGORIES[i.category][0], "label": CATEGORIES[i.category][1]} for i in must[:MUST_LIMIT]]
        result["must_total"] = len(must)
        groups = []
        for key in SEVERITY:
            rows = [i for i in items if i.category == key]
            rows.sort(key=lambda i: (-(i.importance or 0), -by_id[i.entry_id].published_at.timestamp(), i.seq))
            if rows:
                symbol, label = CATEGORIES[key]
                groups.append({"key": key, "symbol": symbol, "label": label, "rows": [_row(i, by_id[i.entry_id]) for i in rows]})
        result["groups"] = groups
        result["shown"] = sum(len(g["rows"]) for g in groups)
    context["result"] = result
    return context