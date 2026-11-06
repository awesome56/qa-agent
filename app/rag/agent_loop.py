"""
Agentic loop — any agent can call via HTTP or MCP to ask questions over RAG/graph.
Example: POST /api/v1/agent/ask {"query":"why did checkout fail?"}
"""
from typing import AsyncGenerator, Dict, Any
from app.rag.vector_store import vector_store
from app.rag.graph import graph_store

SYSTEM = "You are QA Agent (muse-spark-1.2) — you analyze test runs, traces, and k6 results. Answer concisely with evidence. Prefer edge cases for hrms-new."

# deepseek-v4-flash is the current working model on opencode-go/zen (muse-spark-1.2 currently 500)
DEFAULT_MODEL = "deepseek-v4-flash"

async def _call_llm(prompt: str, system: str = SYSTEM, model: str | None = None) -> str:
    import os, json as _json
    from pathlib import Path as _P

    # Prefer the SAME credential opencode/Awesome_App uses (opencode-go provider)
    api_key = os.getenv("OPENCODE_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("MUSE_API_KEY")
    base_url = os.getenv("OPENCODE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    auth_file = _P.home() / ".local/share/opencode/auth.json"
    if auth_file.exists():
        try:
            auth = _json.loads(auth_file.read_text())
            if "opencode-go" in auth:
                api_key = auth["opencode-go"].get("key") or api_key
                base_url = base_url or "https://opencode.ai/zen/go/v1"  # opencode-go OpenAI-compatible gateway
        except Exception:
            pass
    if not api_key:
        return ""
    model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    # strip provider/ prefix so Awesome_App's "opencode-go/muse-spark-1.2-contributor" -> "muse-spark-1.2-contributor"
    if "/" in model:
        model = model.split("/")[-1]
    # support via OpenAI-compatible endpoint (opencode gateway) or direct OpenAI
    # try requested model, fallback to deepseek if muse-spark 500
    for try_model in ([model] + (["deepseek-v4-flash"] if "muse-spark" in model else [])):
        try:
            from openai import OpenAI
            kwargs = {}
            if base_url:
                kwargs["base_url"] = base_url
            client = OpenAI(api_key=api_key, **kwargs)
            resp = client.chat.completions.create(
                model=try_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                temperature=0.25,
            )
            txt = resp.choices[0].message.content or ""
            if txt:
                return txt
        except Exception as e:
            err = f"[LLM error {try_model}: {e}]"
            # if muse-spark 500, try fallback
            if "muse-spark" in try_model and "500" in str(e):
                continue
            return err
    return f"[LLM error {model}: all retries failed]"

async def generate_edge_cases(feature: str, target_url: str, project: str = "other", scope: str = "edge_cases", model: str | None = None) -> Dict[str, Any]:
    """Called by playwright_worker when scope includes edge_cases. Uses model from request or env, defaults to muse-spark-1.2."""
    import os, json as _json
    prompt = f"""Project: {project}
Feature/bug: {feature}
URL: {target_url}
Scope: {scope}
Generate 8-12 edge cases for QA. Cover: empty, XSS, SQLi, 1000-char, past date, overlapping, permission denied, concurrent, network drop, auth expired, concurrent submit, invalid file type.
Return JSON: {{"cases":[{{"title":"","steps":[""],"expected":""}}]}}
"""
    txt = await _call_llm(prompt, system=SYSTEM, model=model)
    if txt and "cases" in txt:
        try:
            start = txt.find("{")
            end = txt.rfind("}")+1
            data = _json.loads(txt[start:end])
            if "cases" in data:
                return {"cases": data["cases"], "raw": txt, "model": model or os.getenv("LLM_MODEL", DEFAULT_MODEL)}
        except Exception:
            pass
    # heuristic fallback (no LLM key)
    fallback = [
        {"title":"Empty required fields","steps":["Leave all required blank","Submit"],"expected":"Validation error"},
        {"title":"XSS in name","steps":[f"Set name to <script>alert(1)</script> on {target_url}","Submit"],"expected":"Sanitized, no execution"},
        {"title":"1000-char overflow","steps":["Fill text field with 1000 'a'","Submit"],"expected":"Truncated or error"},
        {"title":"Past date","steps":["Set date to yesterday","Submit"],"expected":"Reject or warning"},
        {"title":"Overlapping leave","steps":["Create leave overlapping existing"],"expected":"Conflict error"},
        {"title":"Permission denied","steps":["Login as tester without perm, access feature"],"expected":"403 with message"},
        {"title":"Concurrent submit","steps":["Double-click submit quickly"],"expected":"Single creation, second ignored"},
        {"title":"Network drop mid-submit","steps":["Throttle offline after click"],"expected":"Retry or error toast"},
        {"title":"Auth expired","steps":["Clear cookies, reload target"],"expected":"Redirect to login"},
        {"title":"Invalid file type","steps":["Upload .exe where image expected"],"expected":"Invalid type error"},
    ]
    if project == "hrms-new" and "leave" in feature.lower():
        fallback.insert(0, {"title":"Approve own leave","steps":["Create leave as tester, approve as same user"],"expected":"Forbidden"})
    return {"cases": fallback, "raw": txt or "(heuristic fallback — set OPENAI_API_KEY + LLM_MODEL=muse-spark-1.2 for LLM)", "model": model or os.getenv("LLM_MODEL", DEFAULT_MODEL)}

async def agentic_ask(query: str, context_limit: int = 5, model: str | None = None) -> Dict[str, Any]:
    hits = vector_store.search(query, top_k=context_limit)
    graph_hits = graph_store.query(limit=context_limit)
    context = "\n\n".join([f"[{h['test_id']}] {h['text'][:600]}" for h in hits]) or "no prior traces"
    graph_ctx = str(graph_hits[:3])
    import os
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENCODE_API_KEY")
    eff_model = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    if api_key:
        ans = await _call_llm(f"Query: {query}\n\nRAG context:\n{context}\n\nGraph:\n{graph_ctx}", model=eff_model)
        if ans and not ans.startswith("[LLM error"):
            return {"answer": ans, "sources": hits, "graph": graph_hits, "model": eff_model}
        return {"answer": f"{ans}\n\nContext:\n{context}", "sources": hits, "graph": graph_hits, "model": eff_model}
    else:
        return {"answer": f"(no LLM key) Retrieved {len(hits)} traces. Top hit: {hits[0]['text'][:400] if hits else 'none'} — set OPENAI_API_KEY + LLM_MODEL=muse-spark-1.2", "sources": hits, "graph": graph_hits, "model": eff_model}

async def agentic_stream(query: str, model: str | None = None) -> AsyncGenerator[str, None]:
    result = await agentic_ask(query, model=model)
    chunk_size = 80
    ans = result["answer"]
    for i in range(0, len(ans), chunk_size):
        yield ans[i:i+chunk_size]
