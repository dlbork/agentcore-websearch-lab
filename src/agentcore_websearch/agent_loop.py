"""Hand-rolled agentic tool-calling loop (Option A).

No LangChain, no Strands — a from-scratch loop against Bedrock's converse()
API. Yields a structured event per turn so callers (the SSE endpoint) can
show the model's reasoning live: whether it decides to call the tool, the
tool_use/tool_result pairing, and the final answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from agentcore_websearch.bedrock_client import converse, tool_config_from_mcp_tool
from agentcore_websearch.ledger import Ledger
from agentcore_websearch.raw_explorer import ledgered_call_tool, list_tools

MAX_TURNS = 5


async def run_agent_loop(
    gateway_url: str, ledger: Ledger, prompt: str, max_turns: int = MAX_TURNS
) -> AsyncIterator[dict]:
    tools = await list_tools(gateway_url)
    mcp_tool = tools[0]
    tool_config, alias_to_real_name = tool_config_from_mcp_tool(mcp_tool)

    messages = [{"role": "user", "content": [{"text": prompt}]}]

    for _turn in range(max_turns):
        response = await asyncio.to_thread(converse, messages, tool_config)
        message = response["output"]["message"]
        messages.append(message)

        text_parts = [block["text"] for block in message["content"] if "text" in block]
        if text_parts:
            yield {"kind": "model_text", "text": "\n".join(text_parts)}

        tool_use_blocks = [block["toolUse"] for block in message["content"] if "toolUse" in block]

        if response["stopReason"] != "tool_use" or not tool_use_blocks:
            yield {"kind": "final", "text": "\n".join(text_parts)}
            return

        tool_result_content = []
        for tool_use in tool_use_blocks:
            yield {"kind": "tool_use", "name": tool_use["name"], "input": tool_use["input"]}
            real_name = alias_to_real_name.get(tool_use["name"], tool_use["name"])
            result, cache_hit = await ledgered_call_tool(
                ledger, gateway_url, real_name, tool_use["input"]
            )
            yield {
                "kind": "tool_result",
                "name": tool_use["name"],
                "output": result,
                "cache_hit": cache_hit,
            }
            tool_result_content.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"json": result}],
                    }
                }
            )
        messages.append({"role": "user", "content": tool_result_content})

    yield {"kind": "final", "text": "(max turns reached without a final answer)"}
