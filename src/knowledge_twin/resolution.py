import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import isfinite

from knowledge_twin.graph import Entity


@dataclass(frozen=True, slots=True)
class ResolutionMatch:
    entity: Entity
    score: float
    exact: bool


_LEGAL_SUFFIXES = {
    "corporation": "corp",
    "company": "co",
    "limited": "ltd",
    "incorporated": "inc",
}


def normalize_entity_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("entity name must be a non-empty string")
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    tokens = re.findall(r"[a-z0-9]+", ascii_text.casefold())
    canonical = [_LEGAL_SUFFIXES.get(token, token) for token in tokens]
    return " ".join(canonical)


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def entity_similarity(left: str, right: str) -> float:
    normalized_left = normalize_entity_name(left)
    normalized_right = normalize_entity_name(right)
    if normalized_left == normalized_right:
        return 1.0
    sequence_score = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    token_score = _token_jaccard(normalized_left, normalized_right)
    return (0.7 * sequence_score) + (0.3 * token_score)


def resolve_entity(
    query: str,
    entities: Sequence[Entity],
    *,
    min_score: float = 0.82,
    limit: int = 5,
) -> tuple[ResolutionMatch, ...]:
    if not isfinite(min_score) or not 0 <= min_score <= 1:
        raise ValueError("min_score must be finite and between 0 and 1")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    normalized_query = normalize_entity_name(query)
    matches: list[ResolutionMatch] = []
    for entity in entities:
        normalized_name = normalize_entity_name(entity.name)
        score = entity_similarity(normalized_query, normalized_name)
        if score >= min_score:
            matches.append(
                ResolutionMatch(
                    entity=entity,
                    score=score,
                    exact=normalized_query == normalized_name,
                )
            )
    matches.sort(key=lambda item: (-item.score, item.entity.id))
    return tuple(matches[:limit])
