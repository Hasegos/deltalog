import json
import re
import tomllib
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from core.constants.monthly import (
    EXPERIENCE_PLACEHOLDER,
    MONTHLY_DATA_DIR,
    MONTHLY_DEADLINE_DAYS,
    MONTHLY_MONTH_RE,
    MONTHLY_PICKS_MAX,
    MONTHLY_PICKS_MIN,
    MONTHLY_TODOS_MAX,
    MONTHLY_TOOLS_SHOWN,
    MONTHLY_TOPICS_SHOWN,
)
from core.constants.page import KST
from core.months import next_month
from crud import monthly_crud
from services.web.release_service import _breadcrumb, _json_ld

_cache: dict = {"stamp": None, "data": None}
_COUNT_KEYS = ("releases", "prev_releases", "breaking", "prev_breaking", "security", "prev_security", "tools_active", "deadlines_60d")


def _error(name: str, reason: str) -> ValueError:
    """파일 이름과 이유를 담은 오류를 만든다."""
    return ValueError(f"{MONTHLY_DATA_DIR}/{name}.toml: {reason}")


def _count(name: str, where: str, row: dict, key: str, signed: bool = False) -> int | None:
    """숫자 필드를 읽는다. 부호 있는 값(`signed`)만 키가 없을 수 있고, 그때는 `None`이다.

    Raises:
        ValueError: 정수가 아니거나 음수일 때
    """
    value = row.get(key)
    if value is None and signed:
        return None
    if type(value) is not int or (value < 0 and not signed):
        raise _error(name, f"{where}{key} 값이 올바르지 않습니다 ({value!r})")
    return value


