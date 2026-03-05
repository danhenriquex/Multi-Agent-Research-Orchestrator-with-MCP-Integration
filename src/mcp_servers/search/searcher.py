"""
Search backends:
  1. Tavily  – preferred, high-quality AI search
  2. Scraper – fallback, fetches DuckDuckGo HTML (no API key needed)
"""

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

logger = logging.getLogger(__name__)


class TavilySearcher:
    BASE_URL = "https://api.tavily.com/search"

    def __init__(self):
        self._api_key = settings.tavily_api_key

    def is_available(self) -> bool:
        return bool(self._api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.BASE_URL,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "score": r.get("score", 0.0),
                "source": "tavily",
            }
            for r in data.get("results", [])
        ]


class ScrapeFallbackSearcher:
    """
    Uses DuckDuckGo lite (no JS, no API key) as a last resort.
    Returns fewer fields – callers should treat score as 0.
    """

    DDG_URL = "https://lite.duckduckgo.com/lite/"

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "research-agent/0.1"},
        ) as client:
            resp = await client.post(self.DDG_URL, data={"q": query})
            resp.raise_for_status()

        # Very light HTML parse – no external deps needed
        results = []
        lines = resp.text.splitlines()
        i = 0
        while i < len(lines) and len(results) < max_results:
            line = lines[i]
            if 'class="result-link"' in line or "uddg=" in line:
                import re

                url_match = re.search(r'href="([^"]+)"', line)
                title_match = re.search(r">([^<]+)<", line)
                url = url_match.group(1) if url_match else ""
                title = title_match.group(1).strip() if title_match else ""
                if url and title:
                    results.append(
                        {
                            "title": title,
                            "url": url,
                            "snippet": "",
                            "score": 0.0,
                            "source": "scrape_fallback",
                        }
                    )
            i += 1

        logger.warning(
            "Used scrape fallback for search",
            extra={"query": query, "results": len(results)},
        )
        return results
