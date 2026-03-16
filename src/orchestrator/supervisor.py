"""
Supervisor Agent
-----------------
Orchestrates the full research pipeline using A2A calls to peer agents.

OLD architecture (MCP-only):
  Supervisor → MCPGateway → search-mcp  (direct tool call)
  Supervisor → MCPGateway → summarization-mcp

NEW architecture (A2A + MCP):
  Supervisor ─A2A→ SearchAgent    ─MCP→ search-mcp
  Supervisor ─A2A→ SummarizeAgent ─MCP→ summarization-mcp
  Supervisor ─A2A→ FactCheckAgent ─MCP→ knowledge-mcp

The Supervisor does NOT know about MCP — it only speaks A2A.
Each specialist agent privately manages its own MCP connection.

Execution flow:
  1. ReWOO planner produces a step list
  2. Supervisor calls SearchAgent via A2A (1–2 rounds)
  3. Supervisor calls SummarizeAgent via A2A with search results
  4. Supervisor calls FactCheckAgent via A2A with the draft summary
  5. If confidence is too low, Supervisor can request a re-search (self-loop)
  6. Return final result with verification metadata
"""

import time

import structlog

from a2a.client import A2AClient
from a2a.models import A2AMessage
from orchestrator.planner import ReWOOPlanner

log = structlog.get_logger()

# Confidence below which the Supervisor requests a second search pass
RECHECK_THRESHOLD = 0.50


