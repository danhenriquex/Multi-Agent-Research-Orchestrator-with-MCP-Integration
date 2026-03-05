"""
Orchestrator — FastAPI entry point
-----------------------------------
Exposes:
  POST /research         → full JSON response
  POST /research/stream  → Server-Sent Events (streaming)
  GET  /health           → service health + MCP server status
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager

import psycopg2
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from orchestrator.agent import ResearchAgent
from orchestrator.api import ResearchRequest, ResearchResponse

# ── Logging ───────────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = structlog.get_logger()

# ── Config from environment ───────────────────────────────────────────────────

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SEARCH_MCP_URL = os.getenv("SEARCH_MCP_URL", "http://localhost:8001")
SUMMARIZATION_MCP_URL = os.getenv("SUMMARIZATION_MCP_URL", "http://localhost:8002")
DATABASE_URL = os.getenv("DATABASE_URL", "")
MODEL = os.getenv("MODEL", "gpt-4o-mini")
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:4317")

# ── OpenTelemetry → Phoenix ───────────────────────────────────────────────────


def setup_tracing():
    resource = Resource.create({"service.name": "research-agent-orchestrator"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=PHOENIX_ENDPOINT, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer("orchestrator")


tracer = setup_tracing()

# ── Database helpers ──────────────────────────────────────────────────────────


def get_db():
    if not DATABASE_URL:
        return None
    try:
        return psycopg2.connect(DATABASE_URL)
    except Exception as exc:
        log.warning("db_connect_failed", error=str(exc))
        return None


def save_query(
    conn, query: str, status: str, result: dict | None, error: str | None, duration_ms: int
):
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_queries
                  (query, status, plan, result, error, tool_calls, duration_ms, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    query,
                    status,
                    json.dumps(result.get("plan")) if result else None,
                    result.get("answer") if result else None,
                    error,
                    json.dumps(result.get("tool_calls")) if result else None,
                    duration_ms,
                ),
            )
        conn.commit()
    except Exception as exc:
        log.warning("db_save_failed", error=str(exc))
    finally:
        conn.close()


# ── Agent singleton ───────────────────────────────────────────────────────────

_agent: ResearchAgent | None = None
_start_time = time.time()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _agent
    _agent = ResearchAgent(
        openai_api_key=OPENAI_API_KEY,
        search_mcp_url=SEARCH_MCP_URL,
        summarization_mcp_url=SUMMARIZATION_MCP_URL,
        model=MODEL,
    )
    log.info(
        "orchestrator_ready", search_mcp=SEARCH_MCP_URL, summarization_mcp=SUMMARIZATION_MCP_URL
    )
    yield
    if _agent:
        await _agent.close()
    log.info("orchestrator_shutdown")


app = FastAPI(title="research-agent-orchestrator", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    mcp_status = await _agent._gateway.health_check() if _agent else {}
    return {
        "status": "ok",
        "uptime_secs": round(time.time() - _start_time, 1),
        "mcp_servers": mcp_status,
        "model": MODEL,
    }


@app.post("/research", response_model=ResearchResponse)
async def research(req: ResearchRequest):
    """Run a full research cycle and return the complete result."""
    conn = get_db()
    result = None
    error = None
    duration_ms = 0

    with tracer.start_as_current_span("research") as span:
        span.set_attribute("query", req.query)
        try:
            async for chunk in _agent.run(req.query):
                if isinstance(chunk, dict):
                    result = chunk
                    duration_ms = chunk["duration_ms"]

            span.set_attribute("duration_ms", duration_ms)
            span.set_attribute("num_sources", len(result.get("sources", [])))
            save_query(conn, req.query, "complete", result, None, duration_ms)
            return ResearchResponse(
                query=result["query"],
                answer=result["answer"],
                sources=result["sources"],
                plan=result["plan"],
                tool_calls=result["tool_calls"],
                duration_ms=result["duration_ms"],
            )

        except Exception as exc:
            error = str(exc)
            span.set_attribute("error", error)
            log.error("research_failed", query=req.query, error=error)
            save_query(conn, req.query, "failed", None, error, duration_ms)
            return ResearchResponse(
                query=req.query,
                answer=f"[ERROR] Research failed: {error}",
                sources=[],
                plan=[],
                tool_calls=[],
                duration_ms=duration_ms,
            )


@app.post("/research/stream")
async def research_stream(req: ResearchRequest):
    """Stream research progress as Server-Sent Events."""

    async def event_generator():
        conn = get_db()
        result = None
        error = None

        try:
            async for chunk in _agent.run(req.query):
                if isinstance(chunk, str):
                    yield chunk  # SSE chunk already formatted as "data: ...\n\n"
                elif isinstance(chunk, dict):
                    result = chunk
                    # Send final result as JSON event
                    yield f"data: {json.dumps({'type': 'result', **chunk})}\n\n"

            save_query(
                conn, req.query, "complete", result, None, result["duration_ms"] if result else 0
            )

        except Exception as exc:
            error = str(exc)
            log.error("stream_failed", query=req.query, error=error)
            yield f"data: {json.dumps({'type': 'error', 'message': error})}\n\n"
            save_query(conn, req.query, "failed", None, error, 0)

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    port = int(os.getenv("MCP_SERVER_PORT", "8000"))
    uvicorn.run(
        "orchestrator.app:app",
        host="0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
