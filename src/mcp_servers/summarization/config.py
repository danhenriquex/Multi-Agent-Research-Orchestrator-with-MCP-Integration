from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    mcp_server_port: int = 8002
    log_level: str = "INFO"

    max_tokens_per_request: int = 2000
    max_input_tokens: int = 12000
    model: str = "gpt-4o-mini"


settings = Settings()