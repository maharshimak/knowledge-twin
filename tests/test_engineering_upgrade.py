import pytest

from knowledge_twin.graph import Edge, Entity, KnowledgeGraph


def test_directed_paths_and_duplicate_ids():
    g = KnowledgeGraph()
    for key in "abc":
        g.add_entity(Entity(key, "tool", key))
    with pytest.raises(ValueError):
        g.add_entity(Entity("a", "tool", "replacement"))
    g.add_edge(Edge("a", "uses", "b", "source"))
    g.add_edge(Edge("b", "uses", "c", "source"))
    assert len(g.shortest_path("a", "c")) == 2
    assert g.shortest_path("c", "a") is None
    assert g.shortest_path("a", "a") == []
    with pytest.raises(ValueError):
        g.neighborhood("a", 1.5)
