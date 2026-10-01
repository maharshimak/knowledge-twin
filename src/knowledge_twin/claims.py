from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite

_DEFAULT_MULTI_VALUED_PREDICATES = frozenset(
    {
        "has_skill",
        "worked_at",
        "member_of",
        "uses",
        "authored",
        "participated_in",
        "related_to",
        "knows",
    }
)


@dataclass(frozen=True, slots=True)
class Claim:
    subject: str
    predicate: str
    object: str
    evidence: str
    confidence: float = 1.0
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.subject, self.predicate, self.object, self.evidence)
        ):
            raise ValueError("claim subject, predicate, object and evidence are required")
        if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ClaimConflict:
    subject: str
    predicate: str
    objects: tuple[str, ...]
    claims: tuple[Claim, ...]


class ClaimLedger:
    """Evidence-first claim store with deterministic contradiction detection."""

    def __init__(
        self,
        *,
        multi_valued_predicates: frozenset[str] | None = None,
    ) -> None:
        self._claims: list[Claim] = []
        configured = (
            _DEFAULT_MULTI_VALUED_PREDICATES
            if multi_valued_predicates is None
            else multi_valued_predicates
        )
        self._multi_valued_predicates = frozenset(
            predicate.casefold().strip()
            for predicate in configured
            if predicate.strip()
        )

    def add(self, claim: Claim) -> None:
        if claim not in self._claims:
            self._claims.append(claim)

    def claims_for(self, subject: str, predicate: str | None = None) -> tuple[Claim, ...]:
        subject_key = subject.casefold().strip()
        predicate_key = predicate.casefold().strip() if predicate is not None else None
        return tuple(
            claim
            for claim in self._claims
            if claim.subject.casefold() == subject_key
            and (predicate_key is None or claim.predicate.casefold() == predicate_key)
        )

    def conflicts(self, *, min_confidence: float = 0.5) -> tuple[ClaimConflict, ...]:
        if not 0 <= min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        grouped: dict[tuple[str, str], list[Claim]] = defaultdict(list)
        for claim in self._claims:
            if claim.confidence >= min_confidence:
                grouped[(claim.subject.casefold(), claim.predicate.casefold())].append(claim)

        conflicts: list[ClaimConflict] = []
        for claims in grouped.values():
            predicate_key = claims[0].predicate.casefold().strip()
            if predicate_key in self._multi_valued_predicates:
                continue

            # When every claim carries an observation time, compare values only
            # within the same observation. A status changing over time is history,
            # not a contradiction.
            groups: list[list[Claim]]
            if all(claim.observed_at is not None for claim in claims):
                by_time: dict[str, list[Claim]] = defaultdict(list)
                for claim in claims:
                    by_time[str(claim.observed_at)].append(claim)
                groups = list(by_time.values())
            else:
                groups = [claims]

            for candidate_claims in groups:
                objects = sorted(
                    {claim.object.strip() for claim in candidate_claims},
                    key=str.casefold,
                )
                if len(objects) < 2:
                    continue
                conflicts.append(
                    ClaimConflict(
                        subject=candidate_claims[0].subject,
                        predicate=candidate_claims[0].predicate,
                        objects=tuple(objects),
                        claims=tuple(candidate_claims),
                    )
                )
        return tuple(
            sorted(
                conflicts,
                key=lambda item: (item.subject.casefold(), item.predicate.casefold()),
            )
        )

    def best_supported(self, subject: str, predicate: str) -> Claim | None:
        candidates = self.claims_for(subject, predicate)
        if not candidates:
            return None
        support: dict[str, float] = defaultdict(float)
        canonical: dict[str, Claim] = {}
        for claim in candidates:
            key = claim.object.casefold().strip()
            support[key] += claim.confidence
            previous = canonical.get(key)
            if previous is None or claim.confidence > previous.confidence:
                canonical[key] = claim
        winner = max(support, key=lambda key: (support[key], key))
        return canonical[winner]
