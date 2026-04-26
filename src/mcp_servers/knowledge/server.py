"""
Knowledge MCP Server
---------------------
FastMCP server on port 8003, backed by ChromaDB.
Used exclusively by the Fact-Check Agent.

Tools:
  verify_claims   – vector-search for text similar to the input, return
                    top-k matches + max cosine similarity + contradictions.
                    Detects embedding drift via confidence-based invalidation.
  index_documents – upsert documents into the ChromaDB collection
  collection_info – return collection size, metadata, and drift indicators
"""

import logging
import os
import time
import uuid

import chromadb
import structlog
from chromadb.utils import embedding_functions
from fastmcp import FastMCP

# ── Config ────────────────────────────────────────────────────────────────────

CHROMA_HOST = os.getenv("CHROMA_HOST", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
CHROMA_COLL = os.getenv("CHROMA_COLLECTION", "research_knowledge")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
MCP_PORT = int(os.getenv("MCP_SERVER_PORT", "8003"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Confidence-based invalidation thresholds
# DRIFT_THRESHOLD: if best match is below this AND KB has entries,
#   the KB may have embedding drift — flag it instead of returning 0.0
DRIFT_THRESHOLD = float(os.getenv("CHROMA_DRIFT_THRESHOLD", "0.30"))

# VERIFY_THRESHOLD: minimum similarity to consider a claim "verified"
VERIFY_THRESHOLD = float(os.getenv("CHROMA_VERIFY_THRESHOLD", "0.75"))

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
logging.basicConfig(level=LOG_LEVEL)
log = structlog.get_logger()

# ── ChromaDB client ───────────────────────────────────────────────────────────


def _get_collection():
    """Connect to ChromaDB and return (or create) the knowledge collection."""
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

    if OPENAI_KEY:
        ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_KEY,
            model_name=EMBEDDING_MODEL,
        )
    else:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

    return client.get_or_create_collection(
        name=CHROMA_COLL,
        embedding_function=ef,
        metadata={
            "hnsw:space": "cosine",
            "embedding_model": EMBEDDING_MODEL,
        },
    )


# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="knowledge-mcp",
    instructions=(
        "Knowledge base tools. Use verify_claims to check factual accuracy "
        "and index_documents to add new knowledge."
    ),
)

_start_time = time.time()


@mcp.tool
async def verify_claims(text: str, query: str, n_results: int = 5) -> dict:
    """
    Search the knowledge base for content similar to `text`.

    Implements confidence-based invalidation:
      - If KB has entries but best similarity < DRIFT_THRESHOLD,
        returns degraded=True with drift warning instead of silent 0.0.
        This surfaces embedding drift before it reaches users.
      - If similarity >= VERIFY_THRESHOLD: verified=True
      - If similarity < VERIFY_THRESHOLD but > DRIFT_THRESHOLD: verified=False
      - If similarity < DRIFT_THRESHOLD: degraded=True (possible drift)

    Args:
        text:      The text (claim / summary) to verify.
        query:     The original research query (used as additional context).
        n_results: How many KB entries to compare against.

    Returns:
        {
            matches:        [{"document": str, "similarity": float, "metadata": dict}],
            max_similarity: float,
            verified:       bool | None,
            contradictions: [str],
            degraded:       bool,
            drift_warning:  str | None,
        }
    """
    log.info("knowledge_mcp.verify", query=query, text_len=len(text))

    try:
        collection = _get_collection()
        count = collection.count()

        # ── Empty KB — expected on fresh deploy ───────────────────────────────
        if count == 0:
            log.info("knowledge_mcp.kb_empty")
            return {
                "matches": [],
                "max_similarity": 0.0,
                "verified": None,
                "contradictions": [],
                "degraded": False,
                "drift_warning": None,
                "kb_empty": True,
            }

        results = collection.query(
            query_texts=[text],
            n_results=min(n_results, count),
            include=["documents", "distances", "metadatas"],
        )

        docs = results["documents"][0] if results["documents"] else []
        distances = results["distances"][0] if results["distances"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []

        matches = []
        for doc, dist, meta in zip(docs, distances, metas):
            similarity = round(1.0 - (dist / 2.0), 4)
            matches.append(
                {
                    "document": doc[:500],
                    "similarity": similarity,
                    "metadata": meta or {},
                }
            )

        max_sim = max((m["similarity"] for m in matches), default=0.0)

        # ── Confidence-based invalidation ─────────────────────────────────────
        # KB has entries but nothing matches well → likely embedding drift.
        # The old vectors were computed with a different model version.
        # Return a drift warning instead of silently returning low confidence.
        drift_warning = None
        if max_sim < DRIFT_THRESHOLD and count > 0:
            drift_warning = (
                f"Possible embedding drift detected: KB has {count} entries "
                f"but best similarity is only {max_sim:.3f} (threshold={DRIFT_THRESHOLD}). "
                f"Consider re-indexing with current model ({EMBEDDING_MODEL}) "
                f"or calling cache_flush if embedding model was recently updated."
            )
            log.warning(
                "knowledge_mcp.drift_detected",
                max_similarity=max_sim,
                drift_threshold=DRIFT_THRESHOLD,
                kb_count=count,
                embedding_model=EMBEDDING_MODEL,
            )
            return {
                "matches": matches,
                "max_similarity": round(max_sim, 4),
                "verified": None,
                "contradictions": [],
                "degraded": True,
                "drift_warning": drift_warning,
                "kb_empty": False,
            }

        # ── Normal verification ───────────────────────────────────────────────
        verified = max_sim >= VERIFY_THRESHOLD
        contradictions = _detect_contradictions(text, docs)

        log.info(
            "knowledge_mcp.verify_done",
            max_similarity=max_sim,
            verified=verified,
            matches=len(matches),
        )

        return {
            "matches": matches,
            "max_similarity": round(max_sim, 4),
            "verified": verified,
            "contradictions": contradictions,
            "degraded": False,
            "drift_warning": None,
            "kb_empty": False,
        }

    except Exception as exc:
        log.error("knowledge_mcp.verify_error", error=str(exc))
        return {
            "matches": [],
            "max_similarity": 0.0,
            "verified": None,
            "contradictions": [],
            "degraded": True,
            "drift_warning": None,
            "error": str(exc),
        }


@mcp.tool
async def index_documents(documents: list[dict]) -> dict:
    """
    Upsert documents into the knowledge base.

    Each document dict must have:
        {
            "id":       str  (unique identifier; auto-generated if absent),
            "text":     str  (the content to embed),
            "metadata": dict (optional key-value metadata),
        }

    Returns:
        {"indexed": N, "collection": str, "total_docs": N}
    """
    if not documents:
        return {"indexed": 0, "error": "No documents provided"}

    collection = _get_collection()
    ids, texts, metas = [], [], []

    for doc in documents:
        ids.append(doc.get("id") or str(uuid.uuid4()))
        texts.append(doc.get("text", ""))
        metas.append(
            {
                **(doc.get("metadata") or {}),
                "embedding_model": EMBEDDING_MODEL,
                "indexed_at": str(int(time.time())),
            }
        )

    collection.upsert(ids=ids, documents=texts, metadatas=metas)
    log.info("knowledge_mcp.indexed", count=len(ids), collection=CHROMA_COLL)

    return {
        "indexed": len(ids),
        "collection": CHROMA_COLL,
        "total_docs": collection.count(),
    }


@mcp.tool
async def collection_info() -> dict:
    """
    Return metadata about the knowledge collection including drift indicators.

    Checks if stored documents were indexed with a different embedding model
    than the currently configured one — a signal that re-indexing may be needed.
    """
    try:
        collection = _get_collection()
        count = collection.count()

        # Check for model version mismatch in stored documents
        drift_risk = False
        if count > 0:
            try:
                sample = collection.get(limit=5, include=["metadatas"])
                stored_models = set(
                    m.get("embedding_model", "unknown") for m in (sample.get("metadatas") or [])
                )
                if stored_models and EMBEDDING_MODEL not in stored_models:
                    drift_risk = True
                    log.warning(
                        "knowledge_mcp.model_mismatch",
                        current_model=EMBEDDING_MODEL,
                        stored_models=list(stored_models),
                    )
            except Exception:
                pass

        return {
            "name": CHROMA_COLL,
            "count": count,
            "embedding_model": EMBEDDING_MODEL,
            "drift_risk": drift_risk,
            "verify_threshold": VERIFY_THRESHOLD,
            "drift_threshold": DRIFT_THRESHOLD,
            "uptime_secs": round(time.time() - _start_time, 1),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_contradictions(text: str, kb_docs: list[str]) -> list[str]:
    """
    Naive contradiction detector: looks for negation patterns in KB that
    conflict with assertions in the input text.

    Production upgrade path: replace with NLI model
    (e.g. facebook/bart-large-mnli or cross-encoder/nli-deberta-v3-base).
    """
    negation_markers = ["not ", "no ", "never ", "false", "incorrect", "wrong"]
    contradictions = []
    words = set(text.lower().split())

    for doc in kb_docs:
        for marker in negation_markers:
            if marker in doc.lower():
                negated_words = set(doc.lower().replace(marker, "").split())
                overlap = words & negated_words
                if len(overlap) > 3:
                    contradictions.append(
                        f"KB entry may contradict claim (overlap: {', '.join(list(overlap)[:5])})"
                    )
                    break

    return contradictions[:3]


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(
        "knowledge_mcp_starting",
        port=MCP_PORT,
        chroma=f"{CHROMA_HOST}:{CHROMA_PORT}",
        embedding_model=EMBEDDING_MODEL,
        verify_threshold=VERIFY_THRESHOLD,
        drift_threshold=DRIFT_THRESHOLD,
    )
    mcp.run(transport="streamable-http", host="0.0.0.0", port=MCP_PORT, path="/mcp")
