import re
from datetime import datetime

import httpx

from core.config import settings
from core.constants.model import PRICE_DOCS, PRICE_FORMAT_MISS_RATIO, PRICE_SNIPPET_CHARS
from core.constants.page import KST
from core.logger import get_logger
from services.web.model_service import _load

logger = get_logger("price_check")
_PRICE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_state: dict = {"checked_at": None, "providers": {}}


def _price(cell: str) -> float | None:
    """칸의 첫 `$` 금액을 돌려준다. 없으면 `None`. `$0.75 through ... $1.50 starting ...`처럼 날짜별 가격이 이어지면 현재 가격인 앞쪽이다."""
    match = _PRICE.search(cell)
    return float(match.group(1).replace(",", "")) if match else None


def _cells(line: str) -> list[str]:
    """마크다운 표의 한 행을 칸 목록으로 나눈다."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_row(text: str, key: str) -> list[str] | None:
    """가격표(Anthropic · OpenAI)에서 첫 칸이 `key`인 첫 행을 찾는다. `gpt-5.5`가 `gpt-5.5-pro`와 섞이지 않도록 이름 뒤는 칸 끝이나 `(`여야 한다.

    Args:
        text: 가격표 마크다운
        key: 모델 이름 또는 ID
    Returns:
        칸 목록. 없으면 `None`
    """
    pattern = re.compile(r"(?im)^\|\s*" + re.escape(key) + r"\s*(?:\(|<|\|)[^\n]*$")
    match = pattern.search(text)
    return _cells(match.group(0)) if match else None


def _google_rows(text: str, model_id: str) -> list[list[str]] | None:
    """Google 가격 페이지에서 모델 ID가 머리글에 적힌 구역의 `Standard` 표에서 입력 · 출력 행을 찾는다.

    Args:
        text: 가격 페이지 마크다운
        model_id: 모델 ID
    Returns:
        `[입력 행 칸, 출력 행 칸]`. 구역이나 행이 없으면 `None`
    """
    for section in re.split(r"(?m)^## ", text):
        if f"`{model_id}`" not in section.split("###", 1)[0]:
            continue
        standard = re.search(r"(?ms)^### Standard\s*\n(.*?)(?=^##|\Z)", section)
        if not standard:
            return None
        rows = {
            label: _cells(line)
            for line in standard.group(1).splitlines()
            for label in ("Input price", "Output price")
            if line.startswith(f"| {label}")
        }
        return [rows["Input price"], rows["Output price"]] if len(rows) == 2 else None
    return None


def _found(provider: str, text: str, model: dict) -> tuple[float | None, float | None, str] | None:
    """공식 가격표에서 모델의 입력 · 출력 단가와 근거 행을 읽는다.

    Args:
        provider: 제공사
        text: 가격표 마크다운
        model: `model_service`의 모델
    Returns:
        `(입력, 출력, 근거 행 글)`. 모델 행을 못 찾으면 `None`
    """
    key = model[PRICE_DOCS[provider]["key"]]
    if "stop" in PRICE_DOCS[provider]:
        # 표준 가격표 뒤에 배치 · 캐시 등 같은 모델의 다른 단가 표가 이어져, 표준 행이 사라졌을 때 엉뚱한 표의 행을 집지 않게 자른다
        text = re.split(PRICE_DOCS[provider]["stop"], text, maxsplit=1)[0]
    if provider == "Google":
        rows = _google_rows(text, key)
        return (_price(rows[0][-1]), _price(rows[1][-1]), " / ".join(r[0] + ": " + r[-1] for r in rows)) if rows else None
    row = _table_row(text, key)
    if not row or len(row) < 3:
        return None
    # Anthropic 표는 [이름, 입력, 캐시 쓰기 5분, 1시간, 캐시 읽기, 출력], OpenAI 표는 [이름, 입력, 출력, ...]
    out = row[-1] if provider == "Anthropic" else row[2]
    return _price(row[1]), _price(out), " | ".join(row)


def _money(value: float) -> str:
    return f"${value:g}"


def check(provider: str, text: str, models: list[dict]) -> dict:
    """제공사 한 곳의 TOML 단가가 공식 가격표에 그대로 있는지 확인한다. 의미를 해석하지 않고 숫자가 같은지만 본다.

    Args:
        provider: 제공사
        text: 가격표 마크다운
        models: 그 제공사의 단가가 있는 모델 목록
    Returns:
        `{"checked": 확인한 모델 수, "items": 어긋난 항목 목록, "format": 형식이 바뀐 듯한지}`. 항목은 `{"name", "problem", "row"}`
    """
    items, missing = [], 0
    for model in models:
        found = _found(provider, text, model)
        if found is None:
            missing += 1
            items.append({"name": model["name"], "problem": "공식 가격표에서 이 모델을 찾지 못했습니다", "row": ""})
            continue
        got_in, got_out, row = found
        problems = [
            f"{label} 단가가 다릅니다 (우리 {_money(want)} · 공식 {_money(got) if got is not None else '읽지 못함'})"
            for label, want, got in (("입력", model["input"], got_in), ("출력", model["output"], got_out))
            if got is None or abs(got - want) > 1e-9
        ]
        if problems:
            items.append({"name": model["name"], "problem": " · ".join(problems), "row": row[:PRICE_SNIPPET_CHARS]})
    if models and missing / len(models) > PRICE_FORMAT_MISS_RATIO:
        return {"checked": len(models), "items": [{"name": provider, "problem": f"모델 {len(models)}개 중 {missing}개를 못 찾았습니다. 공식 가격 페이지의 형식이 바뀐 듯합니다", "row": ""}], "format": True}
    return {"checked": len(models), "items": items, "format": False}


def check_prices_job() -> None:
    """`data/models.toml`의 단가를 공식 가격 페이지와 대조해 결과를 메모리에 둔다. 어긋나도 TOML은 고치지 않는다. 사람이 공식 페이지를 보고 고친다."""
    try:
        models = _load()["models"]
    except Exception:
        logger.exception("모델 데이터를 읽지 못했습니다")
        return
    providers = {}
    for provider, doc in PRICE_DOCS.items():
        priced = [m for m in models if m["provider"] == provider and m["input"] is not None and m["output"] is not None]
        try:
            response = httpx.get(doc["url"], headers={"User-Agent": settings.COLLECTOR_USER_AGENT}, timeout=settings.FEED_TIMEOUT_SEC, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("가격 페이지 요청 실패: %s (%s)", provider, exc.__class__.__name__)
            providers[provider] = {"checked": 0, "items": [], "format": False, "error": f"가격 페이지를 받지 못했습니다 ({exc.__class__.__name__})"}
            continue
        providers[provider] = {**check(provider, response.text, priced), "error": None}
        logger.info("가격 대조: %s 모델 %d개, 어긋남 %d건", provider, len(priced), len(providers[provider]["items"]))
    _state.update(checked_at=datetime.now(KST), providers=providers)


def latest() -> dict:
    """가장 최근 대조 결과를 돌려준다. 아직 돌지 않았으면 `checked_at`이 `None`이다."""
    return _state