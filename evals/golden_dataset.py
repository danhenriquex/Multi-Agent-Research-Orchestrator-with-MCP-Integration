"""
Golden dataset for regression testing.

Each entry has:
  query:            the research question
  expected_answer:  reference answer to score against (ROUGE, BERTScore)
  expected_sources: domains that should appear in sources
  min_length:       minimum acceptable answer length in chars
  tags:             for filtering (smoke vs full benchmark)

Smoke set (tag="smoke"): 5 critical cases — runs on every commit (~2 min)
Full set  (tag="full"):  all cases — runs nightly or pre-release (~15 min)
"""

GOLDEN_DATASET = [
    # ── Smoke test cases (5 critical) ────────────────────────────────────────
    {
        "id": "a2a-protocol",
        "query": "What is the A2A protocol for AI agents?",
        "expected_answer": (
            "A2A (Agent2Agent) is an open standard introduced by Google in April 2025 "
            "for communication between AI agents. It enables agents from different "
            "frameworks and providers to discover capabilities, send structured requests, "
            "and coordinate tasks without exposing internal architecture. "
            "A2A supports asynchronous communication and multi-step task lifecycles."
        ),
        "expected_sources": ["ibm.com", "google", "codilime.com", "deeplearning.ai"],
        "min_length": 150,
        "tags": ["smoke", "full"],
    },
    {
        "id": "mcp-protocol",
        "query": "What is Model Context Protocol and how does it work?",
        "expected_answer": (
            "Model Context Protocol (MCP) is an open standard from Anthropic that defines "
            "how AI agents connect to external tools and data sources. "
            "It provides a clean abstraction boundary between agent logic and tool "
            "implementation. Each MCP server exposes tools that agents can discover "
            "and call without knowing the underlying implementation."
        ),
        "expected_sources": ["anthropic.com", "modelcontextprotocol.io"],
        "min_length": 150,
        "tags": ["smoke", "full"],
    },
    {
        "id": "rewoo-planning",
        "query": "What is ReWOO planning and how does it compare to ReAct?",
        "expected_answer": (
            "ReWOO (Reason without Observation) separates the planning phase from "
            "execution by generating a full plan before making any tool calls. "
            "ReAct interleaves reasoning and acting in a loop. "
            "ReWOO is more auditable and easier to instrument because the complete "
            "plan is available before execution begins."
        ),
        "expected_sources": [],
        "min_length": 100,
        "tags": ["smoke", "full"],
    },
    {
        "id": "multi-agent-patterns",
        "query": "What are best practices for multi-agent system design?",
        "expected_answer": (
            "Best practices include separation of concerns between agents, "
            "graceful degradation when agents fail, structured communication protocols, "
            "observability through distributed tracing, and idempotent tool calls. "
            "Agents should be stateless where possible and communicate via "
            "well-defined interfaces."
        ),
        "expected_sources": [],
        "min_length": 100,
        "tags": ["smoke", "full"],
    },
    {
        "id": "rag-overview",
        "query": "What is RAG in AI and how does it work?",
        "expected_answer": (
            "RAG (Retrieval-Augmented Generation) combines a retrieval system with "
            "a language model. Given a query, relevant documents are retrieved from "
            "a vector database using semantic search, then provided as context to the "
            "LLM alongside the query. This grounds the model's response in retrieved "
            "facts, reducing hallucination."
        ),
        "expected_sources": [],
        "min_length": 120,
        "tags": ["smoke", "full"],
    },
    # ── Full benchmark additional cases ───────────────────────────────────────
    {
        "id": "langchain-vs-langgraph",
        "query": "What is the difference between LangChain and LangGraph?",
        "expected_answer": (
            "LangChain is a framework for building LLM applications with chains and agents. "
            "LangGraph extends LangChain with a graph-based execution model that supports "
            "cycles, conditional edges, and stateful multi-agent workflows. "
            "LangGraph is better suited for complex agent orchestration while LangChain "
            "is simpler for linear pipelines."
        ),
        "expected_sources": ["langchain.com", "python.langchain.com"],
        "min_length": 120,
        "tags": ["full"],
    },
    {
        "id": "vector-databases",
        "query": "What are the main vector databases available and their trade-offs?",
        "expected_answer": (
            "Main vector databases include Pinecone (managed, scalable), "
            "Weaviate (open source, hybrid search), Chroma (lightweight, local-first), "
            "Qdrant (Rust-based, high performance), and pgvector (Postgres extension). "
            "Trade-offs involve managed vs self-hosted, query latency, "
            "filtering capabilities, and cost."
        ),
        "expected_sources": [],
        "min_length": 120,
        "tags": ["full"],
    },
    {
        "id": "llm-guardrails",
        "query": "What is guardrails in LLMs and which technologies can be used?",
        "expected_answer": (
            "Guardrails in LLMs are mechanisms that ensure safe, ethical outputs by "
            "monitoring and filtering model responses. Technologies include "
            "RLHF, content filters, NeMo Guardrails, Guardrails AI, and "
            "LLM-as-judge evaluation. Approaches include prompt engineering, "
            "rule-based filtering, and output classifiers."
        ),
        "expected_sources": ["nvidia.com", "humanloop.com"],
        "min_length": 120,
        "tags": ["full"],
    },
    {
        "id": "transformer-architecture",
        "query": "What is the transformer architecture and why is it important?",
        "expected_answer": (
            "The transformer architecture uses self-attention mechanisms to process "
            "sequences in parallel rather than sequentially. Introduced in 'Attention "
            "is All You Need' (2017), it enables efficient training on long sequences "
            "and has become the foundation for all modern LLMs including GPT and BERT."
        ),
        "expected_sources": [],
        "min_length": 100,
        "tags": ["full"],
    },
    {
        "id": "fine-tuning-vs-rag",
        "query": "When should you use fine-tuning versus RAG for LLMs?",
        "expected_answer": (
            "RAG is preferred when knowledge changes frequently, when you need "
            "source attribution, or when training data is limited. "
            "Fine-tuning is better when you need to change model behavior, tone, "
            "or format, and when knowledge is stable. "
            "RAG is cheaper and faster to update; fine-tuning gives more consistent "
            "style but requires more compute."
        ),
        "expected_sources": [],
        "min_length": 120,
        "tags": ["full"],
    },
]


def get_smoke_cases() -> list[dict]:
    """Return only smoke test cases (fast subset)."""
    return [c for c in GOLDEN_DATASET if "smoke" in c["tags"]]


def get_full_cases() -> list[dict]:
    """Return all golden dataset cases."""
    return GOLDEN_DATASET


def get_case_by_id(case_id: str) -> dict | None:
    """Return a specific case by ID."""
    return next((c for c in GOLDEN_DATASET if c["id"] == case_id), None)
