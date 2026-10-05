import pytest

from knowledge_twin.graph import Entity
from knowledge_twin.resolution import (
    entity_similarity,
    normalize_entity_name,
    resolve_entity,
    resolve_unique_entity,
)


def test_name_normalization_handles_case_punctuation_and_accents() -> None:
    assert normalize_entity_name("  Société-Générale S.A. ") == "societe generale s a"


def test_entity_similarity_rewards_exact_and_near_matches() -> None:
    assert entity_similarity("OpenAI", "openai") == 1.0
    assert entity_similarity("Acme Corporation", "Acme Corp") > 0.7


def test_resolution_returns_ranked_matches() -> None:
    entities = [
        Entity(id="2", kind="company", name="Acme Corporation"),
        Entity(id="1", kind="company", name="ACME Corp."),
        Entity(id="3", kind="company", name="Contoso"),
    ]

    matches = resolve_entity("Acme Corp", entities, min_score=0.65)

    assert [match.entity.id for match in matches] == ["1", "2"]
    assert matches[0].score >= matches[1].score


def test_unique_resolution_refuses_ambiguous_canonical_duplicates() -> None:
    entities = [
        Entity(id="a", kind="company", name="Acme Corporation"),
        Entity(id="b", kind="company", name="ACME Corp."),
    ]

    decision = resolve_unique_entity("Acme Corp", entities, min_score=0.65)

    assert decision.match is None
    assert decision.ambiguous is True
    assert {item.entity.id for item in decision.alternatives} == {"a", "b"}


def test_unique_resolution_can_filter_by_kind() -> None:
    entities = [
        Entity(id="person", kind="person", name="Jordan Lee"),
        Entity(id="company", kind="company", name="Jordan Lee"),
    ]

    decision = resolve_unique_entity("Jordan Lee", entities, kind="person")

    assert decision.match is not None
    assert decision.match.entity.id == "person"
    assert decision.ambiguous is False


def test_resolution_validates_threshold() -> None:
    with pytest.raises(ValueError, match="min_score"):
        resolve_entity("Acme", [], min_score=1.5)
