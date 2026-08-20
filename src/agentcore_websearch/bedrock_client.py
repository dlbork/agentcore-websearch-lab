"""Thin wrapper over bedrock-runtime converse() with tool-calling support.

Uses amazon.nova-pro-v1:0 rather than Claude: Anthropic models on Bedrock in
this account require a separate "model use case details" form that was
still pending, while Nova is a first-party Amazon model with tool-calling
support and no extra access request. Purely a model swap — the loop
mechanics this project cares about (tool_use/tool_result pairing) are
unaffected by which model reasons over them.
"""

from __future__ import annotations

import re

import boto3
from mcp.types import Tool

MODEL_ID = "amazon.nova-pro-v1:0"
REGION = "us-east-1"

_client = None


def _runtime_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-runtime", region_name=REGION)
    return _client


def _bedrock_safe_tool_name(name: str) -> str:
    """Sanitizes an MCP tool name for Bedrock's toolConfig.

    Discovered live: amazon.nova-pro-v1:0 deterministically fails tool
    calls ("Model produced invalid sequence as part of ToolUse") when the
    tool name contains a run of repeated underscores, e.g. the real MCP
    tool name web-search-tool___WebSearch. Collapsing repeated separators
    to a single underscore fixes it; a hardcoded rename wasn't needed.
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    safe = re.sub(r"_{2,}", "_", safe).strip("_")
    return safe[:64] or "tool"


def tool_config_from_mcp_tool(tool: Tool) -> tuple[dict, dict[str, str]]:
    """Translates a discovered MCP tool (name + inputSchema) into the
    Bedrock Converse toolConfig shape.

    Returns (tool_config, alias_to_real_name) — the alias is what the model
    sees and calls; the caller maps it back to the real MCP tool name when
    actually invoking the tool.
    """
    alias = _bedrock_safe_tool_name(tool.name)
    tool_config = {
        "tools": [
            {
                "toolSpec": {
                    "name": alias,
                    "description": tool.description or "Search the web for current information",
                    "inputSchema": {"json": tool.inputSchema},
                }
            }
        ]
    }
    return tool_config, {alias: tool.name}


def converse(messages: list[dict], tool_config: dict | None = None) -> dict:
    kwargs = {"modelId": MODEL_ID, "messages": messages}
    if tool_config is not None:
        kwargs["toolConfig"] = tool_config
    return _runtime_client().converse(**kwargs)
