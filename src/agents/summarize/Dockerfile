FROM python:3.11-slim
WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] httpx fastmcp openai pydantic pydantic-settings \
    structlog tenacity opentelemetry-sdk opentelemetry-exporter-otlp \
    openinference-instrumentation-openai

COPY src/a2a             /app/a2a
COPY src/shared          /app/shared
COPY src/agents/summarize /app

ENV PYTHONPATH=/app
CMD ["python", "app.py"]
