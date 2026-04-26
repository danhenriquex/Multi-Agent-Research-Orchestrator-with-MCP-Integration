"""
Search MCP Server
-----------------
Runs FastMCP directly on port 8001.

Tools:
  • web_search      – Tavily → scraper fallback
  • cached_search   – semantic cache → exact cache → web_search
  • cache_stats     – hit rate, cost savings, semantic entries
  • cache_flush     – flush namespace (call after embedding model update)
  • health          – server status
"""

import logging
import time

import structlog
from cache import cache
from fastmcp import FastMCP
from searcher import ScrapeFallbackSearcher, TavilySearcher

from config import settings

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
    instructions=(
        "Web search tools. Use cached_search to prefer cache, "
        "web_search for guaranteed fresh results. "
        "Use cache_stats to monitor hit rate and cost savings."
    ),
)


@mcp.tool
async def web_search(query: str, max_results: int = 5) -> dict:
    """
    Search the web fresh (bypasses cache).
    Returns list of results with title, url, snippet, score, source.
    """
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
            return {
                "results": [],
                "backend": "none",
                "cached": False,
                "error": str(exc),
            }

    return {"results": results, "backend": backend, "cached": False}


@mcp.tool
async def cached_search(query: str, max_results: int = 5) -> dict:
    """
    Search with two-layer semantic cache.

    Layer 1 — Exact match: identical query returns instantly.
    Layer 2 — Semantic match: similar query (cosine >= threshold) returns cached result.
    Layer 3 — Cache miss: calls Tavily/scraper and caches the result.

    Returns hit_type: 'exact' | 'semantic' | 'miss' for observability.
    """
    max_results = max(1, min(max_results, 10))

    cached_results, hit_type = await cache.get(query, max_results)
    if cached_results is not None:
        log.info(
            "cached_search_hit",
            query=query[:60],
            hit_type=hit_type,
        )
        return {
            "results": cached_results,
            "backend": "cache",
            "cached": True,
            "hit_type": hit_type,
        }

    # Cache miss — fetch fresh results
    result = await web_search(query, max_results)
    if result.get("results"):
        await cache.set(query, max_results, result["results"])

    return {**result, "hit_type": "miss"}


@mcp.tool
async def cache_stats() -> dict:
    """
    Return cache observability metrics.

    Includes:
      - hit_rate:           % of lookups served from cache
      - exact_hits:         count of exact query matches
      - semantic_hits:      count of similar query matches
      - misses:             count of cache misses (Tavily was called)
      - cost_saved_usd:     estimated USD saved vs calling Tavily every time
      - semantic_entries:   number of query embeddings indexed in ChromaDB
      - similarity_threshold: current semantic matching threshold
    """
    return await cache.stats()


@mcp.tool
async def cache_flush() -> dict:
    """
    Flush all cache entries for the current namespace.

    Call this after:
      - Updating the embedding model (EMBEDDING_MODEL env var)
      - Suspecting embedding drift has degraded cache quality
      - Changing CACHE_NAMESPACE

    Returns number of Redis keys deleted.
    """
    log.warning(
        "cache_flush_requested",
        namespace=settings.cache_namespace,
        embedding_model=settings.embedding_model,
    )
    deleted = await cache.flush_namespace()
    return {
        "deleted_keys": deleted,
        "namespace": settings.cache_namespace,
        "message": f"Flushed {deleted} keys. Cache will rebuild on next requests.",
    }


@mcp.tool
async def health() -> dict:
    """Health check — returns server status and cache config."""
    stats = await cache.stats()
    return {
        "status": "ok",
        "uptime_secs": round(time.time() - _start_time, 1),
        "tavily_configured": tavily.is_available(),
        "scrape_fallback_enabled": settings.enable_scrape_fallback,
        "cache_namespace": settings.cache_namespace,
        "embedding_model": settings.embedding_model,
        "similarity_threshold": settings.cache_similarity_threshold,
        "cache_hit_rate": stats.get("hit_rate", 0.0),
        "cost_saved_usd": stats.get("cost_saved_usd", 0.0),
    }


if __name__ == "__main__":
    import asyncio

    async def startup():
        await cache.connect()
        log.info(
            "search-mcp starting",
            port=settings.mcp_server_port,
            namespace=settings.cache_namespace,
            embedding_model=settings.embedding_model,
            similarity_threshold=settings.cache_similarity_threshold,
        )

    asyncio.run(startup())
    mcp.run(transport="http", host="0.0.0.0", port=settings.mcp_server_port)
