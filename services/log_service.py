import json
from collections import Counter
from pathlib import Path

from core.config import settings


def _read(day: str, filename: str) -> list[dict]:
    """날짜 폴더의 JSON 줄 로그를 읽는다. 파일이 없거나 JSON이 아닌 줄은 건너뛴다.

    Args:
        day: `YYYY-MM-DD`
        filename: `api.log` 또는 `llm.log`
    Returns:
        기록 목록
    """
    path = Path(settings.LOG_DIR) / day / filename
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def day_stats(day: str) -> dict:
    """하루치 `api.log`와 `llm.log`를 집계한다.

    Args:
        day: `YYYY-MM-DD`
    Returns:
        `api`(요청 수, 접속자 수, IP · 경로 · 상태별 개수)와 `llm`(호출 수, 성공 · 실패, 평균 시간, 토큰 합계, 요약 묶음 수)
    """
    api = _read(day, "api.log")
    calls = [r for r in _read(day, "llm.log") if r.get("event") == "call"]
    batches = [r for r in _read(day, "llm.log") if r.get("event") == "batch"]
    ok_calls = [r for r in calls if r.get("ok")]
    return {
        "api": {
            "requests": len(api),
            "visitors": len({r.get("ip") for r in api}),
            "by_ip": Counter(r.get("ip") for r in api).most_common(10),
            "by_path": Counter(r.get("path") for r in api).most_common(10),
            "by_status": sorted(Counter(r.get("status") for r in api).items()),
        },
        "llm": {
            "calls": len(calls),
            "ok": len(ok_calls),
            "failed": len(calls) - len(ok_calls),
            "avg_ms": round(sum(r.get("ms", 0) for r in ok_calls) / len(ok_calls)) if ok_calls else 0,
            "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in ok_calls),
            "completion_tokens": sum(r.get("completion_tokens") or 0 for r in ok_calls),
            "batches": len(batches),
            "items_done": sum(r.get("done", 0) for r in batches),
            "items_failed": sum(r.get("failed", 0) for r in batches),
        },
    }