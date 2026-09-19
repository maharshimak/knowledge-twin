from dataclasses import dataclass

from knowledge_twin.graph import KnowledgeGraph


@dataclass(frozen=True, slots=True)
class GraphQuality:
    entity_count: int
    edge_count: int
    orphan_count: int
    duplicate_edge_count: int
    evidence_coverage: float
    connected_components: int


def analyze_graph(graph: KnowledgeGraph) -> GraphQuality:
    entity_ids = set(graph.entities)
    referenced: set[str] = set()
    signatures: set[tuple[str, str, str]] = set()
    duplicate_edges = 0
    evidenced = 0
    undirected = {entity_id: set() for entity_id in entity_ids}

    for edge in graph.edges:
        referenced.update((edge.source, edge.target))
        signature = (edge.source, edge.relation, edge.target)
        if signature in signatures:
            duplicate_edges += 1
        signatures.add(signature)
        if edge.evidence.strip():
            evidenced += 1
        undirected[edge.source].add(edge.target)
        undirected[edge.target].add(edge.source)

    seen: set[str] = set()
    components = 0
    for entity_id in sorted(entity_ids):
        if entity_id in seen:
            continue
        components += 1
        stack = [entity_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(undirected[current] - seen)

    edge_count = len(graph.edges)
    return GraphQuality(
        entity_count=len(entity_ids),
        edge_count=edge_count,
        orphan_count=len(entity_ids - referenced),
        duplicate_edge_count=duplicate_edges,
        evidence_coverage=evidenced / edge_count if edge_count else 1.0,
        connected_components=components,
    )


def assert_graph_quality(
    graph: KnowledgeGraph,
    *,
    min_evidence_coverage: float = 0.8,
    allow_orphans: bool = False,
) -> GraphQuality:
    if not 0 <= min_evidence_coverage <= 1:
        raise ValueError("min_evidence_coverage must be between 0 and 1")
    report = analyze_graph(graph)
    reasons: list[str] = []
    if report.evidence_coverage < min_evidence_coverage:
        reasons.append("insufficient evidence coverage")
    if report.duplicate_edge_count:
        reasons.append("duplicate relationships detected")
    if report.orphan_count and not allow_orphans:
        reasons.append("orphan entities detected")
    if reasons:
        raise ValueError("Graph quality gate failed: " + "; ".join(reasons))
    return report
