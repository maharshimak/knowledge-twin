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


def test_graph_load_remains_coherent_when_writer_commits_between_reads(tmp_path):
    """In WAL mode, a concurrent replacement must not split an entity/edge snapshot."""
    import sqlite3
    import threading
    from unittest.mock import patch

    store = SQLiteGraphStore(tmp_path / "graph.db")
    initial = KnowledgeGraph()
    initial.add_entity(Entity("a", "test", "Old A", "before"))
    initial.add_entity(Entity("b", "test", "Old B", "before"))
    initial.add_edge(Edge("a", "LINKS", "b", "old relation"))
    store.save(initial)

    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"

    reached_second_read = threading.Event()
    writer_committed = threading.Event()
    real_connect = sqlite3.connect
    outcome = {}

    class CoordinatedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.lstrip().startswith("SELECT source, relation, target, evidence"):
                reached_second_read.set()
                if not writer_committed.wait(timeout=5):
                    raise TimeoutError("writer did not commit between graph SELECTs")
            return super().execute(sql, *args, **kwargs)

    def traced_connect(*args, **kwargs):
        if threading.current_thread().name == "graph-reader":
            kwargs["factory"] = CoordinatedConnection
        return real_connect(*args, **kwargs)

    def read_snapshot():
        try:
            outcome["graph"] = store.load()
        except Exception as error:  # noqa: BLE001 - forward thread failure to test
            outcome["error"] = error

    with patch("knowledge_twin.storage.sqlite3.connect", side_effect=traced_connect):
        reader = threading.Thread(target=read_snapshot, name="graph-reader")
        reader.start()
        try:
            assert reached_second_read.wait(timeout=5)
            updated = KnowledgeGraph()
            updated.add_entity(Entity("new", "test", "New graph", "after"))
            store.save(updated)
        finally:
            writer_committed.set()
            reader.join(timeout=6)

    assert not reader.is_alive()
    assert "error" not in outcome, outcome.get("error")
    snapshot = outcome["graph"]
    assert set(snapshot.entities) == {"a", "b"}
    assert [(e.source, e.target) for e in snapshot.edges] == [("a", "b")]
