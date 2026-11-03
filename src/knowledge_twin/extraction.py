from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib import parse as urlparse
from urllib import request

from knowledge_twin.graph import (
    Edge,
    Entity,
    EvidenceSpan,
    KnowledgeGraph,
    mentions_name,
    sha256_text,
)
from knowledge_twin.quality import GraphQuality, analyze_graph


@dataclass(frozen=True, slots=True)
class GraphExtraction:
    graph: KnowledgeGraph
    quality: GraphQuality
    source_length: int


@dataclass(slots=True)
class OpenAICompatibleGraphExtractor:
    """Turn source text into an evidence-anchored graph using a configured model."""

    base_url: str
    model: str
    api_key: str = ""
    timeout_seconds: float = 60.0
    max_entities: int = 100
    max_edges: int = 300

    def __post_init__(self) -> None:
        if not self.base_url.strip() or not self.model.strip():
            raise ValueError("base_url and model are required.")
        parsed = urlparse.urlsplit(self.base_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            # urllib also opens file:// and ftp:// URLs; only HTTP(S) endpoints are valid.
            raise ValueError("base_url must be an http(s) URL with a host.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if self.max_entities <= 0 or self.max_edges <= 0:
            raise ValueError("graph limits must be positive.")

    def extract(self, text: str, *, document_id: str | None = None) -> GraphExtraction:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("source text must be non-empty.")
        if len(text) > 200_000:
            raise ValueError("source text exceeds 200000 characters.")

        system = (
            "Extract an evidence-grounded knowledge graph. Return only JSON with arrays "
            "'entities' and 'edges'. Every entity needs id, kind, name, description. Every "
            "edge needs source, relation, target, evidence. Evidence MUST be a verbatim "
            "substring from the supplied source text that directly supports the relation. "
            "Do not invent entities or relationships."
        )
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        req = request.Request(endpoint, data=payload, headers=headers, method="POST")
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode())
        raw = str(body["choices"][0]["message"]["content"]).strip()
        return self.parse(text, raw, document_id=document_id)

    def parse(
        self, source_text: str, raw_json: str, *, document_id: str | None = None
    ) -> GraphExtraction:
        """Validate model output and anchor every edge to a span of ``source_text``.

        Each accepted edge is stored with ``origin="extracted"`` and an
        :class:`EvidenceSpan` (``document_id``, character span and the SHA-256
        of ``source_text``). ``document_id`` defaults to ``"sha256:<digest>"``.
        """
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as error:
            raise ValueError("Graph extractor returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise TypeError("Graph JSON must be an object with entities and edges arrays.")

        entities = payload.get("entities")
        edges = payload.get("edges")
        if not isinstance(entities, list) or not isinstance(edges, list):
            raise TypeError("Graph JSON must contain entities and edges arrays.")
        if len(entities) > self.max_entities or len(edges) > self.max_edges:
            raise ValueError("Extracted graph exceeds configured limits.")

        graph = KnowledgeGraph()
        entity_names: dict[str, str] = {}
        for item in entities:
            if not isinstance(item, dict):
                raise TypeError("Each entity must be an object.")
            entity = Entity(
                id=str(item.get("id", "")).strip(),
                kind=str(item.get("kind", "")).strip(),
                name=str(item.get("name", "")).strip(),
                description=str(item.get("description", "")).strip(),
            )
            graph.add_entity(entity)
            entity_names[entity.id] = entity.name

        doc_id = document_id
        for item in edges:
            if not isinstance(item, dict):
                raise TypeError("Each edge must be an object.")
            evidence = str(item.get("evidence", "")).strip()
            source_id = str(item.get("source", "")).strip()
            target_id = str(item.get("target", "")).strip()
            if not evidence:
                raise ValueError("Every extracted relationship requires evidence.")
            span = _locate(source_text, evidence)
            if span is None:
                raise ValueError("Relationship evidence must be a verbatim source substring.")
            if source_id not in entity_names or target_id not in entity_names:
                raise ValueError("Relationship endpoints must reference extracted entities.")
            if not (
                mentions_name(evidence, entity_names[source_id])
                and mentions_name(evidence, entity_names[target_id])
            ):
                raise ValueError(
                    "Relationship evidence must explicitly mention both endpoint entities."
                )
            if doc_id is None:
                doc_id = "sha256:" + sha256_text(source_text)
            provenance = EvidenceSpan.from_source(doc_id, source_text, *span)
            graph.add_edge(
                Edge(
                    source=source_id,
                    relation=str(item.get("relation", "")).strip(),
                    target=target_id,
                    evidence=provenance.quote,
                    origin="extracted",
                    provenance=provenance,
                )
            )

        return GraphExtraction(
            graph=graph,
            quality=analyze_graph(graph),
            source_length=len(source_text),
        )


def _locate(source_text: str, evidence: str) -> tuple[int, int] | None:
    """Character span of ``evidence`` in ``source_text`` (exact first, then case-insensitive)."""
    start = source_text.find(evidence)
    if start >= 0:
        return start, start + len(evidence)
    match = re.search(re.escape(evidence), source_text, flags=re.IGNORECASE)
    return match.span() if match else None
