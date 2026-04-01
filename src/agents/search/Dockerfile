FROM python:3.11-slim
WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[agents]" 2>/dev/null || pip install --no-cache-dir \
    fastapi uvicorn[standard] httpx fastmcp openai pydantic pydantic-settings \
    structlog tenacity opentelemetry-sdk opentelemetry-exporter-otlp \
    openinference-instrumentation-openai

COPY src/a2a            /app/a2a
COPY src/shared         /app/shared
COPY src/agents/search  /app

ENV PYTHONPATH=/app
CMD ["python", "app.py"]
