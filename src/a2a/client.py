"""
A2AClient
----------
Lightweight async HTTP client for agent-to-agent calls.

Usage:
    client = A2AClient(registry={"search": "http://search-agent:8010"})
    response = await client.call("search", A2AMessage(
        sender="supervisor",
        receiver="search",
        task="search",
        payload={"query": "climate change 2024"},
    ))
"""

import time

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import A2AMessage, A2AResponse

log = structlog.get_logger()


class A2AClient:
    """Send A2A messages to peer agents via HTTP POST /a2a."""

    def __init__(self, registry: dict[str, str], timeout: float = 30.0):
        """
        Args:
            registry: Map of agent_name → base_url.
                      e.g. {"search": "http://search-agent:8010"}
            timeout: HTTP timeout in seconds.
        """
        self._registry = registry
        self._timeout = timeout

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    async def call(self, agent_name: str, message: A2AMessage) -> A2AResponse:
        """
        Send a message to a peer agent and return its response.

        Args:
            agent_name: Key into the registry (e.g. "search").
            message: The A2AMessage to send.

        Returns:
            A2AResponse from the peer agent.
        """
        base_url = self._registry.get(agent_name)
        if not base_url:
            return A2AResponse(
                agent=agent_name,
                status="error",
                error=f"Agent '{agent_name}' not found in registry. "
                f"Known agents: {list(self._registry.keys())}",
            )

        url = base_url.rstrip("/") + "/a2a"
        t0 = time.time()

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=message.model_dump())
                resp.raise_for_status()
                data = resp.json()
                elapsed = round((time.time() - t0) * 1000)
                log.info(
                    "a2a_call_ok",
                    sender=message.sender,
                    receiver=agent_name,
                    task=message.task,
                    duration_ms=elapsed,
                )
                return A2AResponse(**{**data, "duration_ms": elapsed})

        except Exception as exc:
            elapsed = round((time.time() - t0) * 1000)
            log.error(
                "a2a_call_failed",
                receiver=agent_name,
                task=message.task,
                error=str(exc),
                duration_ms=elapsed,
            )
            return A2AResponse(
                agent=agent_name,
                status="error",
                error=str(exc),
                duration_ms=elapsed,
            )

    async def health_check(self) -> dict[str, bool]:
        """Ping every registered agent's /health endpoint."""
        results: dict[str, bool] = {}
        for name, base_url in self._registry.items():
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(base_url.rstrip("/") + "/health")
                    results[name] = resp.status_code == 200
            except Exception:
                results[name] = False
        return results
