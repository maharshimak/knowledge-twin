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


def test_graph_load_uses_single_snapshot_transaction(tmp_path):
    import sqlite3
    from unittest.mock import patch

    store = SQLiteGraphStore(tmp_path / "graph.db")
    graph = KnowledgeGraph()
    graph.add_entity(Entity("one", "test", "One", "snapshot"))
    store.save(graph)

    real_connect = sqlite3.connect
    statements = []

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    with patch("knowledge_twin.storage.sqlite3.connect", side_effect=traced_connect):
        restored = store.load()

    assert any(sql.strip().upper() == "BEGIN" for sql in statements)
    assert restored.entities["one"].name == "One"
