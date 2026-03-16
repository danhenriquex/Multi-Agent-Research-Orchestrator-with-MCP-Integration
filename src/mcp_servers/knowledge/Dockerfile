FROM python:3.11-slim
WORKDIR /app

RUN pip install --no-cache-dir \
    fastmcp chromadb openai sentence-transformers \
    structlog tenacity

COPY src/mcp_servers/knowledge /app

ENV PYTHONPATH=/app
CMD ["python", "server.py"]
