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


def test_loaded_graph_cannot_overwrite_newer_writer_changes(tmp_path):
    import pytest

    path = tmp_path / "graph.db"
    first = SQLiteGraphStore(path)
    second = SQLiteGraphStore(path)
    original = KnowledgeGraph()
    original.add_entity(Entity("seed", "test", "Seed"))
    first.save(original)

    first_copy = first.load()
    stale_copy = second.load()
    first_copy.add_entity(Entity("first", "test", "First writer"))
    first.save(first_copy)

    stale_copy.add_entity(Entity("stale", "test", "Old writer"))
    with pytest.raises(RuntimeError, match="changed since it was loaded"):
        second.save(stale_copy)

    restored = first.load()
    assert set(restored.entities) == {"seed", "first"}
    assert "stale" not in restored.entities

    # The writer can resolve the conflict by reloading the latest revision.
    corrected = second.load()
    corrected.add_entity(Entity("second", "test", "Second writer"))
    second.save(corrected)
    assert set(first.load().entities) == {"seed", "first", "second"}


def test_fresh_graph_replacement_remains_backwards_compatible(tmp_path):
    import sqlite3

    db = tmp_path / "graph.db"
    store = SQLiteGraphStore(db)
    original = KnowledgeGraph()
    original.add_entity(Entity("old", "test", "Old"))
    store.save(original)

    replacement = KnowledgeGraph()
    replacement.add_entity(Entity("new", "test", "New"))
    store.save(replacement)

    assert set(store.load().entities) == {"new"}
    with sqlite3.connect(db) as connection:
        revision = connection.execute(
            "SELECT version FROM graph_meta WHERE id = 1"
        ).fetchone()[0]
    assert revision == 2


def test_failed_graph_save_does_not_advance_revision(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "graph.db"
    store = SQLiteGraphStore(path)
    initial = KnowledgeGraph()
    initial.add_entity(Entity("a", "test", "A"))
    store.save(initial)
    loaded = store.load()

    # Force an integrity error *after* clearing the original rows; the
    # database transaction must roll back the graph and version together.
    loaded.entities["bad"] = Entity("a", "test", "Duplicate primary key")
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        store.save(loaded)

    persisted = store.load()
    assert set(persisted.entities) == {"a"}
    assert persisted.entities["a"].name == "A"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT version FROM graph_meta WHERE id = 1"
        ).fetchone()[0] == 1
