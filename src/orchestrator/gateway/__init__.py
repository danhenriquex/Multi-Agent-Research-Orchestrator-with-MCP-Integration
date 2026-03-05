"""
MCP Gateway
-----------
Routes tool calls to MCP servers using FastMCP Client.
Implements dynamic routing + fallback chains.
"""

import json

import structlog
from fastmcp import Client
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()

TOOL_REGISTRY: dict[str, list[tuple[str, str]]] = {
    "search": [
        ("search", "cached_search"),
        ("search", "web_search"),
    ],
    "summarize": [
        ("summarization", "summarize_search_results"),
    ],
    "summarize_text": [
        ("summarization", "summarize_text"),
    ],
}


class MCPGateway:
    def __init__(self, search_url: str, summarization_url: str):
        self._urls = {
            "search": search_url.rstrip("/") + "/mcp",
            "summarization": summarization_url.rstrip("/") + "/mcp",
        }

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        candidates = TOOL_REGISTRY.get(tool_name)
        if not candidates:
            return {"error": f"Unknown tool: {tool_name}"}

        last_error = None
        for server_key, actual_tool in candidates:
            server_url = self._urls.get(server_key, "")
            try:
                result = await self._call_mcp(server_url, actual_tool, arguments)
                log.info("tool_call_success", tool=tool_name, actual_tool=actual_tool)
                return result
            except Exception as exc:
                log.warning(
                    "tool_call_failed", tool=tool_name, actual_tool=actual_tool, error=str(exc)
                )
                last_error = exc

        log.error("all_fallbacks_exhausted", tool=tool_name, error=str(last_error))
        return {
            "error": f"All fallbacks exhausted for '{tool_name}': {last_error}",
            "degraded": True,
        }

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def _call_mcp(self, server_url: str, tool_name: str, arguments: dict) -> dict:
        """Call a tool via FastMCP Client, handling FastMCP 3.x response format."""
        async with Client(server_url) as client:
            result = await client.call_tool(name=tool_name, arguments=arguments)

        # FastMCP 3.x: CallToolResult has .data (parsed dict) and .content (raw TextContent list)
        if hasattr(result, "data") and result.data is not None:
            return result.data

        # Fallback: parse .content[0].text as JSON
        if hasattr(result, "content") and result.content:
            text = (
                result.content[0].text
                if hasattr(result.content[0], "text")
                else str(result.content[0])
            )
            try:
                return json.loads(text)
            except Exception:
                return {"text": text}

        # Last resort: direct list access (older FastMCP versions)
        if isinstance(result, list) and result:
            try:
                return json.loads(result[0].text)
            except Exception:
                return {"text": str(result[0])}

        return {"error": "Empty response from MCP server"}

    async def health_check(self) -> dict[str, bool]:
        results = {}
        for key, url in self._urls.items():
            try:
                async with Client(url) as client:
                    tools = await client.list_tools()
                results[key] = len(tools) > 0
            except Exception as exc:
                log.warning("health_check_failed", server=key, error=str(exc))
                results[key] = False
        return results
