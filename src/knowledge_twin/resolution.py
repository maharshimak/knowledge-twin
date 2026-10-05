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


@dataclass(frozen=True, slots=True)
class EntityResolutionDecision:
    match: ResolutionMatch | None
    ambiguous: bool
    alternatives: tuple[ResolutionMatch, ...]
    reason: str


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
    kind: str | None = None,
) -> tuple[ResolutionMatch, ...]:
    if not isfinite(min_score) or not 0 <= min_score <= 1:
        raise ValueError("min_score must be finite and between 0 and 1")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")
    if kind is not None and (not isinstance(kind, str) or not kind.strip()):
        raise ValueError("kind must be non-empty text when provided")

    normalized_query = normalize_entity_name(query)
    kind_key = kind.casefold().strip() if kind is not None else None
    matches: list[ResolutionMatch] = []
    for entity in entities:
        if kind_key is not None and entity.kind.casefold().strip() != kind_key:
            continue
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
    matches.sort(key=lambda item: (-item.score, not item.exact, item.entity.id))
    return tuple(matches[:limit])


def resolve_unique_entity(
    query: str,
    entities: Sequence[Entity],
    *,
    min_score: float = 0.82,
    min_margin: float = 0.08,
    kind: str | None = None,
) -> EntityResolutionDecision:
    """Resolve one identity only when the evidence clearly beats alternatives."""
    if not isfinite(min_margin) or not 0 <= min_margin <= 1:
        raise ValueError("min_margin must be finite and between 0 and 1")

    matches = resolve_entity(
        query,
        entities,
        min_score=min_score,
        limit=5,
        kind=kind,
    )
    if not matches:
        return EntityResolutionDecision(
            match=None,
            ambiguous=False,
            alternatives=(),
            reason="no candidate meets the minimum similarity threshold",
        )

    best = matches[0]
    if best.exact:
        exact_matches = tuple(match for match in matches if match.exact)
        if len(exact_matches) == 1:
            return EntityResolutionDecision(
                match=best,
                ambiguous=False,
                alternatives=matches[1:],
                reason="unique canonical-name match",
            )
        return EntityResolutionDecision(
            match=None,
            ambiguous=True,
            alternatives=exact_matches,
            reason="multiple entities share the same canonical name",
        )

    if len(matches) == 1:
        return EntityResolutionDecision(
            match=best,
            ambiguous=False,
            alternatives=(),
            reason="single candidate above threshold",
        )

    runner_up = matches[1]
    margin = best.score - runner_up.score
    if margin < min_margin:
        return EntityResolutionDecision(
            match=None,
            ambiguous=True,
            alternatives=matches,
            reason=(
                f"top candidates are too close: margin {margin:.3f} "
                f"< required {min_margin:.3f}"
            ),
        )

    return EntityResolutionDecision(
        match=best,
        ambiguous=False,
        alternatives=matches[1:],
        reason=f"best candidate clears ambiguity margin by {margin:.3f}",
    )
