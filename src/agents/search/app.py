"""
Search Agent Service
---------------------
Exposes:
  POST /a2a        ← receives A2A messages from Supervisor
  GET  /health

A2A tasks handled:
  "search"  → calls Search MCP server, returns ranked results

MCP usage (vertical):
  search-mcp:8001  ← Tavily / Redis-cached web search
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from a2a import A2AMessage, a2a_router
from a2a.router import register_handler
from shared.tracing import configure_tracing as setup_tracing

# ── Config ────────────────────────────────────────────────────────────────────

SEARCH_MCP_URL = os.getenv("SEARCH_MCP_URL", "http://search-mcp:8001")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8010"))
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

tracer = setup_tracing("search-agent", PHOENIX_ENDPOINT)
_start_time = time.time()


# ── A2A task handler ──────────────────────────────────────────────────────────


async def handle_search(msg: A2AMessage) -> dict:
    from fastmcp import Client

    query = msg.payload.get("query", "")
    max_results = msg.payload.get("max_results", 5)
    context = msg.context

    if not query:
        return {"results": [], "error": "Empty query"}

    mcp_url = SEARCH_MCP_URL.rstrip("/") + "/mcp"

    with tracer.start_as_current_span("search_agent.search") as span:
        # ── Input attributes ──────────────────────────────────────────────────
        span.set_attribute("input.query", query)
        span.set_attribute("input.max_results", max_results)
        span.set_attribute("input.caller", msg.sender)
        span.set_attribute("session_id", context.get("session_id", ""))

        log.info("search_agent.searching", query=query, caller=msg.sender)

        async with Client(mcp_url) as client:
            raw = await client.call_tool(
                name="cached_search",
                arguments={"query": query, "max_results": max_results},
            )

        if hasattr(raw, "data") and raw.data:
            result = raw.data
        elif hasattr(raw, "content") and raw.content:
            text = raw.content[0].text if hasattr(raw.content[0], "text") else str(raw.content[0])
            result = json.loads(text)
        else:
            result = {"results": [], "error": "Empty MCP response"}

        results = result.get("results", [])
        backend = result.get("backend", "unknown")
        cached = result.get("cached", False)

        # ── Output attributes ─────────────────────────────────────────────────
        span.set_attribute("output.num_results", len(results))
        span.set_attribute("output.backend", backend)
        span.set_attribute("output.cached", cached)
        # Top 3 result titles so Phoenix shows what was found
        for i, r in enumerate(results[:3]):
            span.set_attribute(f"output.result_{i + 1}.title", r.get("title", ""))
            span.set_attribute(f"output.result_{i + 1}.url", r.get("url", ""))
            span.set_attribute(f"output.result_{i + 1}.score", r.get("score", 0.0))

        log.info(
            "search_agent.done",
            query=query,
            num_results=len(results),
            backend=backend,
            cached=cached,
        )
        return result


# ── App lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    register_handler("search", handle_search)
    log.info("search_agent_ready", port=AGENT_PORT, mcp=SEARCH_MCP_URL)
    yield
    log.info("search_agent_shutdown")


app = FastAPI(title="search-agent", lifespan=lifespan)
app.include_router(a2a_router)


@app.get("/health")
async def health():
    return {
        "agent": "search",
        "status": "ok",
        "uptime_secs": round(time.time() - _start_time, 1),
        "search_mcp": SEARCH_MCP_URL,
    }


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=AGENT_PORT, reload=False)