class SupervisorAgent:
    def __init__(
        self,
        openai_api_key: str,
        a2a_registry: dict[str, str],
        model: str = "gpt-4o-mini",
    ):
        """
        Args:
            openai_api_key: For the ReWOO planner.
            a2a_registry:   Map of agent_name → base_url.
                            e.g. {
                              "search":     "http://search-agent:8010",
                              "summarize":  "http://summarize-agent:8011",
                              "fact_check": "http://fact-check-agent:8012",
                            }
            model:          LLM model for planning.
        """
        self._a2a = A2AClient(registry=a2a_registry)
        self._planner = ReWOOPlanner(openai_api_key=openai_api_key, model=model)
        self._model = model

    async def run(self, query: str, session_id: str = ""):
        """
        Execute a full A2A-orchestrated research cycle.

        Yields str chunks for streaming, then a final dict result.
        """
        start = time.time()
        tool_calls: list[dict] = []
        search_results: list[dict] = []
        context = {"session_id": session_id, "query": query}

        # ── Step 1: Plan ──────────────────────────────────────────────────────
        yield f"data: 🧠 Planning research steps for: {query}\n\n"
        plan = await self._planner.plan(query)
        plan_text = "\n".join(
            f"  Step {s['step']}: [{s['tool']}] {s['input']} — {s['reason']}" for s in plan
        )
        yield f"data: 📋 Plan:\n{plan_text}\n\n"

        # ── Step 2: Execute plan via A2A ──────────────────────────────────────
        summary = ""
        sources: list[dict] = []

        for step in plan:
            step_num = step["step"]
            tool = step["tool"]
            inp = step["input"]

            if tool == "search":
                yield f"data: 🔍 Step {step_num}: SearchAgent ← '{inp[:60]}'\n\n"

                resp = await self._a2a.call(
                    "search",
                    A2AMessage(
                        sender="supervisor",
                        receiver="search",
                        task="search",
                        payload={"query": inp, "max_results": 5},
                        context=context,
                    ),
                )

                tool_calls.append(
                    {
                        "step": step_num,
                        "agent": "search",
                        "task": "search",
                        "input": inp,
                        "duration_ms": resp.duration_ms,
                        "status": resp.status,
                        "protocol": "a2a",
                    }
                )

                if resp.status == "ok":
                    results = resp.result.get("results", [])
                    search_results.extend(results)
                    yield f"data: ✅ SearchAgent → {len(results)} results ({resp.duration_ms}ms)\n\n"
                else:
                    yield f"data: ⚠️ SearchAgent error: {resp.error}\n\n"

            elif tool in ("summarize", "summarize_text"):
                yield f"data: 📝 Step {step_num}: SummarizeAgent ← {len(search_results)} results\n\n"

                resp = await self._a2a.call(
                    "summarize",
                    A2AMessage(
                        sender="supervisor",
                        receiver="summarize",
                        task="summarize",
                        payload={"query": query, "results": search_results},
                        context=context,
                    ),
                )

                tool_calls.append(
                    {
                        "step": step_num,
                        "agent": "summarize",
                        "task": "summarize",
                        "input": f"{len(search_results)} results",
                        "duration_ms": resp.duration_ms,
                        "status": resp.status,
                        "protocol": "a2a",
                    }
                )

                if resp.status == "ok":
                    summary = resp.result.get("summary", "")
                    sources = resp.result.get("sources", [])
                    yield f"data: ✅ SummarizeAgent → {resp.result.get('input_tokens', 0)} tokens ({resp.duration_ms}ms)\n\n"
                else:
                    yield f"data: ⚠️ SummarizeAgent error: {resp.error}\n\n"

        # ── Step 3: Fact-check via A2A (peer collaboration) ───────────────────
        yield "data: 🔎 FactCheckAgent verifying summary...\n\n"

        fact_resp = await self._a2a.call(
            "fact_check",
            A2AMessage(
                sender="supervisor",
                receiver="fact_check",
                task="fact_check",
                payload={"summary": summary, "query": query, "sources": sources},
                context=context,
            ),
        )

        tool_calls.append(
            {
                "step": len(plan) + 1,
                "agent": "fact_check",
                "task": "fact_check",
                "input": "draft summary",
                "duration_ms": fact_resp.duration_ms,
                "status": fact_resp.status,
                "protocol": "a2a",
            }
        )

        verification: dict = {}
        if fact_resp.status == "ok":
            verification = fact_resp.result
            confidence = verification.get("confidence") or 0.0
            verified = verification.get("verified", False)
            flags = verification.get("flags", [])

            yield (
                f"data: {'✅' if verified else '⚠️'} FactCheckAgent → "
                f"confidence={confidence:.0%} verified={verified} "
                f"flags={len(flags)} "
                f"({fact_resp.duration_ms}ms)\n\n"
            )

            # ── Self-healing loop: if confidence too low, re-search ───────────
            if (
                confidence is not None
                and confidence < RECHECK_THRESHOLD
                and not verification.get("degraded")
            ):
                yield "data: 🔄 Low confidence — requesting additional search pass...\n\n"

                recheck_resp = await self._a2a.call(
                    "search",
                    A2AMessage(
                        sender="supervisor",
                        receiver="search",
                        task="search",
                        payload={
                            "query": f"{query} fact check additional sources",
                            "max_results": 3,
                        },
                        context={**context, "recheck": True},
                    ),
                )

                if recheck_resp.status == "ok":
                    extra = recheck_resp.result.get("results", [])
                    search_results.extend(extra)
                    yield f"data: ✅ Re-search → {len(extra)} additional results\n\n"
                    tool_calls.append(
                        {
                            "step": "recheck",
                            "agent": "search",
                            "task": "search",
                            "input": "recheck query",
                            "duration_ms": recheck_resp.duration_ms,
                            "status": recheck_resp.status,
                            "protocol": "a2a",
                        }
                    )
        else:
            yield f"data: ⚠️ FactCheckAgent unavailable: {fact_resp.error} (continuing)\n\n"

        # ── Step 4: Finalize ──────────────────────────────────────────────────
        if not summary:
            summary = "Research could not be completed — no summary generated."

        duration_ms = round((time.time() - start) * 1000)
        yield f"data: ✨ Done in {duration_ms}ms\n\n"

        yield {
            "query": query,
            "plan": plan,
            "answer": summary,
            "sources": sources,
            "search_results": search_results,
            "tool_calls": tool_calls,
            "verification": verification,
            "duration_ms": duration_ms,
        }

    async def health_check(self) -> dict[str, bool]:
        return await self._a2a.health_check()
