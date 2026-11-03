"""Directed shortest-path explanations that carry each hop's evidence."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from knowledge_twin.graph import Edge, KnowledgeGraph
from knowledge_twin.serialization import edge_to_dict


@dataclass(frozen=True, slots=True)
class PathExplanation:
    source: str
    target: str
    found: bool
    hops: tuple[Edge, ...]
    reason: str

    @property
    def length(self) -> int | None:
        return len(self.hops) if self.found else None

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "found": self.found,
            "length": self.length,
            "reason": self.reason,
            "hops": [edge_to_dict(edge) for edge in self.hops],
        }


def explain_path(
    graph: KnowledgeGraph,
    source: str,
    target: str,
    *,
    max_depth: int | None = None,
    relations: Iterable[str] | None = None,
    origins: Iterable[str] | None = None,
) -> PathExplanation:
    """Breadth-first shortest *directed* path from ``source`` to ``target``.

    Edges are followed only from ``edge.source`` to ``edge.target``. Ties are
    broken by edge insertion order, so the result is deterministic. Optional
    filters restrict which relations (case-insensitive) and origins may be used.
    """
    if source not in graph.entities or target not in graph.entities:
        raise ValueError("Both path endpoints must exist.")
    if max_depth is not None and (type(max_depth) is not int or max_depth < 0):
        raise ValueError("max_depth must be a non-negative integer.")
    relation_keys = (
        {relation.casefold().strip() for relation in relations} if relations is not None else None
    )
    origin_keys = set(origins) if origins is not None else None

    def usable(edge: Edge) -> bool:
        if relation_keys is not None and edge.relation.casefold().strip() not in relation_keys:
            return False
        return origin_keys is None or edge.origin in origin_keys

    if source == target:
        return PathExplanation(source, target, True, (), "source and target are the same entity")

    queue: deque[tuple[str, tuple[Edge, ...]]] = deque([(source, ())])
    seen = {source}
    while queue:
        node, path = queue.popleft()
        if max_depth is not None and len(path) >= max_depth:
            continue
        for edge in graph.adj.get(node, ()):
            if edge.target in seen or not usable(edge):
                continue
            hops = (*path, edge)
            if edge.target == target:
                return PathExplanation(
                    source, target, True, hops, f"shortest directed path with {len(hops)} hop(s)"
                )
            seen.add(edge.target)
            queue.append((edge.target, hops))

    limit = f" within {max_depth} hop(s)" if max_depth is not None else ""
    return PathExplanation(
        source, target, False, (), f"no directed path{limit} under the given filters"
    )
