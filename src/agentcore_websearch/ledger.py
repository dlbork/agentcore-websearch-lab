"""Query ledger: cost accounting and a content-addressed response cache.

Every call to the Web Search connector costs money ($7 per 1,000 queries).
The ledger logs each call and caches its raw response by a hash of
(tool_name, query, params), so replaying the same query while iterating on
parsing/rendering code doesn't re-bill it. Only cache misses count toward
the billed query total.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PRICE_PER_1000_QUERIES_USD = 7.00

# AgentCore Gateway's Web Search connector bills a flat $7/1,000 queries and
# is what PRICE_PER_1000_QUERIES_USD models. Bedrock's native Web Search
# tool (see native_web_search.py) bills per-token plus its own Search/Fetch
# pricing, decided by the model's own tool-calling loop rather than one
# call per query -- folding it into the same per-query dollar math would
# misreport cost, so its calls are counted separately and left un-priced.
NATIVE_WEB_SEARCH_TOOL_NAME = "bedrock-native-web-search"


def _cache_key(tool_name: str, query: str, params: dict) -> str:
    payload = json.dumps(
        {"tool_name": tool_name, "query": query, "params": params},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Ledger:
    data_dir: Path = field(default_factory=lambda: Path("data"))

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.cache_dir = self.data_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.data_dir / "ledger.jsonl"
        self.log_path.touch(exist_ok=True)

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def get_cached(self, tool_name: str, query: str, params: dict) -> dict | None:
        path = self._cache_path(_cache_key(tool_name, query, params))
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def record_call(
        self,
        tool_name: str,
        query: str,
        params: dict,
        response: dict,
        cache_hit: bool,
    ) -> None:
        key = _cache_key(tool_name, query, params)
        if not cache_hit:
            self._cache_path(key).write_text(json.dumps(response))
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "tool_name": tool_name,
            "query": query,
            "params": params,
            "cache_hit": cache_hit,
            "response_bytes": len(json.dumps(response)),
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def totals(self) -> dict:
        billed = 0
        cache_hits = 0
        native_calls = 0
        native_cache_hits = 0
        if self.log_path.exists():
            for line in self.log_path.read_text().splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry["tool_name"] == NATIVE_WEB_SEARCH_TOOL_NAME:
                    if entry["cache_hit"]:
                        native_cache_hits += 1
                    else:
                        native_calls += 1
                elif entry["cache_hit"]:
                    cache_hits += 1
                else:
                    billed += 1
        return {
            "billed_queries": billed,
            "cache_hits": cache_hits,
            "cost_usd": round(billed * PRICE_PER_1000_QUERIES_USD / 1000, 4),
            "native_web_search_calls": native_calls,
            "native_web_search_cache_hits": native_cache_hits,
        }
