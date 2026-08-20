from agentcore_websearch.models import KnowledgeGraphFact, WebResult, classify


def test_classify_web_result():
    raw = {
        "title": "Example Page",
        "url": "https://example.com",
        "text": "some snippet",
        "publishedDate": "2026-08-01",
    }
    result = classify(raw)
    assert isinstance(result, WebResult)
    assert result.title == "Example Page"
    assert result.url == "https://example.com"


def test_classify_knowledge_graph_fact():
    raw = {
        "title": None,
        "url": None,
        "text": "CEO: Andy Jassy",
        "publishedDate": None,
    }
    result = classify(raw)
    assert isinstance(result, KnowledgeGraphFact)
    assert result.text == "CEO: Andy Jassy"


def test_classify_missing_fields_defaults():
    result = classify({"title": None})
    assert isinstance(result, KnowledgeGraphFact)
    assert result.text == ""
    assert result.published_date is None