def _text(name: str, raw: dict, key: str, required: bool = True) -> str:
    """문자열 필드를 읽는다. 앞뒤 공백을 뗀다.

    Raises:
        ValueError: 문자열이 아니거나, 필수인데 비었을 때
    """
    value = raw.get(key, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise _error(name, f"{key} 값이 올바르지 않습니다 ({value!r})")
    return value.strip()


def _paragraphs(name: str, raw: dict, key: str) -> list[str]:
    """문단 목록 필드를 읽는다. 키가 없으면 빈 목록이다.

    Raises:
        ValueError: 비어 있지 않은 문자열의 목록이 아닐 때
    """
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise _error(name, f"{key}는 비어 있지 않은 문자열 목록이어야 합니다")
    return [v.strip() for v in value]


def _link(name: str, where: str, value: str) -> str:
    """사이트 안 경로(`/`로 시작)나 `https://` 주소만 허용한다.

    Raises:
        ValueError: 그 밖의 주소일 때
    """
    if not (value.startswith("https://") or (value.startswith("/") and not value.startswith(("//", "/\\")))):
        raise _error(name, f"{where} 주소는 https:// 또는 /로 시작해야 합니다 ({value!r})")
    return value


def _rows(name: str, raw: dict, key: str) -> list[dict]:
    """표 배열 필드를 읽는다. 키가 없으면 빈 목록이다.

    Raises:
        ValueError: 표의 목록이 아닐 때
    """
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise _error(name, f"{key}는 표의 목록이어야 합니다")
    return value


def _stats(name: str, raw: dict) -> dict:
    """`[stats]`를 검증한다. 화면 숫자는 이 값만 쓴다.

    Raises:
        ValueError: 월이 파일 이름과 다르거나 숫자 · 목록 모양이 틀렸을 때
    """
    stats = raw.get("stats")
    if not isinstance(stats, dict) or stats.get("month") != name:
        raise _error(name, "[stats]가 없거나 month가 파일 이름과 다릅니다")
    result = {"month": name, "releases_delta_pct": _count(name, "stats.", stats, "releases_delta_pct", signed=True)}
    result.update({key: _count(name, "stats.", stats, key) for key in _COUNT_KEYS})
    before = result["prev_releases"]
    expected = round(100 * (result["releases"] - before) / before) if before else None
    if result["releases_delta_pct"] != expected:
        raise _error(name, f"stats.releases_delta_pct가 releases와 prev_releases로 계산한 값과 다릅니다 (기대 {expected!r})")
    result["by_tool"] = [
        {"slug": _text(name, row, "slug"), "name": _text(name, row, "name"), **{key: _count(name, "stats.by_tool.", row, key) for key in ("releases", "breaking", "security", "important")}}
        for row in _rows(name, stats, "by_tool")
    ]
    result["topics"] = [
        {"topic": _text(name, row, "topic"), "n": _count(name, "stats.topics.", row, "n"), "prev": _count(name, "stats.topics.", row, "prev")}
        for row in _rows(name, stats, "topics")
    ]
    return result


def _parse(name: str, raw: dict) -> dict:
    """TOML에서 읽은 월간 리포트 한 호를 검증해 서비스가 쓰는 모양으로 바꾼다.

    Args:
        name: 파일 이름(확장자 없음, `YYYY-MM`)
        raw: `tomllib`가 읽은 값
    Returns:
        한 호의 값. `title_candidates` 같은 모르는 키는 버린다
    Raises:
        ValueError: 필수 값이 없거나 형식이 틀렸거나, 검수를 마쳤다고 했는데 (`reviewed = true`) 덜 끝났을 때
    """
    if raw.get("month") != name:
        raise _error(name, f"month가 파일 이름과 다릅니다 ({raw.get('month')!r})")
    reviewed, reviewed_at, published_at = raw.get("reviewed", False), raw.get("reviewed_at"), raw.get("published_at")
    if not isinstance(reviewed, bool) or type(published_at) is not date or (reviewed_at is not None and type(reviewed_at) is not date):
        raise _error(name, "reviewed(true/false), published_at(날짜), reviewed_at(날짜)이 올바르지 않습니다")
    picks = [
        {"url": _link(name, "picks", _text(name, row, "url")), "title": _text(name, row, "title"), "comment": _text(name, row, "comment")}
        for row in _rows(name, raw, "picks")
    ]
    todos = []
    for row in _rows(name, raw, "todos"):
        if type(row.get("date")) is not date:
            raise _error(name, f"todos의 date는 날짜여야 합니다 ({row.get('date')!r})")
        guide = _text(name, row, "guide", required=False)
        todos.append({"date": row["date"], "text": _text(name, row, "text"), "guide": _link(name, "todos guide", guide) if guide else ""})
    issue = {
        "month": name,
        "title": _text(name, raw, "title", required=False),
        "published_at": published_at,
        "reviewed": reviewed,
        "reviewed_at": reviewed_at,
        "editor_note": _paragraphs(name, raw, "editor_note"),
        "experience": _paragraphs(name, raw, "experience"),
        "picks": picks,
        "todos": todos,
        "stats": _stats(name, raw),
    }
    if reviewed:
        if reviewed_at is None or not issue["title"] or not issue["editor_note"] or not issue["experience"]:
            raise _error(name, "reviewed = true면 reviewed_at, title, editor_note, experience가 필요합니다")
        if any(EXPERIENCE_PLACEHOLDER in paragraph for paragraph in issue["experience"]):
            raise _error(name, "reviewed = true인데 experience에 자리표시 문구가 남아 있습니다")
        if not MONTHLY_PICKS_MIN <= len(picks) <= MONTHLY_PICKS_MAX:
            raise _error(name, f"reviewed = true면 picks는 {MONTHLY_PICKS_MIN}~{MONTHLY_PICKS_MAX}개여야 합니다 ({len(picks)}개)")
        if len(todos) > MONTHLY_TODOS_MAX:
            raise _error(name, f"todos는 {MONTHLY_TODOS_MAX}개 이하여야 합니다 ({len(todos)}개)")
    return issue


def _load() -> dict[str, dict]:
    """`data/monthly/*.toml`을 읽어 검증한 값을 `{YYYY-MM: 한 호}`로 돌려준다. 파일이 바뀌었을 때만 다시 읽는다.

    Returns:
        한 호씩의 값. 폴더가 없으면 빈 값
    Raises:
        ValueError: 파일 이름이나 내용이 올바르지 않을 때
    """
    folder = Path(MONTHLY_DATA_DIR)
    files = sorted(folder.glob("*.toml")) if folder.is_dir() else []
    stamp = tuple((f.name, f.stat().st_mtime) for f in files)
    if _cache["stamp"] != stamp:
        issues = {}
        for path in files:
            if not re.fullmatch(MONTHLY_MONTH_RE, path.stem):
                raise _error(path.stem, "파일 이름은 YYYY-MM이어야 합니다")
            try:
                raw = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                raise _error(path.stem, f"TOML 형식이 올바르지 않습니다 ({exc})") from exc
            issues[path.stem] = _parse(path.stem, raw)
        _cache.update(stamp=stamp, data=issues)
    return _cache["data"]


_load()


def _reviewed() -> list[dict]:
    """검수를 마친(`reviewed = true`) 호를 최신 달부터 돌려준다."""
    return sorted((i for i in _load().values() if i["reviewed"]), key=lambda i: i["month"], reverse=True)


def month_label(month: str) -> str:
    """`2026-10`을 `2026년 10월`로 바꾼다."""
    return f"{month[:4]}년 {int(month[5:])}월"


def _delta(now: int, before: int) -> str:
    """지난달과 비교한 증감 글을 만든다. 지난달 값이 0이면 증감률 대신 지난달 값을 적는다."""
    if before == 0:
        return "지난달 0건"
    return f"지난달 {before}건 · {'+' if now >= before else '−'}{abs(round(100 * (now - before) / before))}%"


def _bars(stats: dict) -> dict | None:
    """도구별 릴리스 수 가로 막대 값을 만든다. 상위 `MONTHLY_TOOLS_SHOWN`개만 보이고 나머지는 합계 한 줄로 줄인다.

    Args:
        stats: 검증을 마친 `[stats]`
    Returns:
        `{"bars", "rest_n", "rest_releases"}`. 릴리스가 없으면 `None`
    """
    tools = stats["by_tool"]
    if not tools:
        return None
    shown, rest = tools[:MONTHLY_TOOLS_SHOWN], tools[MONTHLY_TOOLS_SHOWN:]
    peak = max(t["releases"] for t in shown) or 1
    bars = [
        {
            "name": t["name"],
            "releases": t["releases"],
            "pct": round(100 * t["releases"] / peak, 1),
            "breaking": t["breaking"],
            "security": t["security"],
            "title": f"릴리스 {t['releases']}개, breaking {t['breaking']}개, 보안 {t['security']}개",
        }
        for t in shown
    ]
    return {"bars": bars, "rest_n": len(rest), "rest_releases": sum(t["releases"] for t in rest)}


def _topic_bars(stats: dict) -> list[dict]:
    """주제별 이번 달과 지난달 항목 수를 나란히 그릴 막대 값을 만든다. 상위 `MONTHLY_TOPICS_SHOWN`개만 담는다."""
    topics = stats["topics"][:MONTHLY_TOPICS_SHOWN]
    peak = max((max(t["n"], t["prev"]) for t in topics), default=0) or 1
    return [{"topic": t["topic"], "n": t["n"], "prev": t["prev"], "pct": round(100 * t["n"] / peak, 1), "prev_pct": round(100 * t["prev"] / peak, 1)} for t in topics]


def _todo(row: dict, today: date) -> dict:
    """이번 달 할 일 하나를 화면 값으로 바꾼다. `badge`는 종료까지 남은 날(`D-12`), 오늘이면 `오늘`, 지났으면 `지남`이다."""
    delta = (row["date"] - today).days
    return {
        "date": row["date"].isoformat(),
        "label": f"{row['date'].month}월 {row['date'].day}일",
        "badge": "오늘" if delta == 0 else f"D-{delta}" if delta > 0 else "지남",
        "past": delta < 0,
        "text": row["text"],
        "guide": row["guide"],
    }


def build_monthly_index(base: str) -> dict:
    """월간 리포트 목록 화면의 값을 만든다. 검수를 마친 호만 보인다.

    Args:
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
    Returns:
        템플릿에 넘길 값. 공개된 호가 없으면 `noindex`가 참이다
    """
    issues = _reviewed()
    return {
        "issues": [
            {"month": i["month"], "label": month_label(i["month"]), "title": i["title"], "published": i["published_at"].isoformat(), "releases": i["stats"]["releases"], "delta": i["stats"]["releases_delta_pct"]}
            for i in issues
        ],
        "noindex": not issues,
        "seo_title": "월간 리포트 · AI 코딩 도구 한 달 변화 정리 · Deltalog",
        "seo_desc": "한 달 동안 AI 코딩 도구와 IDE에서 바뀐 것을 숫자와 운영자의 직접 검수로 정리하는 월간 리포트입니다.",
        "jsonld": _json_ld(_breadcrumb(base, [("월간 리포트", "/monthly")])),
    }


def build_monthly(month: str, base: str, today: date | None = None) -> dict | None:
    """월간 리포트 한 호의 화면 값을 만든다. 숫자는 파일의 `[stats]`만 쓰고 DB를 읽지 않는다.

    Args:
        month: `YYYY-MM`
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
        today: 기준 날짜(한국 시간). 비우면 오늘
    Returns:
        템플릿에 넘길 값. 파일이 없거나 검수를 마치지 않았으면 `None`
    """
    today = today or datetime.now(KST).date()
    issue = _load().get(month)
    if issue is None or not issue["reviewed"]:
        return None
    stats = issue["stats"]
    keys = [i["month"] for i in _reviewed()]
    pos = keys.index(month)
    path = f"/monthly/{month}"
    label = month_label(month)
    cards = [
        {"name": "릴리스", "value": stats["releases"], "note": _delta(stats["releases"], stats["prev_releases"])},
        {"name": "breaking", "value": stats["breaking"], "note": f"지난달 {stats['prev_breaking']}건"},
        {"name": "보안", "value": stats["security"], "note": f"지난달 {stats['prev_security']}건"},
        {"name": "종료 예정", "value": stats["deadlines_60d"], "note": f"발행일부터 {MONTHLY_DEADLINE_DAYS}일 안"},
    ]
    return {
        "month": month,
        "label": label,
        "title": issue["title"],
        "published": issue["published_at"].isoformat(),
        "published_label": f"{issue['published_at'].year}년 {issue['published_at'].month}월 {issue['published_at'].day}일",
        "reviewed": issue["reviewed_at"].isoformat(),
        "cards": cards,
        "tools_active": stats["tools_active"],
        "editor_note": issue["editor_note"],
        "experience": issue["experience"],
        "todos": [_todo(row, today) for row in issue["todos"]],
        "chart": _bars(stats),
        "topics": _topic_bars(stats),
        "picks": [{**p, "external": p["url"].startswith("https://")} for p in issue["picks"]],
        "newer": keys[pos - 1] if pos > 0 else "",
        "older": keys[pos + 1] if pos < len(keys) - 1 else "",
        "seo_title": f"{issue['title']} · {label} 월간 리포트 · Deltalog",
        "seo_desc": issue["editor_note"][0][:150],
        "seo_type": "article",
        "jsonld": _json_ld(
            [
                {
                    "@context": "https://schema.org",
                    "@type": "Article",
                    "headline": issue["title"],
                    "description": issue["editor_note"][0][:150],
                    "inLanguage": "ko",
                    "datePublished": issue["published_at"].isoformat(),
                    "dateModified": issue["reviewed_at"].isoformat(),
                    "mainEntityOfPage": f"{base}{path}",
                    "author": {"@type": "Organization", "name": "Deltalog"},
                    "publisher": {"@type": "Organization", "name": "Deltalog", "url": base},
                },
                _breadcrumb(base, [("월간 리포트", "/monthly"), (label, path)]),
            ]
        ),
    }


def sitemap_urls() -> list[tuple[str, str]]:
    """사이트맵에 넣을 월간 리포트의 `(경로, lastmod)`를 돌려준다. 검수를 마친 호가 없으면 목록 페이지도 `noindex`라 모두 뺀다.

    Returns:
        `(경로, YYYY-MM-DD)` 목록. `lastmod`는 검수일이다
    """
    issues = _reviewed()
    if not issues:
        return []
    newest = max(i["reviewed_at"] for i in issues).isoformat()
    return [("/monthly", newest)] + [(f"/monthly/{i['month']}", i["reviewed_at"].isoformat()) for i in issues]


def _value(value) -> str:
    """TOML 값 하나를 글로 만든다. 문자열은 `json.dumps`로 감싸 TOML 기본 문자열로 쓰고, JSON이 그대로 두는 DEL 문자만 따로 막는다.

    Args:
        value: 불리언, 숫자, 날짜, 문자열, 또는 그 목록
    Returns:
        TOML 값 문자열
    Raises:
        TypeError: 지원하지 않는 값일 때
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    if isinstance(value, list):
        return "[]" if not value else "[\n" + "".join(f"  {_value(v)},\n" for v in value) + "]"
    raise TypeError(f"TOML로 쓸 수 없는 값입니다 ({value!r})")


def _emit(table: dict, path: str) -> list[str]:
    """표 하나를 TOML 줄로 만든다. 값이 `None`인 키는 쓰지 않는다(TOML에는 null이 없다). 표 · 표 배열은 일반 키 뒤에 `[이름]`, `[[이름]]`으로 쓴다."""
    plain = {k: v for k, v in table.items() if v is not None and not _is_table(v)}
    lines = [f"{key} = {_value(value)}" for key, value in plain.items()]
    for key, value in table.items():
        full = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            lines += ["", f"[{full}]", *_emit(value, full)]
        elif _is_table(value):
            for row in value:
                lines += ["", f"[[{full}]]", *_emit(row, full)]
    return lines


def _is_table(value) -> bool:
    """표이거나 비어 있지 않은 표의 목록이면 참이다."""
    return isinstance(value, dict) or (isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value))


def dumps(doc: dict) -> str:
    """월간 리포트 값을 TOML 글로 만든다. 새 라이브러리를 쓰지 않고, 이 파일이 쓰는 값(문자열, 정수, 날짜, 불리언, 목록, 표)만 쓴다.

    Args:
        doc: 키가 영문 · 숫자 · 밑줄인 값
    Returns:
        `tomllib.loads`로 다시 읽으면 같은 값이 되는 TOML 글
    """
    return "\n".join(_emit(doc, "")) + "\n"


def build_draft(db: Session, month: date, now: datetime) -> str:
    """월간 리포트 초안을 TOML 글로 만든다. 항상 검수 전(`reviewed = false`)이고 경험은 자리표시 문구다.

    저장된 Gemini 초안(`MonthlyDraft`)이 있으면 그 숫자(`stats`)와 글을 쓰고 제목 후보는 `title_candidates`에 둔다.
    없으면 제목 · 해설 · 고른 변경 · 할 일이 빈 뼈대에 지금 센 숫자를 채운다.

    Args:
        db: DB 세션
        month: 그 달 1일
        now: 지금 시각. 발행일과 종료 예정 일정 기준일에 쓴다
    Returns:
        `data/monthly/YYYY-MM.toml`에 그대로 저장할 수 있는 글
    """
    today = now.astimezone(KST).date()
    saved = monthly_crud.get_draft(db, month)
    draft = saved.draft if saved else {}
    headlines = draft.get("headlines", [])
    doc = {
        "month": month.strftime("%Y-%m"),
        "title": headlines[0] if headlines else "",
        **({"title_candidates": headlines} if headlines else {}),
        "published_at": today,
        "reviewed": False,
        "editor_note": draft.get("trends", []),
        "experience": [EXPERIENCE_PLACEHOLDER],
        "picks": draft.get("picks", []),
        "todos": [{"date": date.fromisoformat(t["date"]), "text": t["text"], "guide": ""} for t in draft.get("todos", [])],
        "stats": saved.stats if saved else monthly_crud.stats(db, month, today),
    }
    return dumps(doc)


def is_finished(month: date, now: datetime) -> bool:
    """그 달이 한국 시간으로 끝났는지 돌려준다."""
    return now.astimezone(KST).date() >= next_month(month)