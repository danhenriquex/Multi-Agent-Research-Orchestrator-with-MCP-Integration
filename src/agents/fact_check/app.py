"""
Fact-Check Agent Service
-------------------------
The NEW agent introduced with A2A architecture.

Exposes:
  POST /a2a       ← receives A2A messages from Supervisor or Summarize Agent
  GET  /health

A2A tasks handled:
  "fact_check"   → verifies claims in a summary against knowledge base
  "index"        → ingests documents into the knowledge base (for enrichment)

MCP usage (vertical):
  knowledge-mcp:8003  ← ChromaDB vector search
"""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC

import structlog
import uvicorn
from fastapi import FastAPI
from fastmcp import Client

from a2a import A2AMessage, a2a_router
from a2a.router import register_handler
from shared.tracing import configure_tracing as setup_tracing

# ── Config ────────────────────────────────────────────────────────────────────

KNOWLEDGE_MCP_URL = os.getenv("KNOWLEDGE_MCP_URL", "http://knowledge-mcp:8003")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8012"))
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

tracer = setup_tracing("fact-check-agent", PHOENIX_ENDPOINT)
_start_time = time.time()

CONFIDENCE_THRESHOLD = 0.75


# ── A2A task handlers ─────────────────────────────────────────────────────────


async def handle_fact_check(msg: A2AMessage) -> dict:
    summary = msg.payload.get("summary", "")
    query = msg.payload.get("query", "")
    sources = msg.payload.get("sources", [])

    if not summary:
        return {
            "verified": False,
            "confidence": 0.0,
            "flags": ["Empty summary"],
            "checked_at": _now(),
        }

    mcp_url = KNOWLEDGE_MCP_URL.rstrip("/") + "/mcp"

    with tracer.start_as_current_span("fact_check_agent.verify") as span:
        # ── Input attributes ──────────────────────────────────────────────────
        span.set_attribute("input.query", query)
        span.set_attribute("input.summary_len", len(summary))
        span.set_attribute("input.num_sources", len(sources))
        span.set_attribute("input.caller", msg.sender)
        span.set_attribute("input.summary_preview", summary[:300])

        log.info("fact_check_agent.verifying", query=query, caller=msg.sender)

        try:
            async with Client(mcp_url) as client:
                raw = await client.call_tool(
                    name="verify_claims",
                    arguments={"text": summary, "query": query, "n_results": 5},
                )

            if hasattr(raw, "data") and raw.data:
                kb_result = raw.data
            elif hasattr(raw, "content") and raw.content:
                text = (
                    raw.content[0].text if hasattr(raw.content[0], "text") else str(raw.content[0])
                )
                kb_result = json.loads(text)
            else:
                kb_result = {"matches": [], "max_similarity": 0.0}

        except Exception as exc:
            log.warning("fact_check_agent.mcp_unavailable", error=str(exc))
            span.set_attribute("output.degraded", True)
            span.set_attribute("output.error", str(exc))
            return {
                "verified": None,
                "confidence": None,
                "flags": [f"Knowledge base unavailable: {exc}"],
                "checked_at": _now(),
                "degraded": True,
            }

        max_sim = kb_result.get("max_similarity", 0.0)
        matches = kb_result.get("matches", [])
        flags = kb_result.get("contradictions", [])
        verified = max_sim >= CONFIDENCE_THRESHOLD and not flags

        # ── Output attributes ─────────────────────────────────────────────────
        span.set_attribute("output.confidence", round(max_sim, 3))
        span.set_attribute("output.verified", verified)
        span.set_attribute("output.num_matches", len(matches))
        span.set_attribute("output.num_flags", len(flags))
        if flags:
            span.set_attribute("output.flags", ", ".join(flags[:3]))
        if matches:
            span.set_attribute("output.top_match_preview", matches[0].get("document", "")[:200])

        log.info(
            "fact_check_agent.done",
            query=query,
            verified=verified,
            confidence=round(max_sim, 3),
            flags=flags,
        )

        return {
            "verified": verified,
            "confidence": round(max_sim, 3),
            "flags": flags,
            "matches": [m.get("document", "")[:200] for m in matches[:3]],
            "checked_at": _now(),
        }


async def handle_index(msg: A2AMessage) -> dict:
    documents = msg.payload.get("documents", [])
    if not documents:
        return {"indexed": 0, "error": "No documents provided"}

    mcp_url = KNOWLEDGE_MCP_URL.rstrip("/") + "/mcp"

    try:
        async with Client(mcp_url) as client:
            raw = await client.call_tool(
                name="index_documents",
                arguments={"documents": documents},
            )

        if hasattr(raw, "data") and raw.data:
            return raw.data
        return {"indexed": len(documents)}

    except Exception as exc:
        log.error("fact_check_agent.index_failed", error=str(exc))
        return {"indexed": 0, "error": str(exc)}


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat()


# ── App lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_app: FastAPI):
    register_handler("fact_check", handle_fact_check)
    register_handler("index", handle_index)
    log.info("fact_check_agent_ready", port=AGENT_PORT, mcp=KNOWLEDGE_MCP_URL)
    yield
    log.info("fact_check_agent_shutdown")


app = FastAPI(title="fact-check-agent", lifespan=lifespan)
app.include_router(a2a_router)


@app.get("/health")
async def health():
    return {
        "agent": "fact_check",
        "status": "ok",
        "uptime_secs": round(time.time() - _start_time, 1),
        "knowledge_mcp": KNOWLEDGE_MCP_URL,
    }


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=AGENT_PORT, reload=False)
