"""Deterministic, offline candidate extraction from text.

This is rule-based pattern matching, not model inference: callers supply the
known entities (a gazetteer) and a phrase -> relation lexicon. Mentions are
found by whole-word, case-insensitive matching; a candidate edge is proposed
when two consecutive mentions in one sentence are separated by exactly one
relation phrase. Direction follows text order (first mention -> second), so
passive constructions ("B is used by A") are not handled.

Every candidate edge is ``origin="extracted"`` and carries an
:class:`~knowledge_twin.graph.EvidenceSpan` (document id, sentence span and the
SHA-256 of the full source text). A surface form shared by several entities is
reported as an ambiguous mention and never resolved to one of them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise

from knowledge_twin.graph import Edge, Entity, EvidenceSpan, sha256_text
from knowledge_twin.serialization import edge_to_dict

DEFAULT_RELATION_PATTERNS: dict[str, str] = {
    "uses": "USES",
    "works at": "WORKS_AT",
    "depends on": "DEPENDS_ON",
    "is part of": "PART_OF",
    "owns": "OWNS",
    "reports to": "REPORTS_TO",
    "authored": "AUTHORED",
}

MAX_SOURCE_CHARS = 200_000
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)", flags=re.MULTILINE)
_RELATION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class Mention:
    surface: str
    start: int
    end: int
    entity_ids: tuple[str, ...]

    @property
    def ambiguous(self) -> bool:
        return len(self.entity_ids) > 1

    def to_dict(self) -> dict:
        return {
            "surface": self.surface,
            "start": self.start,
            "end": self.end,
            "entity_ids": list(self.entity_ids),
            "ambiguous": self.ambiguous,
        }


@dataclass(frozen=True, slots=True)
class RuleExtraction:
    document_id: str
    source_sha256: str
    mentions: tuple[Mention, ...]
    candidate_edges: tuple[Edge, ...]
    skipped: tuple[dict, ...]

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "source_sha256": self.source_sha256,
            "mentions": [mention.to_dict() for mention in self.mentions],
            "ambiguous_mentions": [
                mention.to_dict() for mention in self.mentions if mention.ambiguous
            ],
            "candidate_edges": [edge_to_dict(edge) for edge in self.candidate_edges],
            "skipped": list(self.skipped),
        }


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    words = phrase.split()
    return re.compile(
        r"(?<!\w)" + r"\s+".join(re.escape(word) for word in words) + r"(?!\w)",
        flags=re.IGNORECASE,
    )


def _sentences(text: str) -> list[tuple[int, int]]:
    spans = []
    for match in _SENTENCE_RE.finditer(text):
        start, end = match.span()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append((start, end))
    return spans


def _find_mentions(text: str, entities: list[Entity]) -> list[Mention]:
    by_surface: dict[str, list[str]] = defaultdict(list)
    surfaces: dict[str, str] = {}
    for entity in entities:
        key = entity.name.strip().casefold()
        by_surface[key].append(entity.id)
        surfaces.setdefault(key, entity.name.strip())

    raw: list[tuple[int, int, str]] = []
    for key, surface in surfaces.items():
        name_pattern = re.compile(
            r"(?<!\w)" + re.escape(surface) + r"(?!\w)", flags=re.IGNORECASE
        )
        for match in name_pattern.finditer(text):
            raw.append((match.start(), match.end(), key))
    # Earliest start first, then the longest surface, so "RAG Engine" wins over "RAG".
    raw.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    mentions: list[Mention] = []
    cursor = -1
    for start, end, key in raw:
        if start < cursor:
            continue
        mentions.append(
            Mention(text[start:end], start, end, tuple(sorted(set(by_surface[key]))))
        )
        cursor = end
    return mentions


def extract_candidates(
    text: str,
    *,
    document_id: str,
    entities: list[Entity],
    relation_patterns: dict[str, str] | None = None,
) -> RuleExtraction:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("source text must be non-empty")
    if len(text) > MAX_SOURCE_CHARS:
        raise ValueError(f"source text exceeds {MAX_SOURCE_CHARS} characters")
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be non-empty text")
    ids = [entity.id for entity in entities]
    if len(ids) != len(set(ids)):
        raise ValueError("entity IDs must be unique")
    for entity in entities:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (entity.id, entity.kind, entity.name)
        ):
            raise ValueError("Entity ID, kind and name must be non-empty strings.")
    patterns = DEFAULT_RELATION_PATTERNS if relation_patterns is None else relation_patterns
    if not isinstance(patterns, dict) or not patterns:
        raise ValueError("relation_patterns must be a non-empty object")
    compiled: list[tuple[re.Pattern[str], str]] = []
    for phrase, relation in patterns.items():
        if not isinstance(phrase, str) or not phrase.split():
            raise ValueError("relation phrases must be non-empty text")
        if not isinstance(relation, str) or not _RELATION_RE.match(relation):
            raise ValueError("relation names must match ^[A-Za-z][A-Za-z0-9_]{0,63}$")
        compiled.append((_phrase_pattern(phrase), relation))

    mentions = _find_mentions(text, entities)
    source_sha = sha256_text(text)
    candidates: list[Edge] = []
    seen: set[Edge] = set()
    skipped: list[dict] = []
    for sentence_start, sentence_end in _sentences(text):
        inside = [m for m in mentions if sentence_start <= m.start and m.end <= sentence_end]
        for left, right in pairwise(inside):
            between = text[left.end : right.start]
            relations = sorted({rel for pattern, rel in compiled if pattern.search(between)})
            if not relations:
                continue
            span = [sentence_start, sentence_end]
            if left.ambiguous or right.ambiguous:
                skipped.append(
                    {
                        "reason": "ambiguous_mention",
                        "span": span,
                        "mentions": [left.surface, right.surface],
                    }
                )
                continue
            if len(relations) > 1:
                skipped.append(
                    {"reason": "ambiguous_relation", "span": span, "relations": relations}
                )
                continue
            if left.entity_ids == right.entity_ids:
                skipped.append({"reason": "self_reference", "span": span})
                continue
            provenance = EvidenceSpan(
                document_id=document_id,
                start=sentence_start,
                end=sentence_end,
                source_sha256=source_sha,
                quote=text[sentence_start:sentence_end],
            )
            edge = Edge(
                source=left.entity_ids[0],
                relation=relations[0],
                target=right.entity_ids[0],
                evidence=provenance.quote,
                origin="extracted",
                provenance=provenance,
            )
            if edge not in seen:
                seen.add(edge)
                candidates.append(edge)

    return RuleExtraction(
        document_id=document_id,
        source_sha256=source_sha,
        mentions=tuple(mentions),
        candidate_edges=tuple(candidates),
        skipped=tuple(skipped),
    )
