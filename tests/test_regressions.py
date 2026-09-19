import pytest

from knowledge_twin.graph import Edge, Entity, KnowledgeGraph


def test_cycle_traversal_and_unknown_start():
    g = KnowledgeGraph()
    for name in ("a", "b", "c"):
        g.add_entity(Entity(name, "concept", name))
    g.add_edge(Edge("a", "uses", "b"))
    g.add_edge(Edge("b", "uses", "a"))
    g.add_edge(Edge("b", "uses", "c"))
    assert g.neighborhood("a", 1) == {"a", "b"}
    assert g.neighborhood("a", 10) == {"a", "b", "c"}
    with pytest.raises(ValueError):
        g.neighborhood("missing")
    with pytest.raises(ValueError):
        g.neighborhood("a", -1)
