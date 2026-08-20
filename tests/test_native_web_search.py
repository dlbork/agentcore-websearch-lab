from agentcore_websearch.native_web_search import Citation, extract_citations


def test_extract_citations_from_documented_shape():
    # Shape per AWS's Web Search docs: output[].content[].annotations[]
    raw = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "EKS added rollbacks. (aws.amazon.com)",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "Upgrade Amazon EKS clusters with confidence",
                                "url": "https://aws.amazon.com/blogs/aws/eks-rollbacks/",
                                "start_index": 0,
                                "end_index": 20,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    citations = extract_citations(raw)
    assert citations == [
        Citation(
            title="Upgrade Amazon EKS clusters with confidence",
            url="https://aws.amazon.com/blogs/aws/eks-rollbacks/",
            start_index=0,
            end_index=20,
        )
    ]


def test_extract_citations_ignores_non_url_citation_annotations():
    raw = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "hi",
                        "annotations": [{"type": "file_citation"}],
                    }
                ],
            }
        ]
    }
    assert extract_citations(raw) == []


def test_extract_citations_no_output():
    assert extract_citations({}) == []


def test_extract_citations_skips_non_message_items():
    raw = {"output": [{"type": "reasoning", "content": []}]}
    assert extract_citations(raw) == []
