from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    app_env: str = "dev"
    port: int = 8000
    secret_token: str = "change-me"
    target_url_default: str = "https://example.com"
    domain: str = "qa.awesometech.com.ng"
    public_url: str = "https://qa.awesometech.com.ng"
    cors_origins: str = "https://qa.awesometech.com.ng,http://localhost:3000"
    storage_dir: str = "/app/storage"
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "qa-agent-pass"
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"
    github_webhook_secret: str = "change-me-too"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

def _resolve_storage() -> Path:
    for cand in [Path(settings.storage_dir), Path(__file__).resolve().parents[1] / "storage"]:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            test = cand / ".write_test"
            test.write_text("ok")
            test.unlink()
            return cand
        except Exception:
            continue
    return Path(settings.storage_dir)

STORAGE = _resolve_storage()
VIDEOS = STORAGE / "videos"
REPORTS = STORAGE / "reports"
TRACES = STORAGE / "traces"
K6_RESULTS = STORAGE / "k6-results"

for p in [VIDEOS, REPORTS, TRACES, K6_RESULTS]:
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
