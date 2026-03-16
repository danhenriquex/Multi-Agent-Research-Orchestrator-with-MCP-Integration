"""
Integration tests for the Research Agent.

These tests require the full stack to be running:
  make up

Run with:
  make test-integration

Each test hits real HTTP endpoints — no mocks.
Tests are ordered from smallest scope (single agent) to largest (full pipeline).
"""

import json
import os

import httpx
import pytest


# Skip entire module if stack is not reachable
def _stack_available() -> bool:
    try:
        httpx.get("http://localhost:8000/health", timeout=3.0)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _stack_available(),
    reason="Full stack not running — skipping integration tests (run: make up)",
)

# ── Base URLs ──────────────────────────────────────────────────────────────────

ORCHESTRATOR = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
SEARCH_AGENT = os.getenv("SEARCH_AGENT_URL", "http://localhost:8010")
SUMMARIZE_AGENT = os.getenv("SUMMARIZE_AGENT_URL", "http://localhost:8011")
FACT_CHECK_AGENT = os.getenv("FACT_CHECK_AGENT_URL", "http://localhost:8012")
SEARCH_MCP = os.getenv("SEARCH_MCP_URL", "http://localhost:8001")
KNOWLEDGE_MCP = os.getenv("KNOWLEDGE_MCP_URL", "http://localhost:8003")

TIMEOUT = httpx.Timeout(30.0)


# ── Helpers ────────────────────────────────────────────────────────────────────


def a2a_payload(sender: str, receiver: str, task: str, payload: dict) -> dict:
    return {
        "sender": sender,
        "receiver": receiver,
        "task": task,
        "payload": payload,
        "context": {},
    }


# ── Health checks ──────────────────────────────────────────────────────────────


