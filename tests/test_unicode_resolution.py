import pytest

from knowledge_twin.graph import Entity
from knowledge_twin.resolution import (
    entity_similarity,
    normalize_entity_name,
    resolve_unique_entity,
)


@pytest.mark.parametrize("name", ["東京", "Москва", "أحمد", "મહાર્ શિ"])
def test_non_latin_entity_names_keep_identifying_characters(name):
    assert normalize_entity_name(name)
    assert entity_similarity(name, name) == 1.0


def test_different_non_latin_names_are_not_exact_matches():
    entity = Entity("osaka", "city", "大阪")
    decision = resolve_unique_entity("東京", [entity])
    assert decision.match is None
    assert entity_similarity("東京", "大阪") == 0.0


def test_mixed_script_names_do_not_collapse_to_shared_latin_suffix():
    entities = [Entity("tokyo", "company", "東京 Inc"), Entity("osaka", "company", "大阪 Inc")]
    decision = resolve_unique_entity("東京 Incorporated", entities)
    assert decision.match is not None
    assert decision.match.entity.id == "tokyo"
    assert not decision.ambiguous


@pytest.mark.parametrize("name", ["...", "___", "\u0301"])
def test_names_without_letters_or_numbers_are_rejected(name):
    with pytest.raises(ValueError, match="letter or number"):
        normalize_entity_name(name)

