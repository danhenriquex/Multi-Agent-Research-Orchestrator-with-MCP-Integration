"""
Research Agent
--------------
Executes a ReWOO plan using the MCP Gateway.
Collects results from each step and synthesizes a final answer.

Execution flow:
  1. Receive query
  2. Ask planner for a step-by-step plan
  3. Execute each step via gateway (search or summarize tools)
  4. Collect all search results
  5. Run final summarization across all results
  6. Return structured result with plan + answer + tool call records
"""

import time
import structlog
from openai import AsyncOpenAI

from orchestrator.gateway import MCPGateway
from orchestrator.planner import ReWOOPlanner

log = structlog.get_logger()

SYNTHESIS_PROMPT = """You are a research assistant. Based on the search results and summary below,
write a clear, well-structured answer to the research query.
Be factual, cite key points, and be concise (2-4 paragraphs)."""


class ResearchAgent:
    def __init__(
        self,
        openai_api_key: str,
        search_mcp_url: str,
        summarization_mcp_url: str,
        model: str = "gpt-4o-mini",
    ):
        self._gateway = MCPGateway(
            search_url=search_mcp_url,
            summarization_url=summarization_mcp_url,
        )
        self._planner = ReWOOPlanner(openai_api_key=openai_api_key, model=model)
        self._client = AsyncOpenAI(api_key=openai_api_key)
        self._model = model

    async def run(self, query: str):
        """
        Execute a full research cycle for a query.
        Yields string chunks for streaming, then returns final result dict.

        Args:
            query: The research question.

        Yields:
            str: Progress update chunks for streaming to client.

        Returns (via final yield as dict):
            {
              query, plan, answer, sources,
              tool_calls, duration_ms, search_results
            }
        """
        start = time.time()
        tool_calls = []
        search_results = []

        # ── Step 1: Plan ──────────────────────────────────────────────────────
        yield f"data: 🧠 Planning research steps for: {query}\n\n"
        plan = await self._planner.plan(query)

        plan_text = "\n".join(
            f"  Step {s['step']}: [{s['tool']}] {s['input']} — {s['reason']}"
            for s in plan
        )
        yield f"data: 📋 Plan:\n{plan_text}\n\n"

        # ── Step 2: Execute ───────────────────────────────────────────────────
        for step in plan:
            step_num = step["step"]
            tool = step["tool"]
            inp = step["input"]

            # Resolve "#search" reference to collected search results
            if inp == "#search":
                arguments = {"results": search_results, "query": query}
            else:
                arguments = {"query": inp} if tool == "search" else {"text": inp}

            yield f"data: 🔧 Step {step_num}: {tool}({inp[:60]}...)\n\n" if len(inp) > 60 else f"data: 🔧 Step {step_num}: {tool}({inp})\n\n"

            t0 = time.time()
            result = await self._gateway.call_tool(tool, arguments)
            elapsed = round((time.time() - t0) * 1000)

            tool_calls.append({
                "step": step_num,
                "tool": tool,
                "input": inp,
                "duration_ms": elapsed,
                "degraded": result.get("degraded", False),
            })

            # Accumulate search results for later summarization
            if tool == "search" and "results" in result:
                search_results.extend(result["results"])
                yield f"data: ✅ Found {len(result['results'])} results via {result.get('backend', 'unknown')} ({elapsed}ms)\n\n"

            elif tool in ("summarize", "summarize_text"):
                summary = result.get("summary", "")
                sources = result.get("sources", [])
                yield f"data: ✅ Summarized {result.get('input_tokens', 0)} tokens ({elapsed}ms)\n\n"

        # ── Step 3: Final synthesis ───────────────────────────────────────────
        yield "data: 🔬 Synthesizing final answer...\n\n"

        # Use the summary from the last summarize step if available,
        # otherwise do a direct synthesis pass with the LLM
        final_answer = summary if "summary" in locals() and summary else await self._synthesize(
            query, search_results
        )

        duration_ms = round((time.time() - start) * 1000)
        yield f"data: ✨ Done in {duration_ms}ms\n\n"

        yield {
            "query": query,
            "plan": plan,
            "answer": final_answer,
            "sources": sources if "sources" in locals() else [],
            "search_results": search_results,
            "tool_calls": tool_calls,
            "duration_ms": duration_ms,
        }

    async def _synthesize(self, query: str, search_results: list[dict]) -> str:
        """Direct LLM synthesis when summarization MCP is unavailable."""
        if not search_results:
            return "No search results found to answer the query."

        context = "\n\n".join(
            f"[{i+1}] {r.get('title', '')}\n{r.get('snippet', '')}"
            for i, r in enumerate(search_results[:5])
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=1000,
            messages=[
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {"role": "user", "content": f"Query: {query}\n\nSearch Results:\n{context}"},
            ],
        )
        return response.choices[0].message.content

    async def close(self):
        await self._gateway.close()