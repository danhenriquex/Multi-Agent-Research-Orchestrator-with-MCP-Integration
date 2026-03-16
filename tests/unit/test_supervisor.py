"""
Unit tests for the SupervisorAgent.
Verifies that A2A calls are made in the correct order and that
graceful degradation works when agents are unavailable.
"""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from a2a.models import A2AResponse
from orchestrator.supervisor import SupervisorAgent

REGISTRY = {
    "search": "http://search-agent:8010",
    "summarize": "http://summarize-agent:8011",
    "fact_check": "http://fact-check-agent:8012",
}

MOCK_PLAN = [
    {"step": 1, "tool": "search", "input": "AI agents 2024", "reason": "Gather info"},
    {"step": 2, "tool": "summarize", "input": "#search", "reason": "Synthesise"},
]


def make_agent():
    return SupervisorAgent(
        openai_api_key="sk-test",
        a2a_registry=REGISTRY,
        model="gpt-4o-mini",
    )


def search_ok(n=2):
    return A2AResponse(
        agent="search",
        status="ok",
        result={"results": [{"title": f"R{i}", "snippet": "x", "url": "u"} for i in range(n)]},
        duration_ms=50,
    )


def summarize_ok():
    return A2AResponse(
        agent="summarize",
        status="ok",
        result={
            "summary": "AI agents are autonomous systems.",
            "sources": [],
            "input_tokens": 100,
        },
        duration_ms=80,
    )


def factcheck_ok(verified=True, confidence=0.9):
    return A2AResponse(
        agent="fact_check",
        status="ok",
        result={
            "verified": verified,
            "confidence": confidence,
            "flags": [],
            "checked_at": "2024-01-01",
        },
        duration_ms=30,
    )


class TestSupervisorAgent:
    @pytest.mark.asyncio
    async def test_full_happy_path(self):
        agent = make_agent()

        with (
            patch.object(agent._planner, "plan", new=AsyncMock(return_value=MOCK_PLAN)),
            patch.object(
                agent._a2a,
                "call",
                new=AsyncMock(side_effect=[search_ok(), summarize_ok(), factcheck_ok()]),
            ),
        ):
            chunks = []
            async for chunk in agent.run("What are AI agents?"):
                chunks.append(chunk)

        final = next(c for c in chunks if isinstance(c, dict))
        assert final["answer"] == "AI agents are autonomous systems."
        assert final["verification"]["verified"] is True
        assert final["verification"]["confidence"] == 0.9
        # Confirm all three A2A calls were made
        assert len([c for c in chunks if isinstance(c, str) and "SearchAgent" in c]) >= 1
        assert len([c for c in chunks if isinstance(c, str) and "SummarizeAgent" in c]) >= 1
        assert len([c for c in chunks if isinstance(c, str) and "FactCheckAgent" in c]) >= 1

    @pytest.mark.asyncio
    async def test_fact_check_unavailable_does_not_block(self):
        """FactCheckAgent failure should not prevent result delivery."""
        agent = make_agent()
        fc_error = A2AResponse(agent="fact_check", status="error", error="service down")

        with (
            patch.object(agent._planner, "plan", new=AsyncMock(return_value=MOCK_PLAN)),
            patch.object(
                agent._a2a,
                "call",
                new=AsyncMock(side_effect=[search_ok(), summarize_ok(), fc_error]),
            ),
        ):
            chunks = []
            async for chunk in agent.run("test query"):
                chunks.append(chunk)

        final = next(c for c in chunks if isinstance(c, dict))
        # Answer still present despite fact-check failure
        assert "AI agents" in final["answer"]
        assert final["verification"] == {}

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_recheck(self):
        """Confidence < RECHECK_THRESHOLD should trigger a second search call."""
        agent = make_agent()
        recheck_search = A2AResponse(
            agent="search",
            status="ok",
            result={"results": [{"title": "Extra", "snippet": "y", "url": "v"}]},
            duration_ms=40,
        )

        calls = [
            search_ok(),
            summarize_ok(),
            factcheck_ok(verified=False, confidence=0.3),
            recheck_search,
        ]
        mock_call = AsyncMock(side_effect=calls)

        with (
            patch.object(agent._planner, "plan", new=AsyncMock(return_value=MOCK_PLAN)),
            patch.object(agent._a2a, "call", new=mock_call),
        ):
            chunks = []
            async for chunk in agent.run("test query"):
                chunks.append(chunk)

        # 4 A2A calls total: search, summarize, fact_check, recheck
        assert mock_call.call_count == 4
        recheck_stream = [c for c in chunks if isinstance(c, str) and "additional search" in c]
        assert len(recheck_stream) >= 1

    @pytest.mark.asyncio
    async def test_search_failure_graceful(self):
        """Search failure should produce an error message but not raise."""
        agent = make_agent()
        search_err = A2AResponse(agent="search", status="error", error="MCP timeout")

        with (
            patch.object(agent._planner, "plan", new=AsyncMock(return_value=MOCK_PLAN)),
            patch.object(
                agent._a2a,
                "call",
                new=AsyncMock(side_effect=[search_err, summarize_ok(), factcheck_ok()]),
            ),
        ):
            chunks = []
            async for chunk in agent.run("test query"):
                chunks.append(chunk)

        warnings = [c for c in chunks if isinstance(c, str) and "error" in c.lower()]
        assert len(warnings) >= 1

    @pytest.mark.asyncio
    async def test_tool_calls_record_protocol(self):
        """Every tool call record should carry protocol='a2a'."""
        agent = make_agent()

        with (
            patch.object(agent._planner, "plan", new=AsyncMock(return_value=MOCK_PLAN)),
            patch.object(
                agent._a2a,
                "call",
                new=AsyncMock(side_effect=[search_ok(), summarize_ok(), factcheck_ok()]),
            ),
        ):
            chunks = []
            async for chunk in agent.run("test"):
                chunks.append(chunk)

        final = next(c for c in chunks if isinstance(c, dict))
        for record in final["tool_calls"]:
            assert record["protocol"] == "a2a"
