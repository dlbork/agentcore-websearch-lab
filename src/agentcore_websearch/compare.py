"""Factual-vs-open-ended comparison, and a sweep over the discovered
WebSearchTool parameters.

Built as an honest empirical check, not a guaranteed knowledge-graph split:
AWS's docs describe knowledge-graph hits as coming back with `title`/`url`
null, but that was never observed across 6 varied factual queries tested
live against this Gateway (see models.py). classify() still applies the
null-title rule defensively; this module reports what it actually sees.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentcore_websearch.ledger import Ledger
from agentcore_websearch.models import KnowledgeGraphFact, WebResult, classify
from agentcore_websearch.raw_explorer import ledgered_call_tool, list_tools


@dataclass
class QueryComparison:
    label: str
    query: str
    results: list[WebResult | KnowledgeGraphFact]
    cache_hit: bool

    @property
    def knowledge_graph_count(self) -> int:
        return sum(1 for r in self.results if isinstance(r, KnowledgeGraphFact))

    @property
    def web_count(self) -> int:
        return sum(1 for r in self.results if isinstance(r, WebResult))


async def _run_query(
    ledger: Ledger, gateway_url: str, tool_name: str, label: str, query: str, max_results: int
) -> QueryComparison:
    args = {"query": query, "maxResults": max_results}
    response, cache_hit = await ledgered_call_tool(ledger, gateway_url, tool_name, args)
    results = [classify(r) for r in response.get("results", [])]
    return QueryComparison(label=label, query=query, results=results, cache_hit=cache_hit)


async def compare_factual_vs_open_ended(
    ledger: Ledger, gateway_url: str, factual_query: str, open_ended_query: str
) -> list[QueryComparison]:
    tools = await list_tools(gateway_url)
    tool_name = tools[0].name
    factual = await _run_query(ledger, gateway_url, tool_name, "factual", factual_query, 5)
    open_ended = await _run_query(
        ledger, gateway_url, tool_name, "open-ended", open_ended_query, 5
    )
    return [factual, open_ended]


async def sweep_max_results(
    ledger: Ledger, gateway_url: str, query: str, values: tuple[int, ...] = (1, 5, 10, 25)
) -> list[QueryComparison]:
    """Varies the only other documented parameter (`maxResults`, 1-25) one
    value at a time, logging each request/response pair via the ledger."""
    tools = await list_tools(gateway_url)
    tool_name = tools[0].name
    return [
        await _run_query(ledger, gateway_url, tool_name, f"maxResults={n}", query, n)
        for n in values
    ]
