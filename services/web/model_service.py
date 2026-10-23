import re
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from core.constants.deadline import DEADLINE_PAST_DAYS, DEADLINE_PROVIDERS, DEADLINE_SOURCES
from core.constants.model import COST_DEFAULTS, EDITORIAL_KEYS, MODEL_DATA_PATH, MODEL_ID_RE, MODEL_RESERVED_IDS, MODEL_SIBLINGS, MODEL_STALE_DAYS
from core.constants.page import KST
from crud import deadline_crud
from models.deadline_model import Deadline
from services.web.deadline_service import _row as deadline_row
from services.web.release_service import _breadcrumb, _json_ld

_cache: dict = {"mtime": None, "data": None}
_RETIRE_URLS = {source["provider"]: source["url"] for source in DEADLINE_SOURCES}


def _number(model_id: str, raw: dict, key: str, integer: bool = False) -> float | int | None:
    """모델 한 줄의 숫자 필드를 읽는다. 키가 없으면 `None`(미확인)이다.

    Args:
        model_id: 오류 문구에 쓸 모델 ID
        raw: TOML의 `[[model]]` 한 줄
        key: 필드 이름
        integer: 정수만 허용하면 `True`
    Returns:
        값. 없으면 `None`
    Raises:
        ValueError: 숫자가 아니거나 음수(정수 필드는 0 이하)일 때
    """
    value = raw.get(key)
    if value is None:
        return None
    valid = isinstance(value, int) if integer else isinstance(value, (int, float))
    if isinstance(value, bool) or not valid or value < 0 or (integer and value == 0):
        raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: {key} 값이 올바르지 않습니다 ({value!r})")
    return value


def _text(model_id: str, raw: dict, key: str, https: bool = False, required: bool = True) -> str:
    """모델 한 줄의 문자열 필드를 읽는다.

    Args:
        model_id: 오류 문구에 쓸 모델 ID
        raw: TOML의 `[[model]]` 한 줄
        key: 필드 이름
        https: `https://`로 시작해야 하면 `True`
        required: 비어 있으면 안 되면 `True`
    Returns:
        앞뒤 공백을 뗀 문자열. 선택 필드가 없으면 빈 문자열
    Raises:
        ValueError: 문자열이 아니거나, 필수인데 비었거나, `https://`가 아닐 때
    """
    value = raw.get(key, "")
    if not isinstance(value, str) or (required and not value.strip()) or (https and value and not value.startswith("https://")):
        raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: {key} 값이 올바르지 않습니다 ({value!r})")
    return value.strip()


def _strings(model_id: str, raw: dict, key: str, https: bool = False) -> list[str]:
    """모델 한 줄의 문자열 목록 필드를 읽는다. 키가 없으면 빈 목록이다.

    Args:
        model_id: 오류 문구에 쓸 모델 ID
        raw: TOML의 `[[model]]` 한 줄
        key: 필드 이름
        https: 모든 값이 `https://`로 시작해야 하면 `True`
    Returns:
        앞뒤 공백을 뗀 문자열 목록
    Raises:
        ValueError: 목록이 아니거나, 빈 문자열이 있거나, 같은 값이 겹치거나, `https://`가 아닐 때
    """
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() and (not https or v.startswith("https://")) for v in value):
        raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: {key}는 비어 있지 않은 문자열 목록이어야 합니다")
    items = [v.strip() for v in value]
    if len(set(items)) != len(items):
        raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: {key}에 같은 값이 겹칩니다")
    return items


def _parse_editorial(model_id: str, item: dict) -> tuple[dict | None, list[str]]:
    """모델 한 줄의 편집 콘텐츠(`use_when` 등)를 검증한다. 검수(`reviewed = true`)를 마친 모델만 화면에 쓸 값을 돌려주고, 초안은 검증만 하고 버린다.

    Args:
        model_id: 오류 문구에 쓸 모델 ID
        item: TOML의 `[[model]]` 한 줄
    Returns:
        `(화면에 쓸 편집 콘텐츠 또는 None, compare_with 목록)`
    Raises:
        ValueError: 형식이 틀렸거나, 검수를 마쳤는데 검수일 · 근거 링크 · 본문이 없을 때
    """
    reviewed, reviewed_at = item.get("reviewed", False), item.get("reviewed_at")
    if not isinstance(reviewed, bool) or (reviewed_at is not None and type(reviewed_at) is not date):
        raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: reviewed(true/false)나 reviewed_at(날짜)이 올바르지 않습니다")
    body = {key: _strings(model_id, item, key) for key in EDITORIAL_KEYS}
    compare = _strings(model_id, item, "compare_with")
    evidence = _strings(model_id, item, "evidence_urls", https=True)
    if reviewed and (reviewed_at is None or not evidence or not any(body.values())):
        raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: reviewed = true면 reviewed_at, evidence_urls, 본문(use_when · avoid_when · migration · notes 중 하나 이상)이 필요합니다")
    if not reviewed:
        return None, compare
    return {**body, "compare": compare, "evidence": evidence, "reviewed_at": reviewed_at}, compare


