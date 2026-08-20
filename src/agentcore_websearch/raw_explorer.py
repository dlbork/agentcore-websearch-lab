"""Raw MCP tools/list + tools/call against the Gateway's Web Search target.

Deliberately the most literal layer in this project: no response parsing,
no classification, just what the wire actually says. `models.classify()`
and `compare.py` build on top of this once the shape is known.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp.types import Tool

from agentcore_websearch.ledger import Ledger
from agentcore_websearch.transport import gateway_session


async def list_tools(gateway_url: str) -> list[Tool]:
    async with gateway_session(gateway_url) as session:
        result = await session.list_tools()
        return result.tools


async def call_tool(gateway_url: str, tool_name: str, arguments: dict) -> dict:
    """Calls the named tool and returns its parsed JSON payload.

    AgentCore Web Search returns its payload as a JSON string inside the
    first text content block of the MCP CallToolResult.
    """
    async with gateway_session(gateway_url) as session:
        result = await session.call_tool(tool_name, arguments)
        if result.isError:
            raise RuntimeError(f"tool call error: {result.content}")
        if result.structuredContent is not None:
            return result.structuredContent
        for block in result.content:
            if block.type == "text":
                return json.loads(block.text)
        raise RuntimeError(f"no text content in tool result: {result.content}")


async def ledgered_call_tool(
    ledger: Ledger, gateway_url: str, tool_name: str, arguments: dict
) -> tuple[dict, bool]:
    """call_tool(), but served from the ledger's cache on a repeat query.

    Returns (response, cache_hit). Only cache misses count toward the
    billed $7/1,000-query total.
    """
    query = arguments.get("query", "")
    cached = ledger.get_cached(tool_name, query, arguments)
    if cached is not None:
        ledger.record_call(tool_name, query, arguments, cached, cache_hit=True)
        return cached, True

    response = await call_tool(gateway_url, tool_name, arguments)
    ledger.record_call(tool_name, query, arguments, response, cache_hit=False)
    return response, False


def _tool_summary(tool: Tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.inputSchema,
    }


async def _main() -> None:
    from agentcore_websearch.provisioning import status

    gw = status()
    if not gw or not gw.get("gateway_url"):
        print("no gateway provisioned yet - run: agentcore-websearch-provision setup")
        sys.exit(1)
    gateway_url = gw["gateway_url"]

    if len(sys.argv) > 1 and sys.argv[1] == "call":
        query = sys.argv[2] if len(sys.argv) > 2 else "latest AWS re:Invent announcements"
        tools = await list_tools(gateway_url)
        tool_name = tools[0].name
        response = await call_tool(gateway_url, tool_name, {"query": query})
        print(json.dumps(response, indent=2))
    else:
        tools = await list_tools(gateway_url)
        print(json.dumps([_tool_summary(t) for t in tools], indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
