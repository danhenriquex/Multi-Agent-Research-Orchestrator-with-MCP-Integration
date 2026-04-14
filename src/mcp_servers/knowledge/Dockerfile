FROM python:3.11-slim
WORKDIR /app

RUN pip install --no-cache-dir \
    fastmcp "chromadb>=0.5.0" openai \
    structlog tenacity

COPY src/mcp_servers/knowledge /app

ENV PYTHONPATH=/app
CMD ["python", "server.py"]