def _parse(raw: dict) -> dict:
    """TOML에서 읽은 값을 검증해 서비스가 쓰는 모양으로 바꾼다. 종료 일정과 이름을 맞출 정규식도 만든다.

    Args:
        raw: `tomllib`가 읽은 값
    Returns:
        `{"meta": 환율 정보, "models": 모델 목록}`
    Raises:
        ValueError: 필수 값이 없거나 형식이 틀리거나 ID가 겹칠 때
    """
    meta = raw.get("meta", {})
    rate, rate_day = meta.get("usd_krw"), meta.get("usd_krw_date")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0 or not isinstance(rate_day, date):
        raise ValueError(f"{MODEL_DATA_PATH}: [meta]에 usd_krw(양수)와 usd_krw_date(날짜)가 필요합니다")
    models, seen, compares, owners = [], set(), {}, {}
    for item in raw.get("model", []):
        model_id = str(item.get("id", ""))
        if not re.fullmatch(MODEL_ID_RE, model_id) or model_id in MODEL_RESERVED_IDS or model_id in seen:
            raise ValueError(f"{MODEL_DATA_PATH}: id가 올바르지 않거나 겹칩니다 ({model_id!r})")
        seen.add(model_id)
        provider = _text(model_id, item, "provider")
        verified = item.get("verified_at")
        if provider not in DEADLINE_PROVIDERS or not isinstance(verified, date):
            raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: provider({DEADLINE_PROVIDERS})나 verified_at(날짜)이 올바르지 않습니다")
        name = _text(model_id, item, "name")
        aliases = item.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a for a in aliases):
            raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: aliases는 문자열 목록이어야 합니다")
        floor = item.get("retire_not_before")
        if floor is not None and type(floor) is not date:
            raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: retire_not_before는 날짜(YYYY-MM-DD)여야 합니다 ({floor!r})")
        editorial, compare = _parse_editorial(model_id, item)
        compares[model_id] = compare
        for key in EDITORIAL_KEYS:
            for sentence in _strings(model_id, item, key):
                if owners.setdefault(sentence, model_id) != model_id:
                    raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: {key}의 문장이 {owners[sentence]}와 같습니다. 모델마다 다른 내용을 써야 합니다 ({sentence[:30]!r})")
        keys = sorted({model_id, name.lower(), *(a.lower() for a in aliases)}, key=len, reverse=True)
        models.append(
            {
                "provider": provider,
                "id": model_id,
                "name": name,
                "input": _number(model_id, item, "input_per_mtok"),
                "output": _number(model_id, item, "output_per_mtok"),
                "context": _number(model_id, item, "context_tokens", integer=True),
                "max_output": _number(model_id, item, "max_output_tokens", integer=True),
                "note": _text(model_id, item, "note", required=False),
                "source_url": _text(model_id, item, "source_url", https=True),
                "spec_url": _text(model_id, item, "spec_url", https=True, required=False),
                "verified": verified,
                "retire_not_before": floor,
                "editorial": editorial,
                "pattern": re.compile(r"(?<![\w.\-])(?:" + "|".join(re.escape(k) for k in keys) + r")(?![\w.\-]|\s+[a-z])"),
            }
        )
    for model_id, compare in compares.items():
        if model_id in compare or any(c not in seen for c in compare):
            raise ValueError(f"{MODEL_DATA_PATH}: {model_id}: compare_with에 없는 모델이거나 자기 자신이 있습니다 ({compare})")
    return {
        "meta": {"rate": float(rate), "date": rate_day, "source": _text("[meta]", meta, "usd_krw_source"), "url": _text("[meta]", meta, "usd_krw_url", https=True)},
        "models": models,
    }


def _load() -> dict:
    """`data/models.toml`을 읽어 검증한 값을 돌려준다. 파일 수정 시각이 바뀌었을 때만 다시 읽는다.

    Returns:
        `_parse`의 결과
    Raises:
        ValueError: 파일 내용이 올바르지 않을 때
    """
    path = Path(MODEL_DATA_PATH)
    mtime = path.stat().st_mtime
    if _cache["mtime"] != mtime:
        _cache.update(data=_parse(tomllib.loads(path.read_text(encoding="utf-8"))), mtime=mtime)
    return _cache["data"]


