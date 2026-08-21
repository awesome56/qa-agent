"""
Graph stub — Neo4j if available, else in-memory dict.
Nodes: TestRun -> Feature -> Failure
"""
from typing import Dict, Any, List
from datetime import datetime

class GraphStore:
    def __init__(self, uri: str = "", user: str = "", password: str = ""):
        self.enabled = bool(uri and password != "qa-agent-pass" or uri != "bolt://neo4j:7687")
        # actually try to connect if creds look real
        self.driver = None
        self._mem: List[Dict[str, Any]] = []
        if uri:
            try:
                from neo4j import GraphDatabase
                import os
                # only connect if env explicitly set or reachable
                if os.getenv("NEO4J_PASSWORD") or uri != "bolt://neo4j:7687":
                    self.driver = GraphDatabase.driver(uri, auth=(user, password))
                    self.driver.verify_connectivity()
                    self.enabled = True
                    print("[graph] neo4j connected")
            except Exception as e:
                print(f"[graph] neo4j unavailable: {e}, using memory")
                self.driver = None
                self.enabled = False

    def add_run(self, test_id: str, target_url: str, scenario: str, status: str, meta: Dict[str, Any] = None):
        entry = {"test_id": test_id, "target_url": target_url, "scenario": scenario, "status": status, "ts": datetime.utcnow().isoformat(), "meta": meta or {}}
        if self.enabled and self.driver:
            try:
                with self.driver.session() as s:
                    s.run(
                        "MERGE (t:TestRun {id:$id}) SET t.target=$target, t.scenario=$scenario, t.status=$status, t.ts=$ts",
                        id=test_id, target=target_url, scenario=scenario, status=status, ts=entry["ts"]
                    )
                    if meta and meta.get("failed_checks"):
                        s.run("MATCH (t:TestRun {id:$id}) MERGE (f:Failure {id:$fid}) SET f.reason=$reason MERGE (t)-[:FAILED]->(f)",
                              id=test_id, fid=f"{test_id}-fail", reason=str(meta["failed_checks"]))
                return
            except Exception as e:
                print(f"[graph] write failed: {e}")
        self._mem.append(entry)

    def query(self, cypher: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        if self.enabled and self.driver and cypher:
            try:
                with self.driver.session() as s:
                    res = s.run(cypher).data()
                    return res[:limit]
            except Exception as e:
                return [{"error": str(e)}]
        return self._mem[-limit:]

graph_store = GraphStore(
    uri=__import__("app.config", fromlist=["settings"]).settings.neo4j_uri,
    user=__import__("app.config", fromlist=["settings"]).settings.neo4j_user,
    password=__import__("app.config", fromlist=["settings"]).settings.neo4j_password,
)
