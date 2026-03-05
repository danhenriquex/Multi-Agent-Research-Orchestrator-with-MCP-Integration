FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies from pyproject.toml (cached layer)
COPY pyproject.toml .
RUN uv pip install --system --no-cache \
    fastmcp httpx fastapi "uvicorn[standard]" pydantic pydantic-settings structlog redis tenacity

# Copy this service's source + shared modules it depends on
COPY src/mcp_servers/search/     ./src/mcp_servers/search/
COPY src/shared/                 ./src/shared/
COPY src/config/                 ./src/config/

WORKDIR /app/src/mcp_servers/search

EXPOSE 8001
CMD ["python", "server.py"]