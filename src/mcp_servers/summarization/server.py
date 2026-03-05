"""
Summarization MCP Server
-------------------------
Runs FastMCP directly on port 8002.

Tools:
  • summarize_text           – single document summary
  • summarize_search_results – synthesize multiple search snippets
"""

import logging
import time

import structlog
from fastmcp import FastMCP
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from token_budget import count_tokens, truncate_to_budget

# ── Logging ───────────────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logging.basicConfig(level=settings.log_level)
log = structlog.get_logger()

_start_time = time.time()

# ── OpenAI client ─────────────────────────────────────────────────────────────

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI | None:
    global _client
    if _client is None and settings.openai_api_key:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="summarization-mcp",
    instructions="Summarization tools. Use summarize_search_results to synthesize search results.",
)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def _call_openai(system: str, user: str) -> str:
    client = get_client()
    if client is None:
        return "[DEGRADED] OPENAI_API_KEY not configured."
    msg = await client.chat.completions.create(
        model=settings.model,
        max_tokens=settings.max_tokens_per_request,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return msg.choices[0].message.content


@mcp.tool
async def summarize_text(text: str, focus: str = "", max_length: str = "medium") -> dict:
    """Summarize a block of text. max_length: short | medium | long."""
    length_map = {"short": "2-3 sentences", "medium": "one paragraph", "long": "3-4 paragraphs"}
    length = length_map.get(max_length, "one paragraph")
    text_trimmed, truncated = truncate_to_budget(text, settings.max_input_tokens)
    tokens = count_tokens(text_trimmed)
    focus_clause = f" Focus on: {focus}." if focus else ""
    system = f"Summarize in {length}.{focus_clause} Be factual and concise."
    try:
        summary = await _call_openai(system, text_trimmed)
    except Exception as exc:
        return {"summary": f"[ERROR] {exc}", "input_tokens": tokens, "truncated": truncated}
    return {"summary": summary, "input_tokens": tokens, "truncated": truncated}


@mcp.tool
async def summarize_search_results(results: list[dict], query: str, max_length: str = "medium") -> dict:
    """Synthesize multiple search results into a coherent summary."""
    if not results:
        return {"summary": "No search results to summarize.", "sources": [], "input_tokens": 0}

    formatted = f"Query: {query}\n\n"
    sources = []
    for i, r in enumerate(results, 1):
        formatted += f"[{i}] {r.get('title','')}\nURL: {r.get('url','')}\n{r.get('snippet','')}\n\n"
        if r.get("url"):
            sources.append(r["url"])

    text_trimmed, truncated = truncate_to_budget(formatted, settings.max_input_tokens)
    tokens = count_tokens(text_trimmed)
    length_map = {"short": "2-3 sentences", "medium": "one paragraph", "long": "3-4 paragraphs"}
    length = length_map.get(max_length, "one paragraph")
    system = f"Synthesize search results into {length}. Cite sources by number. Be factual."

    try:
        summary = await _call_openai(system, text_trimmed)
    except Exception as exc:
        return {"summary": f"[ERROR] {exc}", "sources": sources, "input_tokens": tokens}
    return {"summary": summary, "sources": sources[:10], "input_tokens": tokens, "truncated": truncated}


@mcp.tool
async def health() -> dict:
    """Health check."""
    return {
        "status": "ok",
        "uptime_secs": round(time.time() - _start_time, 1),
        "openai_configured": bool(settings.openai_api_key),
        "model": settings.model,
    }


if __name__ == "__main__":
    log.info("summarization-mcp starting", port=settings.mcp_server_port)
    mcp.run(transport="http", host="0.0.0.0", port=settings.mcp_server_port)