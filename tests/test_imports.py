import pytest

from knowledge_twin.graph import Edge, Entity, EvidenceSpan, KnowledgeGraph
from knowledge_twin.imports import ImportVersionConflict, VersionedGraph
from knowledge_twin.serialization import graph_to_dict

DOC = "Synthetic note. Alice works at Acme Corp. Bob works at Acme Corp."


def ev(quote: str) -> EvidenceSpan:
    start = DOC.index(quote)
    return EvidenceSpan.from_source("note-1", DOC, start, start + len(quote))


def extracted(source: str, target: str, quote: str) -> dict:
    provenance = ev(quote)
    return {
        "source": source,
        "relation": "WORKS_AT",
        "target": target,
        "evidence": provenance.quote,
        "origin": "extracted",
        "provenance": provenance.to_dict(),
    }


def seeded() -> VersionedGraph:
    repo = VersionedGraph()
    report = repo.import_graph(
        {
            "entities": [
                {"id": "alice", "kind": "person", "name": "Alice"},
                {"id": "acme", "kind": "org", "name": "Acme Corp"},
            ],
            "edges": [extracted("alice", "acme", "Alice works at Acme Corp.")],
        },
        import_id="seed",
    )
    assert report.applied and report.new_version == 1
    return repo


def test_reimporting_the_same_payload_is_a_no_op() -> None:
    repo = seeded()
    payload = graph_to_dict(repo.graph)
    report = repo.import_graph(payload, import_id="again")
    assert not report.applied
    assert report.new_version is None and repo.version == 1
    assert set(report.unchanged_entities) == {"alice", "acme"}
    assert report.duplicate_edges == (0,)
    assert len(repo.graph.edges) == 1


def test_entity_conflict_is_reported_and_never_overwrites() -> None:
    repo = seeded()
    incoming = {
        "entities": [
            {"id": "acme", "kind": "org", "name": "Acme Corporation Renamed"},
            {"id": "bob", "kind": "person", "name": "Bob"},
        ],
        "edges": [],
    }
    strict = repo.import_graph(incoming, import_id="strict")
    assert not strict.applied and strict.has_blocking_conflicts
    assert strict.conflicting_entities[0]["fields"] == {
        "name": {"existing": "Acme Corp", "incoming": "Acme Corporation Renamed"}
    }
    assert "bob" not in repo.graph.entities and repo.version == 1

    lenient = repo.import_graph(incoming, import_id="lenient", strict=False)
    assert lenient.applied and lenient.added_entities == ("bob",)
    assert repo.graph.entities["acme"].name == "Acme Corp"
    assert repo.version == 2
    assert [r.import_id for r in repo.history] == ["seed", "strict", "lenient"]


def test_similar_names_are_surfaced_as_candidates_not_merged() -> None:
    repo = seeded()
    report = repo.import_graph(
        {
            "entities": [
                {"id": "acme-2", "kind": "org", "name": "ACME Corporation"},
                {"id": "acme-person", "kind": "person", "name": "Acme Corp"},
            ],
            "edges": [],
        },
        import_id="dupes",
    )
    assert report.applied
    assert set(repo.graph.entities) == {"alice", "acme", "acme-2", "acme-person"}
    (candidate,) = report.ambiguity_candidates
    assert candidate["incoming_id"] == "acme-2"
    assert candidate["candidates"][0]["id"] == "acme"
    assert candidate["candidates"][0]["exact_canonical_name"] is True


def test_rejected_edges_block_strict_import_atomically() -> None:
    repo = seeded()
    incoming = {
        "entities": [{"id": "bob", "kind": "person", "name": "Bob"}],
        "edges": [
            extracted("bob", "acme", "Bob works at Acme Corp."),
            {"source": "bob", "relation": "WORKS_AT", "target": "acme", "origin": "extracted"},
            {"source": "bob", "relation": "KNOWS", "target": "ghost", "evidence": "x"},
            # evidence mentions Alice, not Bob: cannot support a Bob edge
            extracted("bob", "acme", "Alice works at Acme Corp."),
        ],
    }
    report = repo.import_graph(incoming, import_id="bad")
    assert not report.applied
    assert [item["index"] for item in report.rejected_edges] == [1, 2, 3]
    assert "bob" not in repo.graph.entities

    lenient = repo.import_graph(incoming, import_id="ok-parts", strict=False)
    assert lenient.applied and lenient.added_edges == (0,)
    assert len(repo.graph.edges) == 2


def test_adversarial_duplicate_edges_inside_one_import_are_added_once() -> None:
    repo = seeded()
    edge = extracted("alice", "acme", "Alice works at Acme Corp.")
    human = {"source": "alice", "relation": "MENTORS", "target": "acme", "evidence": "manager",
             "origin": "human"}
    report = repo.import_graph(
        {"entities": [], "edges": [edge, human, dict(human), edge]}, import_id="dups"
    )
    assert report.added_edges == (1,)
    assert report.duplicate_edges == (0, 2, 3)
    assert len(repo.graph.edges) == 2


def test_reextraction_cannot_undo_a_human_correction() -> None:
    repo = seeded()
    graph = repo.graph
    graph.add_entity(Entity("beta", "org", "Beta Ltd"))
    graph.correct_edge(graph.edges[0], target="beta", note="HR review")

    report = repo.import_graph(
        {"entities": [], "edges": [extracted("alice", "acme", "Alice works at Acme Corp.")]},
        import_id="re-extract",
    )
    assert report.suppressed_edges == (0,)
    assert not report.applied
    assert [(e.target, e.origin) for e in graph.edges] == [("beta", "human")]


def test_expected_version_guards_against_stale_imports() -> None:
    repo = seeded()
    with pytest.raises(ImportVersionConflict):
        repo.import_graph({"entities": [], "edges": []}, import_id="x", expected_version=0)
    report = repo.import_graph(
        {"entities": [{"id": "z", "kind": "k", "name": "Z"}], "edges": []},
        import_id="y",
        expected_version=1,
    )
    assert report.base_version == 1 and report.new_version == 2


def test_import_accepts_knowledge_graph_and_rejects_bad_payloads() -> None:
    repo = VersionedGraph()
    graph = KnowledgeGraph()
    graph.add_entity(Entity("a", "k", "A"))
    graph.add_entity(Entity("b", "k", "B"))
    graph.add_edge(Edge("a", "R", "b", "note", "human"))
    assert repo.import_graph(graph, import_id="obj").applied
    with pytest.raises(ValueError, match="duplicate entity IDs"):
        repo.import_graph(
            {"entities": [{"id": "q", "kind": "k", "name": "Q"}] * 2}, import_id="d"
        )
    with pytest.raises(ValueError, match="import_id"):
        repo.import_graph({"entities": []}, import_id=" ")
    with pytest.raises(ValueError, match="format"):
        repo.import_graph({"format": "other"}, import_id="f")


def test_names_without_canonical_form_never_become_candidates() -> None:
    # Canonicalization drops non-Latin scripts on main (see PR #13). Such names must
    # not be reported as matching each other just because both canonicalize to "".
    repo = VersionedGraph()
    repo.import_graph({"entities": [{"id": "tokyo", "kind": "city", "name": "東京"}]},
                      import_id="1")
    report = repo.import_graph(
        {"entities": [{"id": "osaka", "kind": "city", "name": "大阪"}]}, import_id="2"
    )
    assert report.applied and report.ambiguity_candidates == ()
