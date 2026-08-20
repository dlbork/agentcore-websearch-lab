"""Result types returned by the AgentCore Web Search connector.

AWS's docs describe a result as a knowledge-graph fact when `title`/`url`
come back null, with structured facts packed into `text` instead of a web
snippet. Applied here defensively: across 6 varied factual queries tested
live against this Gateway, every result had a populated `title`/`url` — no
null-title shape was ever observed. classify() still checks for it in case
a query surfaces one; see compare.py for what's actually seen in practice.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    text: str
    published_date: str | None


@dataclass(frozen=True)
class KnowledgeGraphFact:
    text: str
    published_date: str | None


def classify(raw_result: dict) -> WebResult | KnowledgeGraphFact:
    if raw_result.get("title") is None:
        return KnowledgeGraphFact(
            text=raw_result.get("text", ""),
            published_date=raw_result.get("publishedDate"),
        )
    return WebResult(
        title=raw_result["title"],
        url=raw_result.get("url", ""),
        text=raw_result.get("text", ""),
        published_date=raw_result.get("publishedDate"),
    )
