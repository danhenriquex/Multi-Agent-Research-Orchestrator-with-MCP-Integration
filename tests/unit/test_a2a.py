"""
Unit tests for A2A protocol layer.

Tests:
  - A2AMessage / A2AResponse model validation
  - A2AClient routing and error handling
  - A2A router dispatch logic
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from a2a.client import A2AClient
from a2a.models import A2AMessage, A2AResponse
from a2a.router import _handlers, handle_a2a, register_handler

# ── Model tests ───────────────────────────────────────────────────────────────


class TestA2AModels:
    def test_message_defaults(self):
        msg = A2AMessage(sender="sup", receiver="search", task="search")
        assert msg.payload == {}
        assert msg.context == {}

    def test_message_with_payload(self):
        msg = A2AMessage(
            sender="supervisor",
            receiver="search",
            task="search",
            payload={"query": "AI agents 2024"},
            context={"session_id": "abc"},
        )
        assert msg.payload["query"] == "AI agents 2024"
        assert msg.context["session_id"] == "abc"

    def test_response_ok(self):
        r = A2AResponse(agent="search", status="ok", result={"results": []})
        assert r.error is None
        assert r.duration_ms == 0

    def test_response_error(self):
        r = A2AResponse(agent="search", status="error", error="timeout")
        assert r.status == "error"
        assert r.result == {}


# ── Client tests ──────────────────────────────────────────────────────────────


class TestA2AClient:
    def setup_method(self):
        self.registry = {
            "search": "http://search-agent:8010",
            "summarize": "http://summarize-agent:8011",
        }
        self.client = A2AClient(registry=self.registry)

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self):
        msg = A2AMessage(sender="sup", receiver="unknown", task="search")
        resp = await self.client.call("unknown", msg)
        assert resp.status == "error"
        assert "unknown" in resp.error

    @pytest.mark.asyncio
    async def test_successful_call(self):
        msg = A2AMessage(
            sender="supervisor",
            receiver="search",
            task="search",
            payload={"query": "test"},
        )
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "agent": "search",
            "status": "ok",
            "result": {"results": [{"title": "Test"}]},
            "error": None,
            "duration_ms": 50,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("a2a.client.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            resp = await self.client.call("search", msg)

        assert resp.status == "ok"
        assert resp.result["results"][0]["title"] == "Test"

    @pytest.mark.asyncio
    async def test_http_error_returns_error_response(self):
        msg = A2AMessage(sender="sup", receiver="search", task="search")

        with patch("a2a.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_cls.return_value = mock_http

            # Disable retries for the test
            with patch("a2a.client.retry", lambda **kw: lambda f: f):
                resp = await self.client.call("search", msg)

        assert resp.status == "error"
        assert "Connection refused" in resp.error

    @pytest.mark.asyncio
    async def test_health_check_all_down(self):
        with patch("a2a.client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)
            mock_http.get = AsyncMock(side_effect=Exception("unreachable"))
            mock_cls.return_value = mock_http

            result = await self.client.health_check()

        assert result == {"search": False, "summarize": False}


# ── Router tests ──────────────────────────────────────────────────────────────


class TestA2ARouter:
    def setup_method(self):
        # Clear handlers between tests
        _handlers.clear()

    @pytest.mark.asyncio
    async def test_unknown_task_returns_error(self):
        msg = A2AMessage(sender="sup", receiver="search", task="nonexistent")
        resp = await handle_a2a(msg)
        assert resp.status == "error"
        assert "nonexistent" in resp.error

    @pytest.mark.asyncio
    async def test_registered_handler_called(self):
        async def my_handler(msg: A2AMessage) -> dict:
            return {"echo": msg.payload.get("value")}

        register_handler("echo", my_handler)

        msg = A2AMessage(sender="test", receiver="echo", task="echo", payload={"value": "hello"})
        resp = await handle_a2a(msg)

        assert resp.status == "ok"
        assert resp.result["echo"] == "hello"
        assert resp.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_handler_exception_returns_error(self):
        async def failing_handler(msg: A2AMessage) -> dict:
            raise ValueError("Something went wrong")

        register_handler("failing", failing_handler)

        msg = A2AMessage(sender="test", receiver="x", task="failing")
        resp = await handle_a2a(msg)

        assert resp.status == "error"
        assert "Something went wrong" in resp.error

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        register_handler("ping", AsyncMock(return_value={"pong": True}))
        register_handler("echo", AsyncMock(return_value={"echo": "ok"}))

        assert set(_handlers.keys()) == {"ping", "echo"}
