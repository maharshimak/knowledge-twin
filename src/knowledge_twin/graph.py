import hashlib
import re
from collections import defaultdict, deque
from dataclasses import dataclass

#: Allowed values for :attr:`Edge.origin`.
#:
#: ``unspecified`` keeps backwards compatibility with callers that predate the
#: origin field. ``extracted`` edges were produced automatically from a source
#: document and must carry an :class:`EvidenceSpan`. ``human`` edges were asserted
#: or corrected by a person and must *not* carry extraction evidence, so a
#: correction can never silently inherit the provenance of the fact it replaced.
EDGE_ORIGINS = frozenset({"unspecified", "extracted", "human"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_text(text: str) -> str:
    """SHA-256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mentions_name(text: str, name: str) -> bool:
    """True when ``name`` occurs in ``text`` as a whole word/phrase (case-insensitive).

    Plain substring tests accept ``"Ann"`` inside ``"Joanne"``; this check requires
    the name not to be glued to other word characters on either side.
    """
    if not name.strip():
        return False
    pattern = r"(?<!\w)" + re.escape(name.strip()) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


@dataclass(frozen=True)
class EvidenceSpan:
    """Attributable evidence: a character span of a specific source document.

    ``start``/``end`` are Python ``str`` (Unicode code point) offsets into the
    source text, ``source_sha256`` is the SHA-256 of the whole source text as
    UTF-8, and ``quote`` is ``source_text[start:end]``.
    """

    document_id: str
    start: int
    end: int
    source_sha256: str
    quote: str

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise ValueError("Evidence document_id must be non-empty text.")
        for value in (self.start, self.end):
            if type(value) is not int or value < 0:
                raise ValueError("Evidence span offsets must be non-negative integers.")
        if self.end <= self.start:
            raise ValueError("Evidence span end must be greater than start.")
        if not isinstance(self.source_sha256, str) or not _SHA256_RE.match(self.source_sha256):
            raise ValueError("Evidence source_sha256 must be 64 lowercase hex characters.")
        if not isinstance(self.quote, str) or len(self.quote) != self.end - self.start:
            raise ValueError("Evidence quote length must equal the span length.")
        if not self.quote.strip():
            raise ValueError("Evidence quote must contain non-whitespace text.")

    @classmethod
    def from_source(
        cls, document_id: str, source_text: str, start: int, end: int
    ) -> "EvidenceSpan":
        if not isinstance(source_text, str):
            raise TypeError("source_text must be a string.")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(
            source_text
        ):
            raise ValueError("Evidence span must lie inside the source text.")
        return cls(
            document_id=document_id,
            start=start,
            end=end,
            source_sha256=sha256_text(source_text),
            quote=source_text[start:end],
        )

    def verify(self, source_text: str) -> bool:
        """True when ``source_text`` is the hashed document and the span matches."""
        return (
            isinstance(source_text, str)
            and sha256_text(source_text) == self.source_sha256
            and source_text[self.start : self.end] == self.quote
        )

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "start": self.start,
            "end": self.end,
            "source_sha256": self.source_sha256,
            "quote": self.quote,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceSpan":
        if not isinstance(data, dict):
            raise TypeError("Evidence provenance must be an object.")
        return cls(
            document_id=data.get("document_id"),
            start=data.get("start"),
            end=data.get("end"),
            source_sha256=data.get("source_sha256"),
            quote=data.get("quote"),
        )


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
    origin: str = "unspecified"
    provenance: EvidenceSpan | None = None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))


def check_edge_evidence(edge: Edge, entities: dict[str, Entity]) -> None:
    """Enforce the origin/evidence invariants for one edge (raises ``ValueError``)."""
    if edge.origin not in EDGE_ORIGINS:
        raise ValueError(f"Edge origin must be one of {sorted(EDGE_ORIGINS)}.")
    if edge.provenance is not None and not isinstance(edge.provenance, EvidenceSpan):
        raise ValueError("Edge provenance must be an EvidenceSpan or None.")
    if edge.origin == "extracted":
        if edge.provenance is None:
            raise ValueError(
                "Extracted relationships require attributable source evidence "
                "(document id, span and source SHA-256)."
            )
        if edge.evidence != edge.provenance.quote:
            raise ValueError("Extracted edge evidence must equal its provenance quote.")
        for endpoint in (edge.source, edge.target):
            if not mentions_name(edge.provenance.quote, entities[endpoint].name):
                raise ValueError(
                    "Extracted edge evidence must explicitly mention both endpoint entities."
                )
    elif edge.origin == "human":
        if edge.provenance is not None:
            raise ValueError(
                "Human-asserted edges must not carry extraction provenance; "
                "record the human rationale in evidence instead."
            )
        if not edge.evidence.strip():
            raise ValueError("Human-asserted edges require an attribution note in evidence.")


class KnowledgeGraph:
    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.edges: list[Edge] = []
        self.adj: dict[str, list[Edge]] = defaultdict(list)
        #: Edges a human retracted or corrected. Imports skip incoming edges that
        #: equal a retracted edge so re-extraction cannot undo a human correction.
        self.retracted_edges: list[Edge] = []

    def add_entity(self, entity: Entity) -> None:
        if not isinstance(entity, Entity):
            raise TypeError("entity must be an Entity.")
        if any(
            not isinstance(v, str) or not v.strip() for v in (entity.id, entity.kind, entity.name)
        ):
            raise ValueError("Entity ID, kind and name must be non-empty strings.")
        if not isinstance(entity.description, str):
            raise TypeError("Entity description must be a string.")
        if entity.id in self.entities:
            raise ValueError("Duplicate entity ID.")
        self.entities[entity.id] = entity

    def add_edge(self, edge: Edge) -> None:
        if not isinstance(edge, Edge):
            raise TypeError("edge must be an Edge.")
        if edge.source not in self.entities or edge.target not in self.entities:
            raise ValueError("Both edge endpoints must exist.")
        if not isinstance(edge.relation, str) or not edge.relation.strip():
            raise ValueError("Relation must be non-empty text.")
        if not isinstance(edge.evidence, str):
            raise TypeError("Edge evidence must be a string.")
        check_edge_evidence(edge, self.entities)
        self.edges.append(edge)
        self.adj[edge.source].append(edge)

    def remove_edge(self, edge: Edge) -> None:
        """Remove the first occurrence of ``edge`` (raises ``ValueError`` if absent)."""
        self.edges.remove(edge)
        self.adj[edge.source].remove(edge)

    def correct_edge(
        self,
        edge: Edge,
        *,
        note: str,
        relation: str | None = None,
        source: str | None = None,
        target: str | None = None,
    ) -> Edge:
        """Replace ``edge`` with a human-asserted correction.

        The correction never inherits the replaced edge's extraction provenance:
        it is stored with ``origin="human"``, ``provenance=None`` and ``note`` as
        its evidence. The replacement is validated before the original is removed.
        """
        if edge not in self.edges:
            raise ValueError("Edge to correct is not in the graph.")
        corrected = Edge(
            source=edge.source if source is None else source,
            relation=edge.relation if relation is None else relation,
            target=edge.target if target is None else target,
            evidence=note if isinstance(note, str) else "",
            origin="human",
            provenance=None,
        )
        if corrected.source not in self.entities or corrected.target not in self.entities:
            raise ValueError("Both edge endpoints must exist.")
        if not isinstance(corrected.relation, str) or not corrected.relation.strip():
            raise ValueError("Relation must be non-empty text.")
        check_edge_evidence(corrected, self.entities)
        self.remove_edge(edge)
        self.add_edge(corrected)
        self.retracted_edges.append(edge)
        return corrected

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
        terms = _tokens(query)
        if not terms:
            return []
        scored = []
        for entity in self.entities.values():
            text = f"{entity.name} {entity.description}".casefold()
            score = sum(term in text for term in terms)
            scored.append((score, entity))
        ordered = sorted(scored, key=lambda item: (-item[0], item[1].id))
        return [entity for score, entity in ordered if score > 0][:top_k]

    def resolve(self, query: str, top_k: int = 5):
        """Resolve likely entity identities through the canonical resolution module."""
        from knowledge_twin.resolution import resolve_entity

        return resolve_entity(
            query,
            list(self.entities.values()),
            min_score=0.0,
            limit=top_k,
        )

    def resolve_one(
        self,
        query: str,
        *,
        kind: str | None = None,
        min_score: float = 0.82,
        min_margin: float = 0.08,
    ):
        """Resolve a single entity only when the identity is not ambiguous."""
        from knowledge_twin.resolution import resolve_unique_entity

        return resolve_unique_entity(
            query,
            list(self.entities.values()),
            min_score=min_score,
            min_margin=min_margin,
            kind=kind,
        )

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
