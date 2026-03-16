"""
A2A (Agent-to-Agent) Protocol
------------------------------
Defines the message contract and lightweight HTTP transport for peer agent
communication.

Key difference from MCP:
  MCP  = vertical  — agent calls a TOOL (dumb executor, no reasoning)
  A2A  = horizontal — agent calls another AGENT (has its own reasoning loop)

Wire format (JSON):
  {
    "sender":    "supervisor",
    "receiver":  "search",
    "task":      "search",
    "payload":   {"query": "..."},
    "context":   {"session_id": "...", "trace_id": "..."},  # optional
  }

Response:
  {
    "agent":   "search",
    "status":  "ok" | "error" | "partial",
    "result":  {...},
    "error":   null | "...",
    "duration_ms": 123,
  }
"""

from .client import A2AClient
from .models import A2AMessage, A2AResponse
from .router import a2a_router

__all__ = ["A2AClient", "A2AMessage", "A2AResponse", "a2a_router"]
