"""
Search MCP Server
-----------------
Runs FastMCP directly on port 8001.
Health check is exposed as an MCP tool (simpler than a separate HTTP server).

Tools:
  • web_search    – Tavily → scraper fallback
  • cached_search – Redis cache → web_search
"""

import logging
import time

import structlog
from fastmcp import FastMCP

from cache import cache
from config import settings
from searcher import ScrapeFallbackSearcher, TavilySearcher

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

# ── Backends ──────────────────────────────────────────────────────────────────

tavily = TavilySearcher()
scraper = ScrapeFallbackSearcher()
_start_time = time.time()

# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="search-mcp",
    instructions="Web search. Use cached_search to prefer cache, web_search for fresh results.",
)


@mcp.tool
async def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web. Returns list of results with title, url, snippet, score, source."""
    max_results = max(1, min(max_results, 10))
    log.info("web_search", query=query)

    results: list[dict] = []
    backend = "none"

    if tavily.is_available():
        try:
            results = await tavily.search(query, max_results)
            backend = "tavily"
        except Exception as exc:
            log.warning("tavily_failed", error=str(exc))

    if not results and settings.enable_scrape_fallback:
        try:
            results = await scraper.search(query, max_results)
            backend = "scrape_fallback"
        except Exception as exc:
            log.error("scraper_failed", error=str(exc))
            return {"results": [], "backend": "none", "cached": False, "error": str(exc)}

    return {"results": results, "backend": backend, "cached": False}


@mcp.tool
async def cached_search(query: str, max_results: int = 5) -> dict:
    """Search with Redis cache. Returns cached results if available."""
    max_results = max(1, min(max_results, 10))

    hit = await cache.get(query, max_results)
    if hit is not None:
        return {"results": hit, "backend": "cache", "cached": True}

    result = await web_search(query, max_results)
    if result.get("results"):
        await cache.set(query, max_results, result["results"])
    return result


@mcp.tool
async def health() -> dict:
    """Health check — returns server status."""
    return {
        "status": "ok",
        "uptime_secs": round(time.time() - _start_time, 1),
        "tavily_configured": tavily.is_available(),
        "scrape_fallback_enabled": settings.enable_scrape_fallback,
    }


if __name__ == "__main__":
    import asyncio

    async def startup():
        await cache.connect()
        log.info("search-mcp starting", port=settings.mcp_server_port)

    asyncio.run(startup())
    mcp.run(transport="http", host="0.0.0.0", port=settings.mcp_server_port)