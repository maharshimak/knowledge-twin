import pytest

from knowledge_twin.extraction import OpenAICompatibleGraphExtractor


def extractor():
    return OpenAICompatibleGraphExtractor(
        base_url="http://localhost",
        model="graph-model",
    )


def test_graph_extraction_requires_verbatim_evidence():
    source = "MAKMA uses the RAG Engine for retrieval."
    result = extractor().parse(
        source,
        """
        {
          "entities": [
            {"id":"makma","kind":"system","name":"MAKMA","description":""},
            {"id":"rag","kind":"service","name":"RAG Engine","description":""}
          ],
          "edges": [
            {
              "source":"makma",
              "relation":"USES",
              "target":"rag",
              "evidence":"MAKMA uses the RAG Engine for retrieval."
            }
          ]
        }
        """,
    )
    assert result.quality.entity_count == 2
    assert result.quality.edge_count == 1
    assert result.quality.evidence_coverage == 1.0


def test_graph_extraction_rejects_hallucinated_evidence():
    with pytest.raises(ValueError, match="verbatim"):
        extractor().parse(
            "MAKMA uses retrieval.",
            """
            {
              "entities": [
                {"id":"a","kind":"system","name":"MAKMA","description":""},
                {"id":"b","kind":"service","name":"RAG","description":""}
              ],
              "edges": [
                {"source":"a","relation":"USES","target":"b","evidence":"invented evidence"}
              ]
            }
            """,
        )
