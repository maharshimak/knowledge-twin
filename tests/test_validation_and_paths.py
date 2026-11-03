import pytest

from knowledge_twin.graph import Edge, Entity, EvidenceSpan, KnowledgeGraph
from knowledge_twin.paths import explain_path
from knowledge_twin.serialization import graph_from_dict, graph_to_dict
from knowledge_twin.validation import validate_graph

DOC = "Synthetic. A uses B. B uses C. A owns C."


def ev(quote: str, doc: str = "doc-1", text: str = DOC) -> EvidenceSpan:
    start = text.index(quote)
    return EvidenceSpan.from_source(doc, text, start, start + len(quote))


def chain() -> KnowledgeGraph:
    graph = KnowledgeGraph()
    for key in "ABCD":
        graph.add_entity(Entity(key.lower(), "system", key))
    for quote, (s, r, t) in {
        "A uses B.": ("a", "USES", "b"),
        "B uses C.": ("b", "USES", "c"),
        "A owns C.": ("a", "OWNS", "c"),
    }.items():
        provenance = ev(quote)
        graph.add_edge(Edge(s, r, t, provenance.quote, "extracted", provenance))
    return graph


def test_clean_graph_validates_and_provenance_verifies() -> None:
    report = validate_graph(chain(), documents={"doc-1": DOC})
    assert report.ok
    assert report.issues == ()


def test_validator_reports_all_structural_problems_at_once() -> None:
    payload = graph_to_dict(chain())
    payload["entities"].append({"id": "x", "kind": "system", "name": "X"})
    payload["edges"] += [
        {"source": "a", "relation": "USES", "target": "ghost", "evidence": "e"},
        {"source": "x", "relation": "LOOPS", "target": "x", "evidence": "e"},
        {"source": "a", "relation": "USES", "target": "b", "evidence": "", "origin": "extracted"},
        {"source": "d", "relation": "  ", "target": "a", "evidence": "e"},
        payload["edges"][0],  # exact duplicate of edge 0
    ]
    graph = graph_from_dict(payload, enforce=False)

    report = validate_graph(graph)

    assert not report.ok
    assert {
        "DANGLING_EDGE",
        "SELF_LOOP",
        "EVIDENCE_POLICY",
        "BLANK_RELATION",
        "DUPLICATE_EDGE",
        "REPEATED_RELATIONSHIP",
    } <= report.codes()
    assert validate_graph(graph, allow_self_loops=True).codes().isdisjoint({"SELF_LOOP"})


def test_validator_detects_tampered_or_unverifiable_provenance() -> None:
    graph = chain()
    report = validate_graph(graph, documents={"doc-1": DOC.replace("owns", "sold")})
    assert [issue.code for issue in report.issues] == ["PROVENANCE_MISMATCH"] * 3

    missing = validate_graph(graph, documents={})
    assert missing.ok
    assert missing.warning_count == 3
    assert missing.codes() == {"PROVENANCE_DOCUMENT_MISSING"}


def test_validator_detects_adjacency_drift_and_key_mismatch() -> None:
    graph = chain()
    graph.adj["a"].pop()
    graph.entities["alias"] = graph.entities["d"]
    report = validate_graph(graph)
    assert {"ADJACENCY_MISMATCH", "ENTITY_KEY_MISMATCH"} <= report.codes()


def test_validator_surfaces_same_name_entities_without_merging() -> None:
    graph = KnowledgeGraph()
    graph.add_entity(Entity("p1", "person", "Jordan Lee"))
    graph.add_entity(Entity("p2", "person", "jordan  lee"))
    graph.add_entity(Entity("c1", "company", "Jordan Lee"))
    report = validate_graph(graph)
    assert report.ok
    issue = next(i for i in report.issues if i.code == "AMBIGUOUS_ENTITY_NAME")
    assert issue.entity_ids == ("p1", "p2")
    assert set(graph.entities) == {"p1", "p2", "c1"}


def test_path_explanation_is_directed_and_carries_evidence() -> None:
    graph = chain()
    explanation = explain_path(graph, "a", "c")
    assert explanation.found and explanation.length == 1
    hop = explanation.to_dict()["hops"][0]
    assert hop["relation"] == "OWNS"
    assert hop["provenance"]["document_id"] == "doc-1"
    assert hop["provenance"]["quote"] == "A owns C."

    assert not explain_path(graph, "c", "a").found  # direction is respected


def test_path_filters_and_depth_limit() -> None:
    graph = chain()
    via_uses = explain_path(graph, "a", "c", relations=["uses"])
    assert [hop.relation for hop in via_uses.hops] == ["USES", "USES"]
    assert [(hop.source, hop.target) for hop in via_uses.hops] == [("a", "b"), ("b", "c")]

    limited = explain_path(graph, "a", "c", relations=["USES"], max_depth=1)
    assert not limited.found and limited.length is None
    assert "within 1 hop" in limited.reason

    assert not explain_path(graph, "a", "c", origins=["human"]).found
    assert explain_path(graph, "a", "a").length == 0
    with pytest.raises(ValueError):
        explain_path(graph, "a", "missing")
    with pytest.raises(ValueError):
        explain_path(graph, "a", "c", max_depth=-1)


def test_path_matches_existing_shortest_path_on_random_graphs() -> None:
    import random

    rng = random.Random(7)
    for _ in range(50):
        graph = KnowledgeGraph()
        nodes = [f"n{i}" for i in range(8)]
        for node in nodes:
            graph.add_entity(Entity(node, "node", node))
        for _ in range(rng.randint(0, 20)):
            graph.add_edge(Edge(rng.choice(nodes), "R", rng.choice(nodes), "synthetic"))
        for source in nodes:
            for target in nodes:
                expected = graph.shortest_path(source, target)
                explanation = explain_path(graph, source, target)
                assert explanation.found == (expected is not None)
                if expected is not None:
                    assert len(explanation.hops) == len(expected)
                    # every hop is a real edge and the hops chain source -> target
                    position = source
                    for hop in explanation.hops:
                        assert hop in graph.edges and hop.source == position
                        position = hop.target
                    assert position == target
