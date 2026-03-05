from pydantic import BaseModel


class ResearchRequest(BaseModel):
    query: str
    max_results: int = 5


class ToolCallRecord(BaseModel):
    step: int
    tool: str
    input: str
    duration_ms: int
    degraded: bool = False


class ResearchResponse(BaseModel):
    query: str
    answer: str
    sources: list[str]
    plan: list[dict]
    tool_calls: list[ToolCallRecord]
    duration_ms: int