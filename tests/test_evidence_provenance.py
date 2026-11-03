import hashlib
import json
import sqlite3

import pytest

from knowledge_twin.extraction import OpenAICompatibleGraphExtractor
from knowledge_twin.graph import Edge, Entity, EvidenceSpan, KnowledgeGraph
from knowledge_twin.serialization import graph_from_dict, graph_to_dict
from knowledge_twin.storage import SQLiteGraphStore

SOURCE = "Synthetic memo. Alice works at Acme Corp. Acme Corp uses Vector DB."


def make_graph() -> KnowledgeGraph:
    graph = KnowledgeGraph()
    graph.add_entity(Entity("alice", "person", "Alice"))
    graph.add_entity(Entity("acme", "org", "Acme Corp"))
    graph.add_entity(Entity("beta", "org", "Beta Ltd"))
    graph.add_entity(Entity("vdb", "system", "Vector DB"))
    return graph


def span_of(quote: str, doc: str = "memo-1") -> EvidenceSpan:
    start = SOURCE.index(quote)
    return EvidenceSpan.from_source(doc, SOURCE, start, start + len(quote))


def extracted(source: str, relation: str, target: str, quote: str) -> Edge:
    provenance = span_of(quote)
    return Edge(source, relation, target, provenance.quote, "extracted", provenance)


