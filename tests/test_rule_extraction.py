import pytest

from knowledge_twin.graph import Entity, KnowledgeGraph
from knowledge_twin.rule_extraction import extract_candidates
from knowledge_twin.validation import validate_graph

ENTITIES = [
    Entity("makma", "system", "MAKMA"),
    Entity("rag", "service", "RAG"),
    Entity("rag-engine", "service", "RAG Engine"),
    Entity("pg", "database", "Postgres"),
]


def test_candidates_carry_sentence_span_and_source_hash() -> None:
    text = "Synthetic overview.\nMAKMA uses the RAG Engine. The RAG Engine depends on Postgres."
    result = extract_candidates(text, document_id="doc-7", entities=ENTITIES)

    triples = [(e.source, e.relation, e.target) for e in result.candidate_edges]
    assert triples == [("makma", "USES", "rag-engine"), ("rag-engine", "DEPENDS_ON", "pg")]
    for edge in result.candidate_edges:
        assert edge.origin == "extracted"
        assert edge.provenance.verify(text)
        assert text[edge.provenance.start : edge.provenance.end] == edge.evidence
    # Longest surface wins: "RAG Engine" is never also reported as "RAG".
    assert all(m.entity_ids != ("rag",) for m in result.mentions)

    graph = KnowledgeGraph()
    for entity in ENTITIES:
        graph.add_entity(entity)
    for edge in result.candidate_edges:
        graph.add_edge(edge)
    assert validate_graph(graph, documents={"doc-7": text}).ok


def test_ambiguous_mentions_are_reported_and_not_linked() -> None:
    entities = [
        Entity("jl-1", "person", "Jordan Lee"),
        Entity("jl-2", "person", "Jordan Lee"),
        Entity("acme", "org", "Acme"),
    ]
    result = extract_candidates(
        "Jordan Lee works at Acme.", document_id="d", entities=entities
    )
    assert result.candidate_edges == ()
    data = result.to_dict()
    assert data["ambiguous_mentions"][0]["entity_ids"] == ["jl-1", "jl-2"]
    assert data["skipped"][0]["reason"] == "ambiguous_mention"


def test_whole_word_matching_and_case_insensitivity() -> None:
    entities = [Entity("ann", "person", "Ann"), Entity("acme", "org", "Acme")]
    assert extract_candidates(
        "Joanne uses Acme.", document_id="d", entities=entities
    ).candidate_edges == ()
    result = extract_candidates("ANN USES acme.", document_id="d", entities=entities)
    assert [(e.source, e.target) for e in result.candidate_edges] == [("ann", "acme")]


def test_conflicting_relation_phrases_and_cross_sentence_pairs_are_skipped() -> None:
    entities = [Entity("a", "x", "Alpha"), Entity("b", "x", "Beta")]
    both = extract_candidates("Alpha uses and owns Beta.", document_id="d", entities=entities)
    assert both.candidate_edges == ()
    assert both.skipped[0]["reason"] == "ambiguous_relation"
    split = extract_candidates("Alpha uses things. Beta exists.", document_id="d",
                               entities=entities)
    assert split.candidate_edges == ()


def test_custom_relation_patterns_and_validation() -> None:
    entities = [Entity("a", "x", "Alpha"), Entity("b", "x", "Beta")]
    result = extract_candidates(
        "Alpha   is   funded by Beta.",
        document_id="d",
        entities=entities,
        relation_patterns={"is funded by": "FUNDED_BY"},
    )
    assert [e.relation for e in result.candidate_edges] == ["FUNDED_BY"]
    for bad in ({}, {"x": "bad relation"}, {" ": "R"}):
        with pytest.raises(ValueError):
            extract_candidates("Alpha", document_id="d", entities=entities,
                               relation_patterns=bad)
    with pytest.raises(ValueError):
        extract_candidates(" ", document_id="d", entities=entities)
    with pytest.raises(ValueError):
        extract_candidates("Alpha", document_id="d", entities=entities * 2)
