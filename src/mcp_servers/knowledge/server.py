"""
Knowledge MCP Server
---------------------
FastMCP server on port 8003, backed by ChromaDB.
Used exclusively by the Fact-Check Agent.

Tools:
  verify_claims   – vector-search for text similar to the input, return
                    top-k matches + max cosine similarity + contradictions
  index_documents – upsert documents into the ChromaDB collection
  collection_info – return collection size and metadata
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
MCP_PORT = int(os.getenv("MCP_SERVER_PORT", "8003"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

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

    # Use OpenAI embeddings if key is available, else sentence-transformers
    if OPENAI_KEY:
        ef = embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_KEY,
            model_name="text-embedding-3-small",
        )
    else:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

    return client.get_or_create_collection(
        name=CHROMA_COLL,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
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
    Returns top matches, max cosine similarity, and detected contradictions.

    Args:
        text:      The text (claim / summary) to verify.
        query:     The original research query (used as additional context).
        n_results: How many KB entries to compare against.

    Returns:
        {
            matches:        [{"document": str, "similarity": float, "metadata": dict}],
            max_similarity: float,
            contradictions: [str],   # phrases that contradict top matches
        }
    """
    log.info("knowledge_mcp.verify", query=query, text_len=len(text))

    try:
        collection = _get_collection()
        results = collection.query(
            query_texts=[text],
            n_results=min(n_results, max(1, collection.count())),
            include=["documents", "distances", "metadatas"],
        )

        docs = results["documents"][0] if results["documents"] else []
        distances = results["distances"][0] if results["distances"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []

        # ChromaDB cosine distance: 0 = identical, 2 = opposite
        # Convert to similarity: 1 - (d / 2)
        matches = []
        for doc, dist, meta in zip(docs, distances, metas):
            similarity = round(1.0 - (dist / 2.0), 4)
            matches.append(
                {
                    "document": doc[:500],  # truncate for wire
                    "similarity": similarity,
                    "metadata": meta or {},
                }
            )

        max_sim = max((m["similarity"] for m in matches), default=0.0)

        # Simple contradiction detection: if the KB says "X is false" while
        # our text contains "X", flag it (naive but works for portfolio demo)
        contradictions = _detect_contradictions(text, docs)

        log.info("knowledge_mcp.verify_done", max_similarity=max_sim, matches=len(matches))

        return {
            "matches": matches,
            "max_similarity": round(max_sim, 4),
            "contradictions": contradictions,
        }

    except Exception as exc:
        log.error("knowledge_mcp.verify_error", error=str(exc))
        return {
            "matches": [],
            "max_similarity": 0.0,
            "contradictions": [],
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

    ids = []
    texts = []
    metas = []

    for doc in documents:
        ids.append(doc.get("id") or str(uuid.uuid4()))
        texts.append(doc.get("text", ""))
        metas.append(doc.get("metadata") or {})

    collection.upsert(ids=ids, documents=texts, metadatas=metas)

    log.info("knowledge_mcp.indexed", count=len(ids), collection=CHROMA_COLL)

    return {
        "indexed": len(ids),
        "collection": CHROMA_COLL,
        "total_docs": collection.count(),
    }


@mcp.tool
async def collection_info() -> dict:
    """Return metadata about the knowledge collection."""
    try:
        collection = _get_collection()
        return {
            "name": CHROMA_COLL,
            "count": collection.count(),
            "uptime_secs": round(time.time() - _start_time, 1),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_contradictions(text: str, kb_docs: list[str]) -> list[str]:
    """
    Naive contradiction detector: looks for negation patterns in KB that
    conflict with assertions in the input text.

    This is intentionally simple for the portfolio demo — in production
    you'd use an NLI model (e.g. facebook/bart-large-mnli).
    """
    negation_markers = ["not ", "no ", "never ", "false", "incorrect", "wrong"]
    contradictions = []

    words = set(text.lower().split())
    for doc in kb_docs:
        for marker in negation_markers:
            if marker in doc.lower():
                # Check if the negated concept overlaps with our text
                negated_words = set(doc.lower().replace(marker, "").split())
                overlap = words & negated_words
                if len(overlap) > 3:  # meaningful overlap threshold
                    contradictions.append(
                        f"KB entry may contradict claim (overlap: {', '.join(list(overlap)[:5])})"
                    )
                    break

    return contradictions[:3]  # at most 3 flags


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("knowledge_mcp_starting", port=MCP_PORT, chroma=f"{CHROMA_HOST}:{CHROMA_PORT}")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=MCP_PORT, path="/mcp")
