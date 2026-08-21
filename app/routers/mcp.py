"""
Minimal MCP-like JSON-RPC + agent loop endpoint.
Any agent can POST here, or use the SSE stream.
Also exposes /mcp/tools/list for opencode mcp discovery.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, Optional
from app.rag.agent_loop import agentic_ask, agentic_stream
from fastapi.responses import StreamingResponse
import json

router = APIRouter(prefix="/mcp", tags=["mcp"])
agent_router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

class AskReq(BaseModel):
    query: str
    stream: bool = False

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
    tool = body.get("tool") or body.get("method")
    args = body.get("args") or body.get("params") or {}
    if tool in ("qa.ask", "agent.ask"):
        res = await agentic_ask(args.get("query") or body.get("query", ""))
        return res
    return {"error": f"unknown tool {tool}"}

@agent_router.post("/ask")
async def ask(req: AskReq):
    if req.stream:
        async def gen():
            async for chunk in agentic_stream(req.query):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")
    else:
        return await agentic_ask(req.query)
