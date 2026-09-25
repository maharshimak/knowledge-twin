from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import isfinite

from knowledge_twin.graph import Edge, KnowledgeGraph

CommunityAlgorithm = Callable[
    [set[str], list[tuple[str, str]]],
    Iterable[set[str]],
]


@dataclass(frozen=True, slots=True)
class GraphCommunity:
    id: str
    entity_ids: tuple[str, ...]
    edge_count: int
    evidence: tuple[str, ...]


class LouvainCommunityDetector:
    """Optional Louvain graph clustering with a dependency-light adapter boundary."""

    def __init__(
        self,
        *,
        resolution: float = 1.0,
        seed: int = 42,
        algorithm: CommunityAlgorithm | None = None,
    ) -> None:
        if not isfinite(resolution) or resolution <= 0:
            raise ValueError("resolution must be finite and positive.")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("seed must be an integer.")
        self.resolution = resolution
        self.seed = seed
        self.algorithm = algorithm

    def _networkx_algorithm(
        self,
        nodes: set[str],
        edges: list[tuple[str, str]],
    ) -> Iterable[set[str]]:
        try:
            import networkx as nx
        except ImportError as error:
            raise RuntimeError(
                "NetworkX is not installed; install the graph-analytics extra."
            ) from error
        graph = nx.Graph()
        graph.add_nodes_from(nodes)
        graph.add_edges_from(edges)
        return nx.community.louvain_communities(
            graph,
            resolution=self.resolution,
            seed=self.seed,
        )

    def detect(self, graph: KnowledgeGraph) -> tuple[GraphCommunity, ...]:
        nodes = set(graph.entities)
        if not nodes:
            return ()
        edges = [(edge.source, edge.target) for edge in graph.edges]
        algorithm = self.algorithm or self._networkx_algorithm
        raw = [set(group) for group in algorithm(nodes, edges)]
        if any(not group for group in raw):
            raise ValueError("Community algorithm returned an empty group.")
        flattened = [node for group in raw for node in group]
        if set(flattened) != nodes or len(flattened) != len(set(flattened)):
            raise ValueError(
                "Community algorithm must return a disjoint partition of all graph entities."
            )

        ordered_groups = sorted(
            (tuple(sorted(group)) for group in raw),
            key=lambda group: group[0],
        )
        communities: list[GraphCommunity] = []
        for index, members in enumerate(ordered_groups, start=1):
            member_set = set(members)
            internal_edges: list[Edge] = [
                edge
                for edge in graph.edges
                if edge.source in member_set and edge.target in member_set
            ]
            evidence = tuple(
                dict.fromkeys(
                    edge.evidence.strip()
                    for edge in internal_edges
                    if edge.evidence.strip()
                )
            )
            communities.append(
                GraphCommunity(
                    id=f"community-{index}",
                    entity_ids=members,
                    edge_count=len(internal_edges),
                    evidence=evidence,
                )
            )
        return tuple(communities)