_load()


def _money(value: float | None) -> str:
    """100만 토큰당 달러 단가를 글로 만든다. 값이 없으면 `미확인`이다.

    Args:
        value: USD 단가
    Returns:
        `$10.00`, `$0.125` 같은 글
    """
    if value is None:
        return "미확인"
    return f"${value:,.2f}" if round(value, 2) == value else f"${value:,.4f}".rstrip("0").rstrip(".")


def _tokens(count: int | None) -> str:
    """토큰 수를 글로 만든다. 값이 없으면 `미확인`이다.

    Args:
        count: 토큰 수
    Returns:
        `1M`, `200K`, `1,048,576` 같은 글
    """
    if count is None:
        return "미확인"
    if count % 1_000_000 == 0:
        return f"{count // 1_000_000}M"
    if count < 1_000_000 and count % 1000 == 0:
        return f"{count // 1000}K"
    return f"{count:,}"


def _present(model: dict, deadlines: list[Deadline], today: date) -> dict:
    """모델 한 줄을 화면에 쓸 값으로 바꾸고, 이름이 맞는 종료 일정을 붙인다.

    Args:
        model: `_parse`가 만든 모델
        deadlines: 종료 일정 목록
        today: 기준 날짜
    Returns:
        화면 값. `deadlines`는 종료일 빠른 순이고 `next`는 아직 지나지 않은 가장 빠른 일정이다 (모두 지났으면 가장 최근 일정, 없으면 `None`).
        `tentative`는 제공사가 "이 날짜 이전에는 종료하지 않는다"고만 밝힌 잠정 날짜(`retire_not_before`)이고 확정된 종료 일정이 아니다. 없으면 `None`
    """
    matched = sorted((d for d in deadlines if d.provider == model["provider"] and model["pattern"].search(d.name.lower())), key=lambda d: d.deadline)
    rows = [deadline_row(d, today) for d in matched]
    age = (today - model["verified"]).days
    floor = model["retire_not_before"]
    return {
        "id": model["id"],
        "provider": model["provider"],
        "name": model["name"],
        "href": f"/models/{model['id']}",
        "input": _money(model["input"]),
        "output": _money(model["output"]),
        "input_raw": model["input"],
        "output_raw": model["output"],
        "context": _tokens(model["context"]),
        "max_output": _tokens(model["max_output"]),
        "note": model["note"],
        "source_url": model["source_url"],
        "spec_url": model["spec_url"],
        "verified": model["verified"].isoformat(),
        "age": age,
        "stale": age > MODEL_STALE_DAYS,
        "priced": model["input"] is not None and model["output"] is not None,
        "deadlines": rows,
        "next": next((r for r in rows if not r["past"]), rows[-1] if rows else None),
        "tentative": {"date": floor.isoformat(), "passed": floor <= today, "url": _RETIRE_URLS.get(model["provider"], model["source_url"])} if floor else None,
    }


def _deadlines(db: Session, today: date) -> list[Deadline]:
    """종료 일정 화면과 같은 기간(최근 종료 `DEADLINE_PAST_DAYS`일 전부터)의 일정을 돌려준다.

    Args:
        db: DB 세션
        today: 기준 날짜
    Returns:
        종료일 빠른 순 일정
    """
    return deadline_crud.list_since(db, today - timedelta(days=DEADLINE_PAST_DAYS))


def _cost_rows(models: list[dict]) -> list[dict]:
    """기본 계산 조건(`COST_DEFAULTS`)으로 모델별 월 비용을 계산해 싼 순으로 돌려준다. 가격이 비어 있는 모델은 뺀다.

    Args:
        models: `_present` 결과 목록
    Returns:
        `{"id", "name", "href", "provider", "usd", "note", "verified", "source_url"}` 목록. 원화는 `_calc`가 환율을 곱해 만든다
    """
    rows = []
    for m in models:
        if not m["priced"]:
            continue
        per_request = (COST_DEFAULTS["input_tokens"] * m["input_raw"] + COST_DEFAULTS["output_tokens"] * m["output_raw"]) / 1_000_000
        rows.append({"id": m["id"], "name": m["name"], "href": m["href"], "provider": m["provider"], "usd": per_request * COST_DEFAULTS["requests"], "note": m["note"], "verified": m["verified"], "source_url": m["source_url"]})
    return sorted(rows, key=lambda r: (r["usd"], r["name"]))


