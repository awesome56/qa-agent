"""
Minimal MCP-like JSON-RPC + agent loop endpoint.
Any agent can POST here, or use the SSE stream.
Also exposes /mcp/tools/list for opencode mcp discovery.
Handles both GET (SSE) and POST (JSON-RPC) for /mcp and /mcp/call to avoid 405.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional
from app.rag.agent_loop import agentic_ask, agentic_stream
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import json
import asyncio

router = APIRouter(prefix="/mcp", tags=["mcp"])
agent_router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

async def _mcp_sse_gen():
    # initial tools list + heartbeat
    tools = [
        {"name": "qa.run_test", "description": "Run e2e + stress test with recording", "inputSchema": {"type":"object","properties":{"target_url":{"type":"string"},"vus":{"type":"integer"},"duration":{"type":"string"}}}},
        {"name": "qa.ask", "description": "Ask RAG/graph about prior test runs", "inputSchema": {"type":"object","properties":{"query":{"type":"string"}}}},
        {"name": "qa.daily_report", "description": "Get daily report", "inputSchema": {"type":"object","properties":{"day":{"type":"string"}}}},
    ]
    yield {"event": "tools", "data": json.dumps({"tools": tools})}
    yield {"event": "ready", "data": json.dumps({"status": "ok", "service": "qa-agent", "sse": True})}
    # keepalive every 15s
    while True:
        await asyncio.sleep(15)
        yield {"event": "ping", "data": json.dumps({"ts": __import__("datetime").datetime.utcnow().isoformat()})}

class AskReq(BaseModel):
    query: str
    stream: bool = False
    model: Optional[str] = None

@router.get("")
async def mcp_root_get(request: Request):
    # Always return SSE for GET to avoid 405 — opencode remote expects text/event-stream
    return EventSourceResponse(_mcp_sse_gen())

@router.get("/call")
async def mcp_call_get(request: Request):
    return EventSourceResponse(_mcp_sse_gen())

@router.post("")
async def mcp_root_post(body: Dict[str, Any]):
    return await mcp_call(body)

@router.get("/tools/list")
async def tools_list():
    return {
        "tools": [
            {"name": "qa.run_test", "description": "Run e2e + stress test with recording", "inputSchema": {"type":"object","properties":{"target_url":{"type":"string"},"vus":{"type":"integer"},"duration":{"type":"string"}}}},
            {"name": "qa.ask", "description": "Ask RAG/graph about prior test runs", "inputSchema": {"type":"object","properties":{"query":{"type":"string"}}}},
            {"name": "qa.daily_report", "description": "Get daily report", "inputSchema": {"type":"object","properties":{"day":{"type":"string"}}}},
        ]
    }

@router.post("/call")
async def mcp_call(body: Dict[str, Any]):
    # Handle MCP JSON-RPC initialize, tools/list, tools/call, and our custom qa.* tools
    method = body.get("method") or body.get("tool")
    params = body.get("params") or body.get("args") or {}
    # MCP handshake
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "qa-agent", "version": "0.1.0"}}}
    if method in ("tools/list", "tools/list_tools"):
        return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": [
            {"name": "qa.run_test", "description": "Run e2e + stress test with recording", "inputSchema": {"type":"object","properties":{"target_url":{"type":"string"},"vus":{"type":"integer"},"duration":{"type":"string"}}}},
            {"name": "qa.ask", "description": "Ask RAG/graph about prior test runs", "inputSchema": {"type":"object","properties":{"query":{"type":"string"}}}},
            {"name": "qa.daily_report", "description": "Get daily report", "inputSchema": {"type":"object","properties":{"day":{"type":"string"}}}},
        ]}}
    if method in ("tools/call", "tool/call"):
        tool = params.get("name") or params.get("tool")
        args = params.get("arguments") or params.get("args") or {}
        if tool in ("qa.ask", "agent.ask"):
            res = await agentic_ask(args.get("query") or body.get("query", ""), model=args.get("model") or params.get("model") or body.get("model"))
            return {"jsonrpc": "2.0", "id": body.get("id"), "result": res}
        if tool == "qa.run_test":
            # delegate to test run — for now return error, actual run via POST /api/v1/test/run
            return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "Use POST /api/v1/test/run for qa.run_test"}}
        return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": f"unknown tool {tool}"}}
    tool = body.get("tool") or body.get("method")
    args = body.get("args") or body.get("params") or {}
    if tool in ("qa.ask", "agent.ask"):
        res = await agentic_ask(args.get("query") or body.get("query", ""), model=args.get("model") or body.get("model"))
        return res
    if tool in ("qa.run_test", "qa.daily_report"):
        # for MCP list, return tools
        return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": []}}
    return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": f"unknown method {method or tool}"}}

@agent_router.post("/ask")
async def ask(req: AskReq):
    if req.stream:
        async def gen():
            async for chunk in agentic_stream(req.query, model=req.model):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    else:
        return await agentic_ask(req.query, model=req.model)
