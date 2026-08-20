# AgentCore Web Search Lab

A hands-on lab for Amazon Bedrock AgentCore's Web Search tool: three
different ways to call it (raw MCP, a hand-rolled agentic loop, and
Bedrock's native Responses API), a FastAPI + HTMX UI to poke at each one
live, and a cost ledger so experimenting doesn't rack up a surprise bill.

## Why this exists

AgentCore's Web Search connector is new and thinly documented. The value
here isn't the UI — it's what got learned by actually calling the thing
and writing down what happened instead of what the docs say should happen:

- **`external_web_access` silently degrades.** The API defaults this
  param to `True`, but an IAM identity without
  `bedrock-websearch:ExternalWebAccess` doesn't get an error — Search
  still succeeds, Fetch just 403s, and the model reports it couldn't
  reach the web. Easy to misdiagnose as a model problem.
- **The documented "knowledge graph" result shape never showed up.**
  AWS's docs say a result is a knowledge-graph fact when `title`/`url`
  come back null. Across varied factual queries against a live Gateway,
  every result had both populated. The code still checks for the
  null-title case defensively, but [`compare.py`](src/agentcore_websearch/compare.py)
  reports what was actually observed, not what the docs promise.
- **Tool names with repeated underscores break Nova's tool calling.**
  `amazon.nova-pro-v1:0` deterministically fails ("Model produced invalid
  sequence as part of ToolUse") on MCP tool names like
  `web-search-tool___WebSearch`. Collapsing repeated separators to one
  underscore fixes it — see [`bedrock_client.py`](src/agentcore_websearch/bedrock_client.py).
- **Two integration paths, two different pricing models.** The Gateway's
  Web Search connector bills a flat $7 per 1,000 queries. Bedrock's
  native Web Search tool (Search + Fetch, invoked by the model's own
  tool-calling loop rather than one call per query) bills per-token
  instead. The [ledger](src/agentcore_websearch/ledger.py) tracks them
  separately rather than folding native calls into a per-query dollar
  figure that would misreport cost.
- **Native Web Search only exists on one API surface.** Per AWS's docs
  it's unavailable through `bedrock-runtime`, `Converse`, or
  `InvokeModel` — only through `bedrock-mantle`'s OpenAI-compatible
  Responses API, and only for Bedrock's OpenAI models. See
  [`native_web_search.py`](src/agentcore_websearch/native_web_search.py).

If you're building against AgentCore Gateway or Bedrock's native web
search, this should save you the trial-and-error that produced these
notes.

## What's in the UI

| Page | Demonstrates |
|---|---|
| Gateway Status / Setup | Provisioning an AgentCore Gateway + Web Search connector target, and tearing it down |
| MCP Tool Discovery | Raw `tools/list` against the Gateway |
| Web Search — Raw `tools/call` | Calling the connector directly, unabstracted |
| Knowledge Graph vs. Web Snippet | The `compare.py` empirical check described above, plus a parameter sweep |
| Agentic Tool-Calling Loop | A from-scratch loop against Bedrock's `converse()` API (no LangChain, no Strands), streamed live over SSE |
| Bedrock Native Web Search | The Responses API path, bearer-token auth minted from IAM credentials — no stored API key |
| Query Ledger | Every call made, cached by a hash of `(tool, query, params)`, with running cost totals |

## Running it

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and an AWS
account with Bedrock access to `amazon.nova-pro-v1:0` and
`openai.gpt-5.6-terra` in `us-east-1`.

```bash
uv sync

# Provision the Gateway + Web Search connector (creates the IAM role too)
uv run agentcore-websearch-provision setup

uv run uvicorn agentcore_websearch.app:app --reload
```

Then open `http://127.0.0.1:8000`.

Every call to the Gateway's Web Search connector bills real money ($7 per
1,000 queries) — the ledger caches by query so re-running the same one
while iterating on UI code doesn't re-bill it, but new queries do cost.

Deployment configuration for a specific private host isn't included here
on purpose — this repo is the lab itself, not a deployment guide.
