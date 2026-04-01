"""
ReWOO Planner
-------------
Implements Reason → Plan → Execute pattern.

Given a research query, the planner asks the LLM to produce a structured
plan of tool calls BEFORE executing any of them. This is the key difference
from ReAct (which interleaves reasoning and action):

  ReAct:   think → act → observe → think → act → ...
  ReWOO:   think+plan → execute all → synthesize

Benefits for this project:
  - Full plan is auditable before execution starts
  - Easier to instrument with Phoenix spans
  - Planning time vs execution time is measurable (portfolio signal)
"""

import json
import re

import structlog
from openai import AsyncOpenAI
from opentelemetry import trace as otel_trace

try:
    from langsmith import traceable
except ImportError:  # graceful fallback if langsmith not installed

    def traceable(**_kw):
        def decorator(fn):
            return fn

        return decorator


log = structlog.get_logger()

PLAN_SYSTEM_PROMPT = """You are a research planning assistant. Given a research query,
produce a concise execution plan as a JSON array of steps.

Each step must have:
  - "step": step number (int)
  - "tool": one of "search", "summarize", "summarize_text"
  - "input": the argument for the tool (string for search queries, or reference like "#1" to use output of step 1)
  - "reason": why this step is needed (one sentence)

Rules:
  - Always start with 1-2 search steps to gather information
  - End with a summarize step that synthesizes search results
  - Maximum 4 steps total (keep it focused)
  - For summarize step, set input to "#search" to use all search results

Example output for "What is photosynthesis?":
[
  {"step": 1, "tool": "search", "input": "photosynthesis process explained", "reason": "Gather core scientific explanation"},
  {"step": 2, "tool": "search", "input": "photosynthesis light reactions dark reactions", "reason": "Get detailed mechanism"},
  {"step": 3, "tool": "summarize", "input": "#search", "reason": "Synthesize findings into coherent answer"}
]

Return ONLY the JSON array, no other text."""


class ReWOOPlanner:
    def __init__(self, openai_api_key: str, model: str = "gpt-4o-mini"):
        self._client = AsyncOpenAI(api_key=openai_api_key)
        self._model = model

    @traceable(name="rewoo_planner.plan", run_type="llm")
    async def plan(self, query: str) -> list[dict]:
        """
        Generate a research plan for a query.

        Args:
            query: The research question to plan for.

        Returns:
            List of step dicts with keys: step, tool, input, reason.
        """
        log.info("planning", query=query)

        tracer = otel_trace.get_tracer("orchestrator.planner")
        with tracer.start_as_current_span("rewoo_planner.plan") as span:
            span.set_attribute("input.query", query)
            span.set_attribute("input.model", self._model)

            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=500,
                    temperature=0.1,  # low temp = more deterministic plans
                    messages=[
                        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Research query: {query}"},
                    ],
                )
                raw = response.choices[0].message.content.strip()

                # Strip markdown fences if present
                raw = re.sub(r"^```json\s*|^```\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

                plan = json.loads(raw)

                span.set_attribute("output.num_steps", len(plan))
                span.set_attribute("output.plan", json.dumps(plan))
                log.info("plan_created", steps=len(plan), query=query)
                return plan

            except Exception as exc:
                span.set_attribute("error", str(exc))
                log.error("planning_failed", error=str(exc), query=query)
                # Fallback: simple 2-step plan
                return [
                    {
                        "step": 1,
                        "tool": "search",
                        "input": query,
                        "reason": "Direct search fallback",
                    },
                    {
                        "step": 2,
                        "tool": "summarize",
                        "input": "#search",
                        "reason": "Summarize results",
                    },
                ]
