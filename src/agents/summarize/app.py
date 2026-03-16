"""
Summarize Agent Service
------------------------
Exposes:
  POST /a2a       ← receives A2A messages from Supervisor or peer agents
  GET  /health

A2A tasks handled:
  "summarize"  → synthesises a list of search results into a coherent answer

MCP usage (vertical):
  summarization-mcp:8002  ← OpenAI-backed summarization with token budget
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastmcp import Client

from a2a import A2AMessage, a2a_router
from a2a.router import register_handler
from shared.tracing import configure_tracing as setup_tracing

# ── Config ────────────────────────────────────────────────────────────────────

SUMMARIZATION_MCP_URL = os.getenv("SUMMARIZATION_MCP_URL", "http://summarization-mcp:8002")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8011"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:4317")

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logging.basicConfig(level=LOG_LEVEL)
log = structlog.get_logger()

tracer = setup_tracing("summarize-agent", PHOENIX_ENDPOINT)
_start_time = time.time()


# ── A2A task handler ──────────────────────────────────────────────────────────


async def handle_summarize(msg: A2AMessage) -> dict:
    query = msg.payload.get("query", "")
    results = msg.payload.get("results", [])

    if not results:
        return {"summary": "No results to summarise.", "sources": [], "input_tokens": 0}

    mcp_url = SUMMARIZATION_MCP_URL.rstrip("/") + "/mcp"

    with tracer.start_as_current_span("summarize_agent.summarize") as span:
        # ── Input attributes ──────────────────────────────────────────────────
        span.set_attribute("input.query", query)
        span.set_attribute("input.num_results", len(results))
        span.set_attribute("input.caller", msg.sender)
        # Show source URLs being summarised
        urls = [r.get("url", "") for r in results[:5]]
        span.set_attribute("input.source_urls", ", ".join(urls))

        log.info("summarize_agent.summarizing", query=query, num_results=len(results))

        async with Client(mcp_url) as client:
            raw = await client.call_tool(
                name="summarize_search_results",
                arguments={"results": results, "query": query},
            )

        if hasattr(raw, "data") and raw.data:
            result = raw.data
        elif hasattr(raw, "content") and raw.content:
            text = raw.content[0].text if hasattr(raw.content[0], "text") else str(raw.content[0])
            result = json.loads(text)
        else:
            result = {
                "summary": "Summarisation failed.",
                "sources": [],
                "input_tokens": 0,
            }

        summary = result.get("summary", "")
        input_tokens = result.get("input_tokens", 0)
        sources = result.get("sources", [])

        # ── Output attributes ─────────────────────────────────────────────────
        span.set_attribute("output.input_tokens", input_tokens)
        span.set_attribute("output.summary_len", len(summary))
        span.set_attribute("output.num_sources", len(sources))
        # First 500 chars of the summary so you can read it in Phoenix
        span.set_attribute("output.summary_preview", summary[:500])

        log.info(
            "summarize_agent.done",
            query=query,
            tokens=input_tokens,
            summary_len=len(summary),
        )
        return result


# ── App lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    register_handler("summarize", handle_summarize)
    log.info("summarize_agent_ready", port=AGENT_PORT, mcp=SUMMARIZATION_MCP_URL)
    yield
    log.info("summarize_agent_shutdown")


app = FastAPI(title="summarize-agent", lifespan=lifespan)
app.include_router(a2a_router)


@app.get("/health")
async def health():
    return {
        "agent": "summarize",
        "status": "ok",
        "uptime_secs": round(time.time() - _start_time, 1),
        "summarization_mcp": SUMMARIZATION_MCP_URL,
    }


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=AGENT_PORT, reload=False)