def _calc(models: list[dict], meta: dict) -> dict:
    """계산기에 쓸 값을 만든다. 서버가 그린 기본 결과(`rows`)와 브라우저 스크립트에 넘길 모델 단가(`data`)를 함께 준다.

    Args:
        models: `_present` 결과 목록
        meta: `_load()["meta"]`
    Returns:
        템플릿에 넘길 값
    """
    rows = _cost_rows(models)
    for row in rows:
        row["krw"] = row["usd"] * meta["rate"]
    return {
        "defaults": COST_DEFAULTS,
        "fx": meta["rate"],
        "fx_date": meta["date"].isoformat(),
        "fx_source": meta["source"],
        "fx_url": meta["url"],
        "rows": rows,
        "data": {
            "fx": meta["rate"],
            "models": [{"id": m["id"], "name": m["name"], "href": m["href"], "provider": m["provider"], "in": m["input_raw"], "out": m["output_raw"], "note": m["note"], "verified": m["verified"], "source": m["source_url"]} for m in models if m["priced"]],
        },
    }


def _grouped(models: list[dict]) -> list[dict]:
    """모델을 제공사별로 묶는다. 제공사 안에서는 출력 단가가 높은 순이고 가격이 없는 모델은 맨 뒤다.

    Args:
        models: `_present` 결과 목록
    Returns:
        `{"provider", "slug", "rows", "sources"}` 목록. 모델이 없는 제공사는 뺀다
    """
    groups = []
    for provider in DEADLINE_PROVIDERS:
        rows = sorted((m for m in models if m["provider"] == provider), key=lambda m: (m["output_raw"] is None, -(m["output_raw"] or 0), m["name"]))
        if rows:
            groups.append({"provider": provider, "slug": provider.lower(), "rows": rows, "sources": sorted({m["source_url"] for m in rows})})
    return groups


def build_models(db: Session, base: str, today: date | None = None) -> dict:
    """모델 가격 비교표 화면에 필요한 값을 만든다.

    Args:
        db: DB 세션
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
        today: 기준 날짜(한국 시간). 비우면 오늘
    Returns:
        템플릿에 넘길 값
    """
    today = today or datetime.now(KST).date()
    data = _load()
    deadlines = _deadlines(db, today)
    models = [_present(m, deadlines, today) for m in data["models"]]
    title = "AI API 가격 비교 · Claude GPT Gemini 단가 · 종료일 · Deltalog"
    desc = "Claude, GPT, Gemini API 모델별 입력 · 출력 단가(100만 토큰당), 컨텍스트 크기, 종료 예정일을 한 표로 비교합니다. 공식 페이지 확인일과 출처를 함께 보여줍니다."
    return {
        "groups": _grouped(models),
        "total": len(models),
        "seo_title": title,
        "seo_desc": desc,
        "jsonld": _json_ld(
            [
                {
                    "@context": "https://schema.org",
                    "@type": "CollectionPage",
                    "name": "AI API 모델 가격 비교",
                    "url": f"{base}/models",
                    "inLanguage": "ko",
                    "description": desc,
                    "dateModified": max(m["verified"] for m in data["models"]).isoformat() if data["models"] else None,
                    "isPartOf": {"@type": "WebSite", "name": "Deltalog", "url": base},
                    "mainEntity": {
                        "@type": "ItemList",
                        "itemListElement": [{"@type": "ListItem", "position": i, "name": m["name"], "url": f"{base}{m['href']}"} for i, m in enumerate((x for x in models if x["priced"]), 1)],
                    },
                },
                _breadcrumb(base, [("모델 가격", "/models")]),
            ]
        ),
    }


def build_cost(base: str, today: date | None = None) -> dict:
    """전체 모델 월 비용 계산기 화면에 필요한 값을 만든다. 종료 일정은 쓰지 않아 DB를 읽지 않는다.

    Args:
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
        today: 기준 날짜(한국 시간). 비우면 오늘
    Returns:
        템플릿에 넘길 값
    """
    today = today or datetime.now(KST).date()
    data = _load()
    models = [_present(m, [], today) for m in data["models"]]
    title = "AI API 월 비용 계산기 · 토큰 · 요청 수로 원화 환산 · Deltalog"
    desc = "입력 · 출력 토큰과 월 요청 수를 넣으면 Claude, GPT, Gemini API의 월 비용을 달러와 원화로 계산합니다. 환율은 직접 고칠 수 있습니다."
    return {
        "calc": _calc(models, data["meta"]),
        "models_total": len(models),
        "seo_title": title,
        "seo_desc": desc,
        "jsonld": _json_ld(
            [
                {
                    "@context": "https://schema.org",
                    "@type": "WebApplication",
                    "name": "AI API 월 비용 계산기",
                    "url": f"{base}/models/cost",
                    "inLanguage": "ko",
                    "description": desc,
                    "applicationCategory": "UtilitiesApplication",
                    "operatingSystem": "Any",
                    "isAccessibleForFree": True,
                    "isPartOf": {"@type": "WebSite", "name": "Deltalog", "url": base},
                },
                _breadcrumb(base, [("모델 가격", "/models"), ("월 비용 계산기", "/models/cost")]),
            ]
        ),
    }


