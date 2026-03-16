"""
A2A message schemas — shared by every agent service.
"""

from typing import Any

from pydantic import BaseModel, Field


class A2AMessage(BaseModel):
    """Envelope sent from one agent to another via HTTP POST /a2a."""

    sender: str = Field(..., description="Name of the calling agent")
    receiver: str = Field(..., description="Name of the target agent")
    task: str = Field(..., description="Task identifier (e.g. 'search', 'summarize', 'fact_check')")
    payload: dict[str, Any] = Field(default_factory=dict, description="Task-specific arguments")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional cross-agent context: session_id, trace_id, prior_results, etc.",
    )


class A2AResponse(BaseModel):
    """Structured response from a peer agent."""

    agent: str = Field(..., description="Name of the responding agent")
    status: str = Field(..., description="'ok', 'error', or 'partial'")
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
