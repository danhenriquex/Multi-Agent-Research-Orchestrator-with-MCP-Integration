FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache \
    fastmcp openai fastapi "uvicorn[standard]" pydantic pydantic-settings structlog tenacity tiktoken

COPY src/mcp_servers/summarization/  ./src/mcp_servers/summarization/
COPY src/shared/                      ./src/shared/
COPY src/config/                      ./src/config/

WORKDIR /app/src/mcp_servers/summarization

EXPOSE 8002
CMD ["python", "server.py"]