def build_model_detail(db: Session, model_id: str, base: str, today: date | None = None) -> dict | None:
    """모델 상세 화면에 필요한 값을 만든다. 가격이 비어 있는 모델은 `noindex`다. 검수를 마친(`reviewed = true`) 모델만 `editorial`에 편집 콘텐츠가 있고, 아니면 `None`이다.

    Args:
        db: DB 세션
        model_id: 모델 ID
        base: 사이트 주소 (끝 `/` 없음). JSON-LD의 주소에 쓴다
        today: 기준 날짜(한국 시간). 비우면 오늘
    Returns:
        템플릿에 넘길 값. 그런 모델이 없으면 `None`
    """
    today = today or datetime.now(KST).date()
    data = _load()
    deadlines = _deadlines(db, today)
    models = [_present(m, deadlines, today) for m in data["models"]]
    raw = next((m for m in data["models"] if m["id"] == model_id), None)
    if raw is None:
        return None
    model = next(m for m in models if m["id"] == model_id)
    for row in model["deadlines"]:
        target = next((m for m in data["models"] if m["provider"] == raw["provider"] and m["id"] != model_id and m["pattern"].search(row["replacement"].lower())), None)
        row["replacement_href"] = f"/models/{target['id']}" if target and row["replacement"] else ""
    first = model["next"]
    editorial = None
    if raw["editorial"]:
        by_id = {m["id"]: m for m in models}
        editorial = {**raw["editorial"], "reviewed_at": raw["editorial"]["reviewed_at"].isoformat(), "compare": [by_id[c] for c in raw["editorial"]["compare"]]}
    facts =[f"입력 {model['input']} · 출력 {model['output']} (100만 토큰당)"] if model["priced"] else []
    if model["context"] != "미확인":
        facts.append(f"컨텍스트 {model['context']}")
    if model["max_output"] != "미확인":
        facts.append(f"최대 출력 {model['max_output']}")
    if first:
        facts.append(f"종료 예정 {first['date']}")
    desc = f"{model['name']} API 가격 · 한도 · 종료일. {', '.join(facts)}. 최종 확인 {model['verified']}." if facts else f"{model['name']} API 가격 · 한도 · 종료일. 최종 확인 {model['verified']}."
    path = f"/models/{model_id}"
    siblings = [m for m in models if m["provider"] == raw["provider"] and m["id"] != model_id][:MODEL_SIBLINGS]
    return {
        "m": model,
        "first": first,
        "editorial": editorial,
        "siblings": siblings,
        "calc": _calc([model], data["meta"]),
        "noindex": not model["priced"],
        "seo_title": f"{model['name']} API 가격 · 컨텍스트 · 종료일 · Deltalog",
        "seo_desc": desc,
        "jsonld": _json_ld(
            [
                {
                    "@context": "https://schema.org",
                    "@type": "WebPage",
                    "name": f"{model['name']} API 가격 · 한도 · 종료일",
                    "url": f"{base}{path}",
                    "inLanguage": "ko",
                    "description": desc,
                    "dateModified": model["verified"],
                    "isPartOf": {"@type": "WebSite", "name": "Deltalog", "url": base},
                },
                _breadcrumb(base, [("모델 가격", "/models"), (model["name"], path)]),
            ]
        ),
    }


def sitemap_urls() -> list[tuple[str, str]]:
    """사이트맵에 넣을 모델 페이지의 `(경로, lastmod)`를 돌려준다. 가격이 비어 있는 모델 상세는 `noindex`라 뺀다.

    Returns:
        `(경로, YYYY-MM-DD)` 목록. `lastmod`는 가격을 확인한 날짜다
    """
    models = _load()["models"]
    if not models:
        return []
    newest = max(m["verified"] for m in models).isoformat()
    urls = [("/models", newest), ("/models/cost", newest)]
    urls += [(f"/models/{m['id']}", m["verified"].isoformat()) for m in models if m["input"] is not None and m["output"] is not None]
    return urls