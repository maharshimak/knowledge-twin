"""Graph integrity validation that reports every problem instead of stopping at one."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from knowledge_twin.graph import Edge, KnowledgeGraph, check_edge_evidence
from knowledge_twin.resolution import normalize_entity_name


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    severity: str  # "error" | "warning"
    message: str
    edge_index: int | None = None
    entity_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "edge_index": self.edge_index,
            "entity_ids": list(self.entity_ids),
        }


@dataclass(frozen=True, slots=True)
class GraphValidationReport:
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def codes(self) -> set[str]:
        return {issue.code for issue in self.issues}

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _edge_identity(edge: Edge) -> tuple:
    return (
        edge.source,
        edge.relation,
        edge.target,
        edge.evidence,
        edge.origin,
        edge.provenance,
    )


def _canonical_name(name: str) -> str:
    try:
        return normalize_entity_name(name)
    except ValueError:
        return ""


def validate_graph(
    graph: KnowledgeGraph,
    *,
    allow_self_loops: bool = False,
    documents: dict[str, str] | None = None,
) -> GraphValidationReport:
    """Check structural and evidence invariants of ``graph``.

    Errors: entity key mismatch, dangling edge, self-loop (unless allowed),
    blank relation, exact duplicate edge, origin/evidence policy violation,
    adjacency index out of sync, provenance that does not match a supplied
    document. Warnings: the same (source, relation, target) asserted more than
    once with different evidence, entities of the same kind sharing a canonical
    name (possible duplicates that were deliberately *not* merged), and
    provenance whose document was not supplied for verification.
    """
    issues: list[ValidationIssue] = []

    for key, entity in graph.entities.items():
        if key != entity.id:
            issues.append(
                ValidationIssue(
                    "ENTITY_KEY_MISMATCH",
                    "error",
                    f"entity stored under key {key!r} has id {entity.id!r}",
                    entity_ids=(key, entity.id),
                )
            )

    identities: dict[tuple, int] = {}
    triples: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, edge in enumerate(graph.edges):
        endpoints = (edge.source, edge.target)
        missing = tuple(node for node in endpoints if node not in graph.entities)
        if missing:
            issues.append(
                ValidationIssue(
                    "DANGLING_EDGE",
                    "error",
                    f"edge references missing entities {sorted(set(missing))}",
                    edge_index=index,
                    entity_ids=tuple(sorted(set(missing))),
                )
            )
        if edge.source == edge.target and not allow_self_loops:
            issues.append(
                ValidationIssue(
                    "SELF_LOOP",
                    "error",
                    "edge connects an entity to itself and self-loops are not allowed",
                    edge_index=index,
                    entity_ids=(edge.source,),
                )
            )
        if not isinstance(edge.relation, str) or not edge.relation.strip():
            issues.append(
                ValidationIssue("BLANK_RELATION", "error", "edge relation is blank", index)
            )
        if not missing:
            try:
                check_edge_evidence(edge, graph.entities)
            except ValueError as error:
                issues.append(
                    ValidationIssue("EVIDENCE_POLICY", "error", str(error), index, endpoints)
                )
        identity = _edge_identity(edge)
        if identity in identities:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_EDGE",
                    "error",
                    f"edge is an exact duplicate of edge {identities[identity]}",
                    index,
                    endpoints,
                )
            )
        else:
            identities[identity] = index
            relation_key = edge.relation.casefold().strip() if isinstance(
                edge.relation, str
            ) else ""
            triples[(edge.source, relation_key, edge.target)].append(index)

        if documents is not None and edge.provenance is not None:
            source_text = documents.get(edge.provenance.document_id)
            if source_text is None:
                issues.append(
                    ValidationIssue(
                        "PROVENANCE_DOCUMENT_MISSING",
                        "warning",
                        f"document {edge.provenance.document_id!r} was not supplied; "
                        "evidence could not be verified",
                        index,
                        endpoints,
                    )
                )
            elif not edge.provenance.verify(source_text):
                issues.append(
                    ValidationIssue(
                        "PROVENANCE_MISMATCH",
                        "error",
                        "evidence hash or span does not match the supplied document",
                        index,
                        endpoints,
                    )
                )

    for (source, relation, target), indexes in triples.items():
        if len(indexes) > 1:
            issues.append(
                ValidationIssue(
                    "REPEATED_RELATIONSHIP",
                    "warning",
                    f"{source} -[{relation}]-> {target} is asserted by edges {indexes}",
                    indexes[0],
                    (source, target),
                )
            )

    expected_adj = Counter((edge.source, _edge_identity(edge)) for edge in graph.edges)
    actual_adj = Counter(
        (node, _edge_identity(edge)) for node, edges in graph.adj.items() for edge in edges
    )
    misplaced = any(node != edge.source for node, edges in graph.adj.items() for edge in edges)
    if expected_adj != actual_adj or misplaced:
        issues.append(
            ValidationIssue(
                "ADJACENCY_MISMATCH",
                "error",
                "adjacency index does not match the edge list; traversal results are unreliable",
            )
        )

    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entity in graph.entities.values():
        if not isinstance(entity.name, str) or not isinstance(entity.kind, str):
            continue
        key = _canonical_name(entity.name)
        if key:
            by_name[(entity.kind.casefold().strip(), key)].append(entity.id)
    for (kind, name), ids in sorted(by_name.items()):
        if len(ids) > 1:
            issues.append(
                ValidationIssue(
                    "AMBIGUOUS_ENTITY_NAME",
                    "warning",
                    f"{len(ids)} entities of kind {kind!r} share canonical name {name!r}; "
                    "they were not merged automatically",
                    entity_ids=tuple(sorted(ids)),
                )
            )

    return GraphValidationReport(issues=tuple(issues))
