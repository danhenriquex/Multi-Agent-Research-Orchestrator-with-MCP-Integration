"""Redis-backed cache with TTL. Falls back to no-op if Redis is unavailable."""

import hashlib
import json
import logging

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)


class SearchCache:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        try:
            self._client = aioredis.from_url(
                settings.redis_url, decode_responses=True
            )
            await self._client.ping()
            logger.info("Redis cache connected", extra={"url": settings.redis_url})
        except Exception as exc:
            logger.warning("Redis unavailable, caching disabled: %s", exc)
            self._client = None

    def _key(self, query: str, max_results: int) -> str:
        raw = f"{query}:{max_results}"
        return "search:" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def get(self, query: str, max_results: int) -> list[dict] | None:
        if not self._client:
            return None
        try:
            data = await self._client.get(self._key(query, max_results))
            if data:
                logger.debug("Cache HIT", extra={"query": query})
                return json.loads(data)
        except Exception as exc:
            logger.warning("Cache get error: %s", exc)
        return None

    async def set(self, query: str, max_results: int, results: list[dict]) -> None:
        if not self._client:
            return
        try:
            await self._client.setex(
                self._key(query, max_results),
                settings.cache_ttl_secs,
                json.dumps(results),
            )
        except Exception as exc:
            logger.warning("Cache set error: %s", exc)


cache = SearchCache()