from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    tavily_api_key: str = ""
    redis_url: str = "redis://localhost:6379"
    mcp_server_port: int = 8001
    log_level: str = "INFO"

    # Rate limiting
    rate_limit_requests: int = 10
    rate_limit_window_secs: int = 60

    # Cache TTL
    cache_ttl_secs: int = 3600

    # Fallback: simple scraping when Tavily key missing
    enable_scrape_fallback: bool = True

    # ── Embedding model versioning ────────────────────────────────────────────
    # Changing this value invalidates all existing cache entries automatically.
    # Old keys become unreachable (different version hash in key prefix).
    embedding_model: str = "text-embedding-3-small"

    # ── Cache namespace isolation ─────────────────────────────────────────────
    # In multi-tenant deployments set this per tenant/app to prevent
    # cross-tenant cache leakage. Default "default" = single-tenant mode.
    cache_namespace: str = "default"

    # ── Semantic cache similarity threshold ───────────────────────────────────
    # Queries with cosine similarity >= this threshold are treated as cache hits.
    # Higher = safer (fewer false positives), lower = more cache hits.
    # Recommended range: 0.90-0.97 for factual research queries.
    # Too low (e.g. 0.85) risks serving wrong answers for similar-but-different
    # queries like "reset password" vs "reset router".
    cache_similarity_threshold: float = 0.94

    # ── ChromaDB confidence threshold ─────────────────────────────────────────
    # Minimum similarity for a KB match to be considered meaningful.
    # If best match is below this AND KB has entries → likely embedding drift.
    chroma_similarity_threshold: float = 0.30

    # ── Cost tracking ─────────────────────────────────────────────────────────
    # Approximate cost per Tavily API call in USD (used for savings estimate).
    tavily_cost_per_call_usd: float = 0.001


settings = Settings()
