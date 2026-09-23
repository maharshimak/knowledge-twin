from knowledge_twin.graph import Edge, Entity, KnowledgeGraph
from knowledge_twin.storage import SQLiteGraphStore


def test_sqlite_graph_store_round_trips_entities_edges_and_evidence(tmp_path) -> None:
    graph = KnowledgeGraph()
    graph.add_entity(Entity("rag", "technology", "RAG", "retrieval augmented generation"))
    graph.add_entity(Entity("db", "technology", "Vector DB", "semantic index"))
    graph.add_edge(Edge("rag", "USES", "db", "Architecture document section 2"))

    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.save(graph)
    restored = store.load()

    assert restored.entities["rag"].description == "retrieval augmented generation"
    assert restored.edges == [
        Edge("rag", "USES", "db", "Architecture document section 2")
    ]
    assert restored.shortest_path("rag", "db") == restored.edges
