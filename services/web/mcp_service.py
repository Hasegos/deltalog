from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from core.constants.deadline import DEADLINE_PROVIDERS
from core.constants.news import NEWS_COMPANIES
from core.constants.page import KST
from crud import deadline_crud, entry_crud, item_crud, news_crud
from services.web.changes_service import build_changes

SERVER_INFO = {"name": "deltalog", "title": "Deltalog", "version": "1.0.0"}
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Deltalog는 AI 코딩 도구와 IDE의 릴리스 노트, 제작사 공식 소식, 모델 · API 종료 일정을 한국어로 요약해 모은 서비스입니다. "
    "요약은 AI가 만들었으니 중요한 결정 전에는 각 항목의 원문 링크를 확인하세요."
)
MAX_ROWS = 20

TOOLS = [
    {
        "name": "list_tools",
        "description": "Deltalog가 추적하는 도구(Claude Code, Codex, Cursor, VS Code 등)의 slug, 이름, 가장 최근 버전과 게시일을 돌려준다. 다른 도구의 tool 값을 모를 때 먼저 부른다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_updates_since",
        "description": "지금 쓰는 버전 이후 최신 버전까지 바뀐 점을 한국어로 요약해 돌려준다. 업그레이드 전에 꼭 볼 breaking · 보안 변경을 먼저 준다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "도구 slug. 예: claude-code (list_tools로 확인)"},
                "version": {"type": "string", "description": "지금 쓰는 버전. 예: 2.1.290"},
                "level": {"type": "string", "enum": ["key", "all"], "description": "key는 중요도 4 이상과 breaking · 보안만(기본), all은 요약된 전부"},
            },
            "required": ["tool", "version"],
        },
    },
    {
        "name": "get_upcoming_deadlines",
        "description": "Anthropic, OpenAI, Google이 공식 문서에 예고한 모델 · API 종료 일정을 종료일이 빠른 순으로 돌려준다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 365, "description": "오늘부터 며칠 안의 일정(기본 90)"},
                "provider": {"type": "string", "enum": DEADLINE_PROVIDERS, "description": "제공사로 거르기(기본 전체)"},
            },
        },
    },
    {
        "name": "get_recent_news",
        "description": "제작사의 최근 공식 소식을 중요도 높은 순이 아니라 최신순으로 돌려준다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "enum": NEWS_COMPANIES, "description": "제작사로 거르기(기본 전체)"},
                "min_importance": {"type": "integer", "minimum": 1, "maximum": 5, "description": "최소 중요도(기본 3)"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ROWS, "description": "최대 개수(기본 10)"},
            },
        },
    },
]


def _int(value, default: int, low: int, high: int) -> int:
    """정수로 읽어 범위 안으로 맞춘다. 읽지 못하면 기본값이다."""
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _list_tools(db: Session, _args: dict) -> dict:
    out = []
    for source in item_crud.list_sources(db):
        latest = entry_crud.list_source_entries(db, source.id, 1)
        out.append(
            {
                "tool": source.slug,
                "name": source.name,
                "latest_version": (latest[0].version or latest[0].title) if latest else None,
                "published": latest[0].published_at.date().isoformat() if latest else None,
            }
        )
    return {"tools": out}


def _updates(db: Session, args: dict) -> dict:
    data = build_changes(db, str(args.get("tool", "")), str(args.get("version", "")).strip(), "all" if args.get("level") == "all" else "key")
    if data["error"]:
        raise ValueError(data["error"])
    result = data["result"]
    if result is None:
        raise ValueError("tool과 version이 필요합니다.")
    if result["releases"] == 0:
        return {"tool": result["source"], "from": data["version"], "newest": result["newest"], "message": "이미 최신 버전 이상입니다."}
    return {
        "tool": result["source"],
        "from": data["version"],
        "to": result["newest"],
        "releases": result["releases"],
        "pending_summaries": result["pending"],
        "counts": {c["label"]: c["count"] for c in result["counts"]},
        "check_before_upgrade": [{"type": m["label"], "version": m["version"], "summary": m["summary"], "url": m["url"]} for m in result["must"]],
        "check_before_upgrade_total": result["must_total"],
        "changes": [
            {"type": g["label"], "items": [{"version": r["version"], "summary": r["summary"], "importance": r["importance"], "url": r["url"]} for r in g["rows"][:MAX_ROWS]], "total": len(g["rows"])}
            for g in result["groups"]
        ],
    }


def _deadlines(db: Session, args: dict) -> dict:
    today = datetime.now(KST).date()
    provider = args.get("provider") if args.get("provider") in DEADLINE_PROVIDERS else ""
    rows = deadline_crud.list_range(db, today, today + timedelta(days=_int(args.get("days"), 90, 1, 365)), 50)
    return {
        "deadlines": [
            {"provider": r.provider, "name": r.name, "deadline": r.deadline.isoformat(), "days_left": (r.deadline - today).days, "replacement": r.replacement, "summary": r.summary_ko, "url": r.source_url}
            for r in rows
            if not provider or r.provider == provider
        ]
    }


def _news(db: Session, args: dict) -> dict:
    company = [args["company"]] if args.get("company") in NEWS_COMPANIES else []
    rows = news_crud.list_for_feed(db, company, _int(args.get("min_importance"), 3, 1, 5), _int(args.get("limit"), 10, 1, MAX_ROWS))
    return {
        "news": [
            {"company": n.company, "title": n.title_ko or n.title, "summary": n.summary_ko, "importance": n.importance, "published": n.published_at.date().isoformat(), "url": n.url}
            for n in rows
        ]
    }


HANDLERS = {"list_tools": _list_tools, "get_updates_since": _updates, "get_upcoming_deadlines": _deadlines, "get_recent_news": _news}


def call_tool(db: Session, name: str, args: dict) -> dict | None:
    """도구 하나를 실행해 JSON으로 돌려줄 값을 만든다.

    Args:
        db: DB 세션
        name: 도구 이름
        args: 인자
    Returns:
        결과. 그런 도구가 없으면 `None`
    Raises:
        ValueError: 인자가 틀렸을 때 (메시지를 그대로 사용자에게 보인다)
    """
    handler = HANDLERS.get(name)
    return handler(db, args) if handler else None