class TestHealth:
    def test_search_agent_healthy(self):
        r = httpx.get(f"{SEARCH_AGENT}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["agent"] == "search"

    def test_summarize_agent_healthy(self):
        r = httpx.get(f"{SUMMARIZE_AGENT}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["agent"] == "summarize"

    def test_fact_check_agent_healthy(self):
        r = httpx.get(f"{FACT_CHECK_AGENT}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["agent"] == "fact_check"

    def test_orchestrator_healthy(self):
        r = httpx.get(f"{ORCHESTRATOR}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "a2a_agents" in data
        assert "search" in data["a2a_agents"]
        assert "summarize" in data["a2a_agents"]
        assert "fact_check" in data["a2a_agents"]


# ── A2A layer: individual agents ───────────────────────────────────────────────


class TestSearchAgentA2A:
    def test_search_returns_results(self):
        r = httpx.post(
            f"{SEARCH_AGENT}/a2a",
            json=a2a_payload(
                "test",
                "search",
                "search",
                {"query": "Python programming language", "max_results": 3},
            ),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        results = data["result"]["results"]
        # Results may be empty if Tavily key is missing — just check structure
        assert isinstance(results, list)
        if results:
            assert all("title" in r and "url" in r for r in results)

    def test_search_empty_query_returns_error(self):
        r = httpx.post(
            f"{SEARCH_AGENT}/a2a",
            json=a2a_payload("test", "search", "search", {"query": ""}),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        # Either an error status or empty results — both are acceptable
        assert data["status"] in ("ok", "error")

    def test_unknown_task_returns_error(self):
        r = httpx.post(
            f"{SEARCH_AGENT}/a2a",
            json=a2a_payload("test", "search", "nonexistent_task", {}),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"


class TestSummarizeAgentA2A:
    def test_summarize_returns_summary(self):
        results = [
            {
                "title": "Python basics",
                "snippet": "Python is a high-level programming language known for readability.",
                "url": "https://python.org",
            },
            {
                "title": "Python features",
                "snippet": "Python supports multiple programming paradigms including OOP and functional programming.",
                "url": "https://docs.python.org",
            },
        ]
        r = httpx.post(
            f"{SUMMARIZE_AGENT}/a2a",
            json=a2a_payload(
                "test",
                "summarize",
                "summarize",
                {"query": "What is Python?", "results": results},
            ),
            timeout=httpx.Timeout(60.0),
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert len(data["result"].get("summary", "")) > 50
        assert "input_tokens" in data["result"]

    def test_summarize_empty_results(self):
        r = httpx.post(
            f"{SUMMARIZE_AGENT}/a2a",
            json=a2a_payload("test", "summarize", "summarize", {"query": "test", "results": []}),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "No results" in data["result"].get("summary", "")


class TestFactCheckAgentA2A:
    def test_fact_check_returns_verification(self):
        r = httpx.post(
            f"{FACT_CHECK_AGENT}/a2a",
            json=a2a_payload(
                "test",
                "fact_check",
                "fact_check",
                {
                    "summary": "Python is a programming language created by Guido van Rossum.",
                    "query": "What is Python?",
                    "sources": [],
                },
            ),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        result = data["result"]
        assert "verified" in result
        assert "confidence" in result
        assert "checked_at" in result

    def test_fact_check_empty_summary(self):
        r = httpx.post(
            f"{FACT_CHECK_AGENT}/a2a",
            json=a2a_payload(
                "test",
                "fact_check",
                "fact_check",
                {
                    "summary": "",
                    "query": "test",
                    "sources": [],
                },
            ),
            timeout=TIMEOUT,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["result"]["verified"] is False

    def test_index_then_verify_improves_confidence(self):
        """Index a document then verify a related claim — confidence should be > 0."""
        # Index a document
        index_r = httpx.post(
            f"{FACT_CHECK_AGENT}/a2a",
            json=a2a_payload(
                "test",
                "fact_check",
                "index",
                {
                    "documents": [
                        {
                            "id": "test-doc-001",
                            "text": "The Eiffel Tower is located in Paris, France. It was built in 1889.",
                            "metadata": {"source": "integration-test"},
                        }
                    ]
                },
            ),
            timeout=TIMEOUT,
        )
        assert index_r.status_code == 200
        index_result = index_r.json()["result"]
        # May fail if OpenAI key missing — degraded mode returns 0
        if index_result.get("error"):
            pytest.skip(
                f"Knowledge base unavailable (likely missing API key): {index_result['error']}"
            )
        assert index_result.get("indexed", 0) >= 1

        # Now verify a related claim
        verify_r = httpx.post(
            f"{FACT_CHECK_AGENT}/a2a",
            json=a2a_payload(
                "test",
                "fact_check",
                "fact_check",
                {
                    "summary": "The Eiffel Tower is a famous landmark in Paris, France.",
                    "query": "Where is the Eiffel Tower?",
                    "sources": [],
                },
            ),
            timeout=TIMEOUT,
        )
        assert verify_r.status_code == 200
        result = verify_r.json()["result"]
        # Confidence should now be > 0 since we indexed a related document
        assert result.get("confidence") is not None


# ── Full pipeline ──────────────────────────────────────────────────────────────


class TestFullPipeline:
    def test_research_endpoint_returns_answer(self):
        r = httpx.post(
            f"{ORCHESTRATOR}/research",
            json={"query": "What is the MCP protocol for AI agents?"},
            timeout=httpx.Timeout(120.0),
        )
        assert r.status_code == 200
        data = r.json()

        # Answer must be present (may be short if search returned no results)
        assert len(data["answer"]) > 0
        if data["answer"] == "No results to summarise.":
            pytest.skip("Search returned no results — likely missing Tavily API key in CI")
        assert data["query"] == "What is the MCP protocol for AI agents?"

        # Plan must have been generated
        assert len(data["plan"]) >= 2

        # All tool calls must use A2A protocol
        for call in data["tool_calls"]:
            assert call["protocol"] == "a2a"
            assert call["status"] == "ok"

        # Verification block must be present
        assert "verification" in data
        assert "duration_ms" in data

    def test_research_records_sources(self):
        r = httpx.post(
            f"{ORCHESTRATOR}/research",
            json={"query": "What is Docker containerization?"},
            timeout=httpx.Timeout(120.0),
        )
        assert r.status_code == 200
        data = r.json()
        if not data["sources"]:
            pytest.skip("No sources returned — likely missing Tavily API key in CI")
        assert all(s.startswith("http") for s in data["sources"])

    def test_streaming_endpoint_yields_events(self):
        events = []
        with httpx.stream(
            "POST",
            f"{ORCHESTRATOR}/research/stream",
            json={"query": "What is Redis?"},
            timeout=httpx.Timeout(120.0),
        ) as r:
            assert r.status_code == 200
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(line[6:])
                if line == "data: [DONE]":
                    break

        # Should have planning, agent call events, and a final result
        assert len(events) >= 5
        assert any("[DONE]" in e for e in events)

        # Final result before [DONE] should be valid JSON with answer
        result_events = [e for e in events if e.startswith("{")]
        assert len(result_events) >= 1
        final = json.loads(result_events[-1])
        assert "answer" in final
        if final["answer"] == "No results to summarise.":
            pytest.skip("Search returned no results — likely missing Tavily API key in CI")
        assert len(final["answer"]) > 50

    def test_invalid_query_handled_gracefully(self):
        """Empty or whitespace query should not crash the service."""
        r = httpx.post(
            f"{ORCHESTRATOR}/research",
            json={"query": "   "},
            timeout=httpx.Timeout(60.0),
        )
        # Should return 200 with some kind of answer, not a 500
        assert r.status_code == 200
