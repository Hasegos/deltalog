import json

from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy.orm import Session

from db.session import get_db
from services.web import mcp_service

router = APIRouter()

HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}


def _error(rpc_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _handle(db: Session, message: object) -> dict | None:
    """JSON-RPC 요청 하나를 처리한다. 알림(`id` 없음)은 답하지 않는다.

    Args:
        db: DB 세션
        message: 요청 본문 하나
    Returns:
        JSON-RPC 응답. 알림이면 `None`
    """
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(None, -32600, "Invalid Request")
    method, rpc_id, params = message["method"], message.get("id"), message.get("params") or {}
    if "id" not in message:
        return None
    if method == "initialize":
        asked = params.get("protocolVersion") if isinstance(params, dict) else None
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": asked if asked in mcp_service.PROTOCOLS else mcp_service.PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": mcp_service.SERVER_INFO,
                "instructions": mcp_service.INSTRUCTIONS,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": mcp_service.TOOLS}}
    if method == "tools/call":
        name = params.get("name") if isinstance(params, dict) else None
        args = params.get("arguments") if isinstance(params, dict) else None
        try:
            data = mcp_service.call_tool(db, str(name), args if isinstance(args, dict) else {})
        except ValueError as exc:
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}}
        if data is None:
            return _error(rpc_id, -32602, f"Unknown tool: {name}")
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": False}}
    return _error(rpc_id, -32601, f"Method not found: {method}")


@router.post("/mcp", include_in_schema=False)
def mcp(payload: dict | list = Body(...), db: Session = Depends(get_db)) -> Response:
    """MCP(Model Context Protocol) 서버. Streamable HTTP의 JSON 응답 방식만 지원하고, 세션 없이 읽기 전용 도구 4개를 연다. 키는 필요 없다.

    Args:
        payload: JSON-RPC 요청 하나 또는 배열
        db: 요청에 쓸 DB 세션
    Returns:
        JSON-RPC 응답(`200`). 알림만 보냈으면 본문 없는 `202`
    """
    if isinstance(payload, list):
        replies = [r for r in (_handle(db, m) for m in payload) if r is not None]
        body = replies or None
    else:
        body = _handle(db, payload)
    if body is None:
        return Response(status_code=202, headers=HEADERS)
    return Response(json.dumps(body, ensure_ascii=False), media_type="application/json", headers=HEADERS)