"""
Agentic loop — any agent can call via HTTP or MCP to ask questions over RAG/graph.
Example: POST /api/v1/agent/ask {"query":"why did checkout fail?"}
"""
from typing import AsyncGenerator, Dict, Any
from app.rag.vector_store import vector_store
from app.rag.graph import graph_store

SYSTEM = "You are QA Agent — you analyze test runs, traces, and k6 results. Answer concisely with evidence."

async def agentic_ask(query: str, context_limit: int = 5) -> Dict[str, Any]:
    # retrieve from vector + graph
    hits = vector_store.search(query, top_k=context_limit)
    graph_hits = graph_store.query(limit=context_limit)

    context = "\n\n".join([f"[{h['test_id']}] {h['text'][:600]}" for h in hits]) or "no prior traces"
    graph_ctx = str(graph_hits[:3])

    # if OPENAI_API_KEY, do LLM; else return retrieved context
    import os
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI()
            resp = client.chat.completions.create(
                model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Query: {query}\n\nRAG context:\n{context}\n\nGraph:\n{graph_ctx}"}
                ],
                temperature=0.2,
            )
            answer = resp.choices[0].message.content
            return {"answer": answer, "sources": hits, "graph": graph_hits}
        except Exception as e:
            return {"answer": f"LLM error: {e}\n\nContext:\n{context}", "sources": hits, "graph": graph_hits}
    else:
        return {"answer": f"(no LLM key) Retrieved {len(hits)} traces. Top hit: {hits[0]['text'][:400] if hits else 'none'}", "sources": hits, "graph": graph_hits}

async def agentic_stream(query: str) -> AsyncGenerator[str, None]:
    # SSE streaming version — yields chunks
    result = await agentic_ask(query)
    # naive chunk
    chunk_size = 80
    ans = result["answer"]
    for i in range(0, len(ans), chunk_size):
        yield ans[i:i+chunk_size]
