import pytest

from knowledge_twin.communities import LouvainCommunityDetector
from knowledge_twin.graph import Edge, Entity, KnowledgeGraph


def graph_fixture():
    graph = KnowledgeGraph()
    for entity_id in ("a", "b", "c", "d"):
        graph.add_entity(Entity(entity_id, "system", entity_id.upper()))
    graph.add_edge(Edge("a", "USES", "b", "a uses b"))
    graph.add_edge(Edge("c", "USES", "d", "c uses d"))
    return graph


def test_community_adapter_preserves_internal_evidence():
    detector = LouvainCommunityDetector(
        algorithm=lambda nodes, edges: [{"a", "b"}, {"c", "d"}]
    )
    communities = detector.detect(graph_fixture())
    assert [community.entity_ids for community in communities] == [
        ("a", "b"),
        ("c", "d"),
    ]
    assert communities[0].evidence == ("a uses b",)


def test_community_adapter_rejects_invalid_partition():
    detector = LouvainCommunityDetector(
        algorithm=lambda nodes, edges: [{"a", "b"}, {"b", "c", "d"}]
    )
    with pytest.raises(ValueError, match="disjoint partition"):
        detector.detect(graph_fixture())
