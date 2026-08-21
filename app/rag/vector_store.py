"""
RAG stub — pluggable. Uses Qdrant if available, else in-memory list.
Called by worker to embed logs/traces for later querying via agent_loop.
"""
from typing import List, Dict, Any, Optional

class VectorStore:
    def __init__(self, url: str = "", api_key: str = ""):
        self.url = url
        self.api_key = api_key
        self.enabled = bool(url)
        self._mem: List[Dict[str, Any]] = []
        self.client = None
        if self.enabled:
            try:
                from qdrant_client import QdrantClient
                self.client = QdrantClient(url=url, api_key=api_key or None, timeout=5)
                # ensure collection
                from qdrant_client.models import Distance, VectorParams
                try:
                    self.client.get_collection("qa_traces")
                except Exception:
                    self.client.create_collection(
                        collection_name="qa_traces",
                        vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                    )
            except Exception as e:
                print(f"[rag] qdrant unavailable: {e}, fallback to memory")
                self.enabled = False
                self.client = None

    async def embed_and_upsert(self, test_id: str, text: str, metadata: Dict[str, Any]):
        # if OPENAI_API_KEY set, embed; else store raw text for keyword search
        vector = None
        try:
            import os
            if os.getenv("OPENAI_API_KEY"):
                from openai import OpenAI
                client = OpenAI()
                resp = client.embeddings.create(model="text-embedding-3-small", input=text[:8000])
                vector = resp.data[0].embedding
        except Exception as e:
            print(f"[rag] embed failed: {e}")

        if self.enabled and self.client and vector:
            try:
                from qdrant_client.models import PointStruct
                import uuid
                self.client.upsert(
                    collection_name="qa_traces",
                    points=[PointStruct(id=str(uuid.uuid4()), vector=vector, payload={"test_id": test_id, "text": text[:2000], **metadata})],
                )
                return
            except Exception as e:
                print(f"[rag] qdrant upsert failed: {e}")

        # memory fallback
        self._mem.append({"test_id": test_id, "text": text, "metadata": metadata})
        if len(self._mem) > 1000:
            self._mem = self._mem[-1000:]

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        # naive keyword search for memory fallback
        q = query.lower()
        scored = sorted(self._mem, key=lambda x: x["text"].lower().count(q), reverse=True)
        return scored[:top_k]

vector_store = VectorStore(url=__import__("app.config", fromlist=["settings"]).settings.qdrant_url,
                           api_key=__import__("app.config", fromlist=["settings"]).settings.qdrant_api_key)
