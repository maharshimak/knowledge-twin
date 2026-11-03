"""Versioned, conflict-aware graph imports.

Imports never merge two entities with different IDs. When an incoming entity
looks like an existing one (same kind, similar canonical name) the candidates
are reported as ``ambiguity_candidates`` for a human to decide; when an incoming
entity reuses an existing ID with different fields, it is a conflict and the
existing value is never overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledge_twin.graph import Edge, Entity, KnowledgeGraph, check_edge_evidence
from knowledge_twin.resolution import normalize_entity_name, resolve_entity
from knowledge_twin.serialization import (
    canonical_sha256,
    entity_to_dict,
    graph_to_dict,
    parse_graph_lists,
)


class ImportVersionConflict(RuntimeError):
    """Raised when ``expected_version`` does not match the current version."""


@dataclass(frozen=True, slots=True)
class MergeReport:
    import_id: str
    payload_sha256: str
    base_version: int
    new_version: int | None
    applied: bool
    strict: bool
    added_entities: tuple[str, ...] = ()
    unchanged_entities: tuple[str, ...] = ()
    conflicting_entities: tuple[dict, ...] = ()
    ambiguity_candidates: tuple[dict, ...] = ()
    added_edges: tuple[int, ...] = ()
    duplicate_edges: tuple[int, ...] = ()
    suppressed_edges: tuple[int, ...] = ()
    rejected_edges: tuple[dict, ...] = ()

    @property
    def has_blocking_conflicts(self) -> bool:
        return bool(self.conflicting_entities or self.rejected_edges)

    def to_dict(self) -> dict:
        return {
            "import_id": self.import_id,
            "payload_sha256": self.payload_sha256,
            "base_version": self.base_version,
            "new_version": self.new_version,
            "applied": self.applied,
            "strict": self.strict,
            "has_blocking_conflicts": self.has_blocking_conflicts,
            "added_entities": list(self.added_entities),
            "unchanged_entities": list(self.unchanged_entities),
            "conflicting_entities": list(self.conflicting_entities),
            "ambiguity_candidates": list(self.ambiguity_candidates),
            "added_edges": list(self.added_edges),
            "duplicate_edges": list(self.duplicate_edges),
            "suppressed_edges": list(self.suppressed_edges),
            "rejected_edges": list(self.rejected_edges),
        }


@dataclass(slots=True)
class VersionedGraph:
    """A graph plus a monotonically increasing import version and history."""

    graph: KnowledgeGraph = field(default_factory=KnowledgeGraph)
    version: int = 0
    history: list[MergeReport] = field(default_factory=list)

    def import_graph(
        self,
        incoming: dict[str, Any] | KnowledgeGraph,
        *,
        import_id: str,
        strict: bool = True,
        expected_version: int | None = None,
        ambiguity_threshold: float = 0.82,
    ) -> MergeReport:
        """Merge ``incoming`` into the graph and return a merge report.

        ``strict=True`` applies nothing when any entity conflicts or any edge is
        rejected. ``strict=False`` applies the non-conflicting parts. Conflicting
        entities always keep their existing values. The version advances only
        when something was applied.
        """
        if not isinstance(import_id, str) or not import_id.strip():
            raise ValueError("import_id must be non-empty text")
        if expected_version is not None and expected_version != self.version:
            raise ImportVersionConflict(
                f"expected graph version {expected_version}, current version is {self.version}"
            )
        payload = graph_to_dict(incoming) if isinstance(incoming, KnowledgeGraph) else incoming
        entities, edges, _ = parse_graph_lists(payload)
        payload_sha = canonical_sha256(payload)
        base = self.graph

        incoming_ids = [entity.id for entity in entities]
        if len(set(incoming_ids)) != len(incoming_ids):
            raise ValueError("incoming graph contains duplicate entity IDs")

        added: list[Entity] = []
        unchanged: list[str] = []
        conflicts: list[dict] = []
        ambiguity: list[dict] = []
        existing_entities = list(base.entities.values())
        for entity in entities:
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (entity.id, entity.kind, entity.name)
            ):
                raise ValueError("Entity ID, kind and name must be non-empty strings.")
            current = base.entities.get(entity.id)
            if current is None:
                added.append(entity)
                candidates = _ambiguity_candidates(entity, existing_entities, ambiguity_threshold)
                if candidates:
                    ambiguity.append({"incoming_id": entity.id, "candidates": candidates})
            elif current == entity:
                unchanged.append(entity.id)
            else:
                existing = entity_to_dict(current)
                proposed = entity_to_dict(entity)
                conflicts.append(
                    {
                        "id": entity.id,
                        "fields": {
                            key: {"existing": existing[key], "incoming": proposed[key]}
                            for key in existing
                            if existing[key] != proposed[key]
                        },
                    }
                )

        merged_entities = dict(base.entities)
        merged_entities.update({entity.id: entity for entity in added})
        existing_edges = set(map(_edge_key, base.edges))
        retracted = set(map(_edge_key, base.retracted_edges))
        accepted: list[tuple[int, Edge]] = []
        duplicates: list[int] = []
        suppressed: list[int] = []
        rejected: list[dict] = []
        for index, edge in enumerate(edges):
            reason = _edge_rejection(edge, merged_entities)
            key = _edge_key(edge)
            if reason is not None:
                rejected.append({"index": index, "reason": reason})
            elif key in retracted:
                suppressed.append(index)
            elif key in existing_edges:
                duplicates.append(index)
            else:
                existing_edges.add(key)
                accepted.append((index, edge))

        base_version = self.version
        blocking = bool(conflicts or rejected)
        apply = bool(added or accepted) and not (strict and blocking)
        if apply:
            for entity in added:
                base.add_entity(entity)
            for _, edge in accepted:
                base.add_edge(edge)
            self.version += 1

        report = MergeReport(
            import_id=import_id,
            payload_sha256=payload_sha,
            base_version=base_version,
            new_version=self.version if apply else None,
            applied=apply,
            strict=strict,
            added_entities=tuple(entity.id for entity in added),
            unchanged_entities=tuple(unchanged),
            conflicting_entities=tuple(conflicts),
            ambiguity_candidates=tuple(ambiguity),
            added_edges=tuple(index for index, _ in accepted),
            duplicate_edges=tuple(duplicates),
            suppressed_edges=tuple(suppressed),
            rejected_edges=tuple(rejected),
        )
        self.history.append(report)
        return report


def _edge_key(edge: Edge) -> tuple:
    return (
        edge.source,
        edge.relation,
        edge.target,
        edge.evidence,
        edge.origin,
        edge.provenance,
    )


def _edge_rejection(edge: Edge, entities: dict[str, Entity]) -> str | None:
    if edge.source not in entities or edge.target not in entities:
        return "edge endpoints must exist in the base graph or this import"
    if not edge.relation.strip():
        return "relation must be non-empty text"
    try:
        check_edge_evidence(edge, entities)
    except ValueError as error:
        return str(error)
    return None


def _ambiguity_candidates(
    entity: Entity, existing: list[Entity], threshold: float
) -> list[dict]:
    if not _has_canonical_name(entity.name):
        return []
    same_kind = [
        candidate
        for candidate in existing
        if candidate.kind.casefold().strip() == entity.kind.casefold().strip()
        and _has_canonical_name(candidate.name)
    ]
    matches = resolve_entity(entity.name, same_kind, min_score=threshold, limit=5)
    return [
        {
            "id": match.entity.id,
            "name": match.entity.name,
            "score": round(match.score, 6),
            "exact_canonical_name": match.exact,
        }
        for match in matches
    ]


def _has_canonical_name(name: str) -> bool:
    # Names whose canonical form is empty (or rejected) cannot be compared
    # safely; they are never offered as candidates rather than matched by accident.
    try:
        return bool(normalize_entity_name(name))
    except ValueError:
        return False
