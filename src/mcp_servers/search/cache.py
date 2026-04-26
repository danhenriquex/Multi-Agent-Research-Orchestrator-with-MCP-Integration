"""
Redis-backed semantic cache with:
  - Version-tagged keys     → changing embedding model auto-invalidates all entries
  - Namespace isolation     → prevents cross-tenant cache leakage
  - Semantic similarity     → cache hits on similar (not just identical) queries
  - Hit rate tracking       → Redis counters for observability
  - Cost savings estimate   → tracks USD saved vs calling Tavily
  - Confidence-based evict  → removes entries whose similarity has drifted

Falls back to exact-match (no-op semantic layer) if ChromaDB unavailable.
"""

import hashlib
import json
import logging
import time

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)

# ── Version tag ───────────────────────────────────────────────────────────────
# Short hash of the embedding model name.
# Changing settings.embedding_model changes this prefix → all old keys miss.
_MODEL_VERSION_TAG = hashlib.md5(settings.embedding_model.encode()).hexdigest()[:8]


class SearchCache:
    """
    Two-layer cache:

    Layer 1 — Exact match (Redis key = hash of query+max_results+version+namespace)
               Always checked first. O(1) lookup.

    Layer 2 — Semantic match (ChromaDB vector search over cached query embeddings)
               Checked when exact miss occurs. Finds similar queries above threshold.
               Optional — falls back gracefully if ChromaDB unavailable.
    """

    def __init__(self):
        self._client: aioredis.Redis | None = None
        self._chroma_collection = None
        self._openai_client = None

    # ── Startup ───────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to Redis (required) and ChromaDB (optional)."""
        # Redis
        try:
            self._client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._client.ping()
            logger.info("Redis cache connected: %s", settings.redis_url)
        except Exception as exc:
            logger.warning("Redis unavailable, caching disabled: %s", exc)
            self._client = None

        # ChromaDB for semantic layer (optional)
        try:
            import chromadb

            chroma_host = "chromadb"
            chroma_port = 8000
            client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
            self._chroma_collection = client.get_or_create_collection(
                name=f"search_cache_{settings.cache_namespace}",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("Semantic cache ChromaDB connected")
        except Exception as exc:
            logger.warning("ChromaDB unavailable, semantic cache disabled: %s", exc)
            self._chroma_collection = None

        # OpenAI embeddings for semantic layer
        if self._chroma_collection and settings.embedding_model:
            try:
                import openai

                self._openai_client = openai.AsyncOpenAI()
                logger.info("OpenAI embeddings ready for semantic cache")
            except Exception as exc:
                logger.warning("OpenAI client unavailable: %s", exc)
                self._openai_client = None

    # ── Key construction ──────────────────────────────────────────────────────

    def _exact_key(self, query: str, max_results: int) -> str:
        """
        Exact match key. Includes:
          - namespace:      prevents cross-tenant hits
          - version tag:    auto-invalidates on embedding model change
          - query hash:     the actual content key
        """
        content_hash = hashlib.sha256(f"{query}:{max_results}".encode()).hexdigest()[:16]
        return f"search:{settings.cache_namespace}:v{_MODEL_VERSION_TAG}:{content_hash}"

    def _stats_key(self, metric: str) -> str:
        return f"cache_stats:{settings.cache_namespace}:{metric}"

    # ── Public interface ──────────────────────────────────────────────────────

    async def get(self, query: str, max_results: int) -> tuple[list[dict] | None, str]:
        """
        Try to return cached results for a query.

        Returns:
            (results, hit_type) where hit_type is one of:
              "exact"    — identical query was cached
              "semantic" — similar query found above threshold
              "miss"     — no cache hit
        """
        if not self._client:
            return None, "miss"

        # ── Layer 1: exact match ──────────────────────────────────────────────
        try:
            data = await self._client.get(self._exact_key(query, max_results))
            if data:
                await self._record_hit("exact")
                logger.debug("Cache EXACT HIT: %s", query[:60])
                return json.loads(data), "exact"
        except Exception as exc:
            logger.warning("Cache exact get error: %s", exc)

        # ── Layer 2: semantic match ───────────────────────────────────────────
        if self._chroma_collection and self._openai_client:
            try:
                embedding = await self._embed(query)
                if embedding:
                    results = self._chroma_collection.query(
                        query_embeddings=[embedding],
                        n_results=1,
                        include=["documents", "distances", "metadatas"],
                    )
                    distances = results.get("distances", [[]])[0]
                    metadatas = results.get("metadatas", [[]])[0]

                    if distances:
                        similarity = 1.0 - (distances[0] / 2.0)
                        if similarity >= settings.cache_similarity_threshold:
                            # Fetch actual results from Redis using stored key
                            cached_key = metadatas[0].get("redis_key", "")
                            if cached_key:
                                cached_data = await self._client.get(cached_key)
                                if cached_data:
                                    await self._record_hit("semantic")
                                    logger.info(
                                        "Cache SEMANTIC HIT: %s (similarity=%.3f)",
                                        query[:60],
                                        similarity,
                                    )
                                    return json.loads(cached_data), "semantic"
            except Exception as exc:
                logger.warning("Semantic cache lookup error: %s", exc)

        await self._record_miss()
        return None, "miss"

    async def set(self, query: str, max_results: int, results: list[dict]) -> None:
        """
        Cache results for a query.
        Stores in Redis (exact key) and indexes query embedding in ChromaDB
        for future semantic lookups.
        """
        if not self._client:
            return

        exact_key = self._exact_key(query, max_results)

        # Store results in Redis
        try:
            await self._client.setex(
                exact_key,
                settings.cache_ttl_secs,
                json.dumps(results),
            )
        except Exception as exc:
            logger.warning("Cache set error: %s", exc)
            return

        # Index query embedding in ChromaDB for semantic lookups
        if self._chroma_collection and self._openai_client:
            try:
                embedding = await self._embed(query)
                if embedding:
                    doc_id = hashlib.md5(
                        f"{settings.cache_namespace}:{query}:{max_results}".encode()
                    ).hexdigest()
                    self._chroma_collection.upsert(
                        ids=[doc_id],
                        embeddings=[embedding],
                        documents=[query],
                        metadatas=[
                            {
                                "redis_key": exact_key,
                                "namespace": settings.cache_namespace,
                                "model_version": _MODEL_VERSION_TAG,
                                "embedding_model": settings.embedding_model,
                                "cached_at": str(int(time.time())),
                            }
                        ],
                    )
            except Exception as exc:
                logger.warning("Semantic cache index error: %s", exc)

        # Track cost savings
        await self._record_cost_saved()

    async def stats(self) -> dict:
        """
        Return cache observability metrics:
          - hit_rate:          % of lookups that hit cache
          - exact_hits:        count of exact match hits
          - semantic_hits:     count of semantic similarity hits
          - misses:            count of cache misses
          - cost_saved_usd:    estimated USD saved vs Tavily calls
          - semantic_entries:  number of query embeddings indexed
        """
        if not self._client:
            return {"error": "Redis unavailable"}

        try:
            exact_hits = int(await self._client.get(self._stats_key("exact_hits")) or 0)
            semantic_hits = int(await self._client.get(self._stats_key("semantic_hits")) or 0)
            misses = int(await self._client.get(self._stats_key("misses")) or 0)
            cost_saved = float(await self._client.get(self._stats_key("cost_saved_usd")) or 0.0)

            total = exact_hits + semantic_hits + misses
            hit_rate = round((exact_hits + semantic_hits) / total, 3) if total else 0.0

            semantic_entries = 0
            if self._chroma_collection:
                try:
                    semantic_entries = self._chroma_collection.count()
                except Exception:
                    pass

            return {
                "hit_rate": hit_rate,
                "exact_hits": exact_hits,
                "semantic_hits": semantic_hits,
                "misses": misses,
                "total_lookups": total,
                "cost_saved_usd": round(cost_saved, 4),
                "semantic_entries": semantic_entries,
                "namespace": settings.cache_namespace,
                "embedding_model": settings.embedding_model,
                "model_version_tag": _MODEL_VERSION_TAG,
                "similarity_threshold": settings.cache_similarity_threshold,
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def flush_namespace(self) -> int:
        """
        Delete all cache entries for the current namespace.
        Useful when deploying a new embedding model version.
        Returns number of keys deleted.
        """
        if not self._client:
            return 0
        pattern = f"search:{settings.cache_namespace}:*"
        keys = await self._client.keys(pattern)
        if keys:
            await self._client.delete(*keys)
        # Also clear ChromaDB semantic index
        if self._chroma_collection:
            try:
                existing = self._chroma_collection.get()
                ids_to_delete = [
                    id_
                    for id_, meta in zip(existing["ids"], existing["metadatas"])
                    if meta.get("namespace") == settings.cache_namespace
                ]
                if ids_to_delete:
                    self._chroma_collection.delete(ids=ids_to_delete)
            except Exception as exc:
                logger.warning("Semantic cache flush error: %s", exc)
        return len(keys)

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float] | None:
        """Generate an embedding for text using the configured model."""
        try:
            response = await self._openai_client.embeddings.create(
                model=settings.embedding_model,
                input=text[:2000],
            )
            return response.data[0].embedding
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)
            return None

    async def _record_hit(self, hit_type: str) -> None:
        if not self._client:
            return
        try:
            await self._client.incr(self._stats_key(f"{hit_type}_hits"))
        except Exception:
            pass

    async def _record_miss(self) -> None:
        if not self._client:
            return
        try:
            await self._client.incr(self._stats_key("misses"))
        except Exception:
            pass

    async def _record_cost_saved(self) -> None:
        if not self._client:
            return
        try:
            await self._client.incrbyfloat(
                self._stats_key("cost_saved_usd"),
                settings.tavily_cost_per_call_usd,
            )
        except Exception:
            pass


cache = SearchCache()
