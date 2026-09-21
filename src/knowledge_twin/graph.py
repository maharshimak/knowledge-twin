from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    id: str
    kind: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class Edge:
    source: str
    relation: str
    target: str
    evidence: str = ""


class KnowledgeGraph:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.edges: list[Edge] = []
        self.adj: dict[str, list[Edge]] = defaultdict(list)

    def add_entity(self, entity: Entity) -> None:
        if any(
            not isinstance(v, str) or not v.strip() for v in (entity.id, entity.kind, entity.name)
        ):
            raise ValueError("Entity ID, kind and name must be non-empty strings.")
        if entity.id in self.entities:
            raise ValueError("Duplicate entity ID.")
        self.entities[entity.id] = entity

    def add_edge(self, edge: Edge) -> None:
        if edge.source not in self.entities or edge.target not in self.entities:
            raise ValueError("Both edge endpoints must exist.")
        if not isinstance(edge.relation, str) or not edge.relation.strip():
            raise ValueError("Relation must be non-empty text.")
        self.edges.append(edge)
        self.adj[edge.source].append(edge)

    def neighborhood(self, start: str, depth: int = 1) -> set[str]:
        if start not in self.entities:
            raise ValueError("Start entity does not exist.")
        if type(depth) is not int or depth < 0:
            raise ValueError("Depth must be non-negative.")
        seen = {start}
        queue = deque([(start, 0)])
        while queue:
            node, level = queue.popleft()
            if level >= depth:
                continue
            for edge in self.adj[node]:
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append((edge.target, level + 1))
        return seen

    def search(self, query: str, top_k: int = 5) -> list[Entity]:
        if type(top_k) is not int or top_k <= 0:
            raise ValueError("top_k must be positive.")
        terms = set(query.lower().split())
        scored = []
        for entity in self.entities.values():
            text = f"{entity.name} {entity.description}".lower()
            score = sum(term in text for term in terms)
            scored.append((score, entity))

        ordered = sorted(scored, key=lambda x: x[0], reverse=True)
        return [entity for score, entity in ordered if score > 0][:top_k]

    def shortest_path(self, source: str, target: str) -> list[Edge] | None:
        """Return a shortest directed evidence path; None means unreachable."""
        if source not in self.entities or target not in self.entities:
            raise ValueError("Both path endpoints must exist.")
        queue = deque([(source, [])])
        seen = {source}
        while queue:
            node, path = queue.popleft()
            if node == target:
                return path
            for edge in self.adj[node]:
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append((edge.target, [*path, edge]))
        return None
