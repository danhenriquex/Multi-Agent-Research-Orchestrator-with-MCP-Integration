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


settings = Settings()