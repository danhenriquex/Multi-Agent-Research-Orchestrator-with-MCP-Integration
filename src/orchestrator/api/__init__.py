from typing import Any

from pydantic import BaseModel


class ResearchRequest(BaseModel):
    query: str
    max_results: int = 5


class ToolCallRecord(BaseModel):
    step: int | str
    tool: str | None = None  # MCP tool name (if applicable)
    agent: str | None = None  # A2A agent name
    task: str | None = None  # A2A task name
    input: str
    duration_ms: int
    degraded: bool = False
    status: str = "ok"
    protocol: str = "a2a"  # "a2a" or "mcp"


class VerificationResult(BaseModel):
    verified: bool | None = None
    confidence: float | None = None
    flags: list[str] = []
    degraded: bool = False


class ResearchResponse(BaseModel):
    query: str
    answer: str
    sources: list[Any]
    plan: list[dict]
    tool_calls: list[dict]  # loosened — A2A records have different shapes
    verification: VerificationResult = VerificationResult()
    duration_ms: int
