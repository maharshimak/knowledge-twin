import pytest

from knowledge_twin.graph import Edge, Entity, KnowledgeGraph
from knowledge_twin.quality import analyze_graph, assert_graph_quality


def test_graph_quality_reports_evidence_and_connectivity() -> None:
    graph = KnowledgeGraph()
    graph.add_entity(Entity("a", "person", "A"))
    graph.add_entity(Entity("b", "system", "B"))
    graph.add_edge(Edge("a", "uses", "b", evidence="source-1"))

    report = assert_graph_quality(graph)
    assert report.evidence_coverage == pytest.approx(1.0)
    assert report.connected_components == 1
    assert report.orphan_count == 0


def test_graph_quality_rejects_orphans_and_duplicates() -> None:
    graph = KnowledgeGraph()
    for entity_id in ("a", "b", "c"):
        graph.add_entity(Entity(entity_id, "node", entity_id.upper()))
    graph.add_edge(Edge("a", "links", "b"))
    graph.add_edge(Edge("a", "links", "b"))

    report = analyze_graph(graph)
    assert report.orphan_count == 1
    assert report.duplicate_edge_count == 1
    with pytest.raises(ValueError, match="Graph quality gate failed"):
        assert_graph_quality(graph)
