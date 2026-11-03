"""Regression tests for defects reproduced on main before this change."""

import json

import pytest

from knowledge_twin.extraction import OpenAICompatibleGraphExtractor
from knowledge_twin.graph import Edge, Entity, KnowledgeGraph
from knowledge_twin.quality import analyze_graph, assert_graph_quality


def extractor(base_url: str = "http://localhost") -> OpenAICompatibleGraphExtractor:
    return OpenAICompatibleGraphExtractor(base_url=base_url, model="graph-model")


def test_entity_with_non_string_description_is_rejected() -> None:
    # Previously accepted: search("none") then matched the literal "None" and
    # SQLite save failed on the NOT NULL description column.
    graph = KnowledgeGraph()
    with pytest.raises(TypeError, match="description"):
        graph.add_entity(Entity("a", "k", "A", None))  # type: ignore[arg-type]
    assert graph.search("none") == []


def test_edge_with_non_string_evidence_is_rejected() -> None:
    # Previously accepted, then analyze_graph crashed with AttributeError.
    graph = KnowledgeGraph()
    graph.add_entity(Entity("a", "k", "A"))
    graph.add_entity(Entity("b", "k", "B"))
    with pytest.raises(TypeError, match="evidence"):
        graph.add_edge(Edge("a", "r", "b", None))  # type: ignore[arg-type]
    assert graph.edges == []


def test_quality_analysis_reports_dangling_edges_instead_of_crashing() -> None:
    graph = KnowledgeGraph()
    graph.add_entity(Entity("a", "k", "A"))
    graph.add_entity(Entity("b", "k", "B"))
    graph.add_edge(Edge("a", "r", "b", "a r b"))
    del graph.entities["b"]  # public attribute mutated directly

    report = analyze_graph(graph)
    assert report.dangling_edge_count == 1
    with pytest.raises(ValueError, match="dangling"):
        assert_graph_quality(graph, allow_orphans=True)


@pytest.mark.parametrize(
    "base_url", ["file:///etc/passwd", "ftp://example.test/x", "localhost:8000", "http://"]
)
def test_extractor_rejects_non_http_base_urls(base_url: str) -> None:
    # urllib.request.urlopen opens file:// URLs, which would read local files.
    with pytest.raises(ValueError, match="http"):
        extractor(base_url)


@pytest.mark.parametrize("raw", ["[]", '"text"', "42", "null"])
def test_extractor_rejects_non_object_json_with_type_error(raw: str) -> None:
    # Previously raised AttributeError from payload.get on a list/str/int.
    with pytest.raises(TypeError, match="object"):
        extractor().parse("source", raw)


def test_endpoint_mention_check_requires_whole_words() -> None:
    # Previously "Ann" was accepted because it is a substring of "Joanne".
    source = "Joanne uses Acme daily."
    payload = {
        "entities": [
            {"id": "ann", "kind": "person", "name": "Ann"},
            {"id": "acme", "kind": "org", "name": "Acme"},
        ],
        "edges": [
            {"source": "ann", "relation": "USES", "target": "acme", "evidence": "Joanne uses Acme"}
        ],
    }
    with pytest.raises(ValueError, match="endpoint entities"):
        extractor().parse(source, json.dumps(payload))
