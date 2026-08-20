"""Bedrock's built-in Web Search tool, via the Responses API on bedrock-mantle.

A genuinely separate integration path from the rest of this lab: no
AgentCore Gateway, no MCP, no Converse toolConfig. Per AWS's docs, Web
Search "is not available through bedrock-runtime, Converse, or
InvokeModel" -- it only exists on bedrock-mantle's OpenAI-compatible
Responses API, and only for Bedrock's OpenAI GPT models (this lab uses
openai.gpt-5.6-terra).

Auth is a short-lived bearer token minted from the process's own IAM
credentials via aws-bedrock-token-generator -- no API key stored anywhere.

external_web_access defaults to False here on purpose: the parameter
defaults to True in the API, but AmazonBedrockFullAccess (what this lab's
IAM identity holds) does not grant bedrock-websearch:ExternalWebAccess. A
True request from this identity doesn't error -- Search still succeeds,
Fetch silently 403s, and the model reports it couldn't reach the external
web. See TOOL_NAME's log entries on /costs for what was actually observed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from aws_bedrock_token_generator import provide_token
from openai import OpenAI

from agentcore_websearch.ledger import NATIVE_WEB_SEARCH_TOOL_NAME as TOOL_NAME
from agentcore_websearch.ledger import Ledger

REGION = "us-east-1"
MODEL_ID = "openai.gpt-5.6-terra"
BASE_URL = f"https://bedrock-mantle.{REGION}.api.aws/openai/v1"


@dataclass(frozen=True)
class Citation:
    title: str
    url: str
    start_index: int
    end_index: int


@dataclass(frozen=True)
class NativeSearchResult:
    answer_text: str
    citations: list[Citation]
    external_web_access: bool
    raw: dict
    cache_hit: bool


def _client() -> OpenAI:
    token = provide_token(region=REGION)
    return OpenAI(api_key=token, base_url=BASE_URL)


def extract_citations(raw: dict) -> list[Citation]:
    """Pulls url_citation annotations out of a raw Responses API payload.

    Operates on the plain dict (per AWS's documented JSON shape:
    output[].content[].annotations[]) rather than SDK response objects, so
    it's testable against a sample payload with no live call or SDK
    dependency -- see tests/test_native_web_search.py.
    """
    citations = []
    for item in raw.get("output") or []:
        if item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if block.get("type") != "output_text":
                continue
            for ann in block.get("annotations") or []:
                if ann.get("type") != "url_citation":
                    continue
                citations.append(
                    Citation(
                        title=ann["title"],
                        url=ann["url"],
                        start_index=ann["start_index"],
                        end_index=ann["end_index"],
                    )
                )
    return citations


def search(
    ledger: Ledger, prompt: str, external_web_access: bool = False
) -> NativeSearchResult:
    """Runs one Web Search-grounded turn.

    Cached by (prompt, external_web_access) like the rest of this lab, so
    replaying a query while iterating on rendering doesn't re-bill it.
    """
    params = {"external_web_access": external_web_access}
    cached = ledger.get_cached(TOOL_NAME, prompt, params)
    if cached is not None:
        ledger.record_call(TOOL_NAME, prompt, params, cached, cache_hit=True)
        return NativeSearchResult(
            answer_text=cached["answer_text"],
            citations=[Citation(**c) for c in cached["citations"]],
            external_web_access=external_web_access,
            raw=cached["raw"],
            cache_hit=True,
        )

    client = _client()
    response = client.responses.create(
        model=MODEL_ID,
        input=prompt,
        tools=[{"type": "web_search", "external_web_access": external_web_access}],
    )

    raw = json.loads(response.model_dump_json())
    citations = extract_citations(raw)
    payload = {
        "answer_text": response.output_text,
        "citations": [
            {"title": c.title, "url": c.url, "start_index": c.start_index, "end_index": c.end_index}
            for c in citations
        ],
        "raw": raw,
    }
    ledger.record_call(TOOL_NAME, prompt, params, payload, cache_hit=False)

    return NativeSearchResult(
        answer_text=response.output_text,
        citations=citations,
        external_web_access=external_web_access,
        raw=raw,
        cache_hit=False,
    )
