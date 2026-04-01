FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache \
    openai fastmcp fastapi "uvicorn[standard]" httpx \
    pydantic pydantic-settings structlog tenacity \
    psycopg2-binary \
    opentelemetry-sdk opentelemetry-exporter-otlp \
    openinference-instrumentation-openai \
    langsmith

COPY src/orchestrator/  ./src/orchestrator/
COPY src/a2a/           ./src/a2a/
COPY src/shared/        ./src/shared/
COPY src/config/        ./src/config/

# src/ on PYTHONPATH so "from orchestrator.agent import ..." resolves
ENV PYTHONPATH=/app/src

EXPOSE 8000
CMD ["python", "src/orchestrator/app.py"]
