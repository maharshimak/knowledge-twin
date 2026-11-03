"""JSON-compatible graph serialization (``knowledge-twin.graph.v1``)."""

from __future__ import annotations

import json
from typing import Any

from knowledge_twin.graph import Edge, Entity, EvidenceSpan, KnowledgeGraph, sha256_text

GRAPH_FORMAT = "knowledge-twin.graph.v1"
MAX_ENTITIES = 10_000
MAX_EDGES = 50_000


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys, UTF-8 friendly, compact separators."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return sha256_text(canonical_json(value))


def entity_to_dict(entity: Entity) -> dict:
    return {
        "id": entity.id,
        "kind": entity.kind,
        "name": entity.name,
        "description": entity.description,
    }


def edge_to_dict(edge: Edge) -> dict:
    return {
        "source": edge.source,
        "relation": edge.relation,
        "target": edge.target,
        "evidence": edge.evidence,
        "origin": edge.origin,
        "provenance": edge.provenance.to_dict() if edge.provenance is not None else None,
    }


def graph_to_dict(graph: KnowledgeGraph) -> dict:
    return {
        "format": GRAPH_FORMAT,
        "entities": [entity_to_dict(entity) for entity in graph.entities.values()],
        "edges": [edge_to_dict(edge) for edge in graph.edges],
        "retracted_edges": [edge_to_dict(edge) for edge in graph.retracted_edges],
    }


def _require_str(item: dict, key: str, *, default: str | None = None) -> str:
    value = item.get(key, default)
    if not isinstance(value, str):
        raise TypeError(f"field '{key}' must be a string")
    return value


def entity_from_dict(item: Any) -> Entity:
    if not isinstance(item, dict):
        raise TypeError("each entity must be an object")
    return Entity(
        id=_require_str(item, "id"),
        kind=_require_str(item, "kind"),
        name=_require_str(item, "name"),
        description=_require_str(item, "description", default=""),
    )


def edge_from_dict(item: Any) -> Edge:
    if not isinstance(item, dict):
        raise TypeError("each edge must be an object")
    provenance_raw = item.get("provenance")
    provenance = EvidenceSpan.from_dict(provenance_raw) if provenance_raw is not None else None
    return Edge(
        source=_require_str(item, "source"),
        relation=_require_str(item, "relation"),
        target=_require_str(item, "target"),
        evidence=_require_str(item, "evidence", default=""),
        origin=_require_str(item, "origin", default="unspecified"),
        provenance=provenance,
    )


def parse_graph_lists(data: Any) -> tuple[list[Entity], list[Edge], list[Edge]]:
    """Type-check a serialized graph without applying graph invariants."""
    if not isinstance(data, dict):
        raise TypeError("graph must be an object")
    fmt = data.get("format", GRAPH_FORMAT)
    if fmt != GRAPH_FORMAT:
        raise ValueError(f"unsupported graph format {fmt!r}")
    entities = data.get("entities", [])
    edges = data.get("edges", [])
    retracted = data.get("retracted_edges", [])
    if not all(isinstance(value, list) for value in (entities, edges, retracted)):
        raise ValueError("graph entities, edges and retracted_edges must be arrays")
    if len(entities) > MAX_ENTITIES or len(edges) + len(retracted) > MAX_EDGES:
        raise ValueError("graph exceeds size limits")
    return (
        [entity_from_dict(item) for item in entities],
        [edge_from_dict(item) for item in edges],
        [edge_from_dict(item) for item in retracted],
    )


def graph_from_dict(data: Any, *, enforce: bool = True) -> KnowledgeGraph:
    """Build a graph from :func:`graph_to_dict` output.

    With ``enforce=True`` (default) every entity/edge passes the normal graph
    invariants and the first violation raises ``ValueError``. ``enforce=False``
    only type-checks and loads the structure as-is so that
    :func:`knowledge_twin.validation.validate_graph` can report every problem
    (dangling edges, missing evidence, ...) instead of stopping at the first.
    """
    entities, edges, retracted = parse_graph_lists(data)
    graph = KnowledgeGraph()
    if enforce:
        for entity in entities:
            graph.add_entity(entity)
        for edge in edges:
            graph.add_edge(edge)
        for edge in retracted:
            if edge.source not in graph.entities or edge.target not in graph.entities:
                raise ValueError("Retracted edge endpoints must exist.")
            graph.retracted_edges.append(edge)
        return graph
    for entity in entities:
        if entity.id in graph.entities:
            raise ValueError("Duplicate entity ID.")
        graph.entities[entity.id] = entity
    for edge in edges:
        graph.edges.append(edge)
        graph.adj[edge.source].append(edge)
    graph.retracted_edges.extend(retracted)
    return graph