def test_evidence_span_hashes_the_whole_source_and_verifies() -> None:
    provenance = span_of("Alice works at Acme Corp.")
    assert provenance.source_sha256 == hashlib.sha256(SOURCE.encode("utf-8")).hexdigest()
    assert provenance.verify(SOURCE)
    assert not provenance.verify(SOURCE + " tampered")
    assert not provenance.verify(SOURCE.replace("Alice", "Alyce"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"document_id": " "},
        {"start": -1},
        {"end": 3, "start": 3},
        {"source_sha256": "A" * 64},
        {"source_sha256": "abc"},
        {"quote": "wrong length"},
        {"start": True},
    ],
)
def test_evidence_span_rejects_malformed_values(kwargs: dict) -> None:
    values = {
        "document_id": "d",
        "start": 0,
        "end": 5,
        "source_sha256": "0" * 64,
        "quote": "Alice",
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        EvidenceSpan(**values)


def test_extracted_edge_without_provenance_is_rejected() -> None:
    graph = make_graph()
    with pytest.raises(ValueError, match="attributable source evidence"):
        graph.add_edge(Edge("alice", "WORKS_AT", "acme", "Alice works at Acme Corp.", "extracted"))
    assert graph.edges == []


def test_extracted_edge_evidence_must_match_quote_and_mention_endpoints() -> None:
    graph = make_graph()
    provenance = span_of("Alice works at Acme Corp.")
    with pytest.raises(ValueError, match="provenance quote"):
        graph.add_edge(Edge("alice", "WORKS_AT", "acme", "paraphrase", "extracted", provenance))
    # Re-pointing an extracted edge to an entity its evidence never mentions fails.
    with pytest.raises(ValueError, match="endpoint entities"):
        graph.add_edge(Edge("alice", "WORKS_AT", "beta", provenance.quote, "extracted", provenance))
    graph.add_edge(Edge("alice", "WORKS_AT", "acme", provenance.quote, "extracted", provenance))
    assert len(graph.edges) == 1


def test_human_edges_cannot_carry_extraction_provenance() -> None:
    graph = make_graph()
    provenance = span_of("Alice works at Acme Corp.")
    with pytest.raises(ValueError, match="must not carry extraction provenance"):
        graph.add_edge(Edge("alice", "WORKS_AT", "acme", "reviewer note", "human", provenance))
    with pytest.raises(ValueError, match="attribution note"):
        graph.add_edge(Edge("alice", "WORKS_AT", "acme", "  ", "human"))
    with pytest.raises(ValueError, match="origin"):
        graph.add_edge(Edge("alice", "WORKS_AT", "acme", "x", "model"))


def test_human_correction_does_not_inherit_extraction_evidence() -> None:
    graph = make_graph()
    original = extracted("alice", "WORKS_AT", "acme", "Alice works at Acme Corp.")
    graph.add_edge(original)

    corrected = graph.correct_edge(original, target="beta", note="HR record review 2026-10")

    assert corrected.origin == "human"
    assert corrected.provenance is None
    assert corrected.evidence == "HR record review 2026-10"
    assert graph.edges == [corrected]
    assert graph.adj["alice"] == [corrected]
    assert graph.retracted_edges == [original]


def test_failed_correction_leaves_graph_unchanged() -> None:
    graph = make_graph()
    original = extracted("alice", "WORKS_AT", "acme", "Alice works at Acme Corp.")
    graph.add_edge(original)
    with pytest.raises(ValueError, match="attribution note"):
        graph.correct_edge(original, target="beta", note="")
    with pytest.raises(ValueError, match="endpoints"):
        graph.correct_edge(original, target="missing", note="x")
    assert graph.edges == [original]
    assert graph.retracted_edges == []


def test_serialization_round_trip_preserves_origin_provenance_and_retractions() -> None:
    graph = make_graph()
    original = extracted("alice", "WORKS_AT", "acme", "Alice works at Acme Corp.")
    graph.add_edge(original)
    graph.add_edge(extracted("acme", "USES", "vdb", "Acme Corp uses Vector DB."))
    graph.correct_edge(original, target="beta", note="reviewer")

    payload = json.loads(json.dumps(graph_to_dict(graph)))
    restored = graph_from_dict(payload)

    assert restored.edges == graph.edges
    assert restored.retracted_edges == graph.retracted_edges
    assert graph_to_dict(restored) == payload


def test_graph_from_dict_enforces_evidence_policy() -> None:
    payload = graph_to_dict(make_graph())
    payload["edges"] = [
        {"source": "alice", "relation": "WORKS_AT", "target": "acme", "origin": "extracted"}
    ]
    with pytest.raises(ValueError, match="attributable"):
        graph_from_dict(payload)


def test_sqlite_round_trip_preserves_provenance_and_retractions(tmp_path) -> None:
    graph = make_graph()
    original = extracted("alice", "WORKS_AT", "acme", "Alice works at Acme Corp.")
    graph.add_edge(original)
    graph.add_edge(extracted("acme", "USES", "vdb", "Acme Corp uses Vector DB."))
    graph.correct_edge(original, target="beta", note="reviewer")

    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.save(graph)
    restored = store.load()

    assert restored.edges == graph.edges
    assert restored.retracted_edges == [original]
    assert restored.edges[0].provenance.verify(SOURCE)


def test_sqlite_store_migrates_legacy_edge_table(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE entities (id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                                   name TEXT NOT NULL, description TEXT NOT NULL);
            CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                                relation TEXT NOT NULL, target TEXT NOT NULL,
                                evidence TEXT NOT NULL);
            INSERT INTO entities VALUES ('a', 'k', 'A', ''), ('b', 'k', 'B', '');
            INSERT INTO edges(source, relation, target, evidence) VALUES ('a', 'R', 'b', 'old');
            """
        )
    connection.close()

    restored = SQLiteGraphStore(path).load()
    assert restored.edges == [Edge("a", "R", "b", "old", "unspecified", None)]


def test_model_extractor_attaches_span_provenance() -> None:
    extractor = OpenAICompatibleGraphExtractor(base_url="http://localhost", model="m")
    payload = {
        "entities": [
            {"id": "acme", "kind": "org", "name": "Acme Corp"},
            {"id": "vdb", "kind": "system", "name": "Vector DB"},
        ],
        "edges": [
            {
                "source": "acme",
                "relation": "USES",
                "target": "vdb",
                "evidence": "acme corp uses vector db",
            }
        ],
    }
    result = extractor.parse(SOURCE, json.dumps(payload), document_id="memo-1")
    edge = result.graph.edges[0]
    assert edge.origin == "extracted"
    assert edge.provenance.document_id == "memo-1"
    # The stored evidence is the exact source slice, not the model's casing.
    assert edge.evidence == "Acme Corp uses Vector DB"
    assert edge.provenance.verify(SOURCE)

    default_doc = extractor.parse(SOURCE, json.dumps(payload)).graph.edges[0]
    assert default_doc.provenance.document_id == "sha256:" + edge.provenance.source_sha256
