from agentcore_websearch.ledger import PRICE_PER_1000_QUERIES_USD, Ledger


def test_cache_miss_then_hit(tmp_path):
    ledger = Ledger(data_dir=tmp_path)

    cached = ledger.get_cached("WebSearchTool", "who is the CEO of Amazon", {})
    assert cached is None

    response = {"results": [{"title": "x", "url": "y", "text": "z", "publishedDate": None}]}
    ledger.record_call("WebSearchTool", "who is the CEO of Amazon", {}, response, cache_hit=False)

    cached = ledger.get_cached("WebSearchTool", "who is the CEO of Amazon", {})
    assert cached == response


def test_totals_only_bills_cache_misses(tmp_path):
    ledger = Ledger(data_dir=tmp_path)
    response = {"results": []}

    ledger.record_call("WebSearchTool", "q1", {}, response, cache_hit=False)
    ledger.record_call("WebSearchTool", "q1", {}, response, cache_hit=True)
    ledger.record_call("WebSearchTool", "q2", {}, response, cache_hit=False)

    totals = ledger.totals()
    assert totals["billed_queries"] == 2
    assert totals["cache_hits"] == 1
    assert totals["cost_usd"] == round(2 * PRICE_PER_1000_QUERIES_USD / 1000, 4)


def test_different_params_are_different_cache_entries(tmp_path):
    ledger = Ledger(data_dir=tmp_path)
    ledger.record_call("WebSearchTool", "q", {"count": 5}, {"a": 1}, cache_hit=False)

    assert ledger.get_cached("WebSearchTool", "q", {"count": 10}) is None
    assert ledger.get_cached("WebSearchTool", "q", {"count": 5}) == {"a": 1}
