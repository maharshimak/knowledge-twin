from knowledge_twin.graph import Edge, Entity, KnowledgeGraph


def test_graph_neighborhood_and_search() -> None:
    graph = KnowledgeGraph()
    graph.add_entity(Entity("a", "technology", "RAG", "retrieval augmented generation"))
    graph.add_entity(Entity("b", "technology", "Vector DB", "semantic search database"))
    graph.add_edge(Edge("a", "USES", "b", "RAG retrieves from vector stores"))
    assert graph.neighborhood("a") == {"a", "b"}
    assert graph.search("semantic")[0].id == "b"
