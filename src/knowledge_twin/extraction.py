from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import request

from knowledge_twin.graph import Edge, Entity, KnowledgeGraph
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
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if self.max_entities <= 0 or self.max_edges <= 0:
            raise ValueError("graph limits must be positive.")

    def extract(self, text: str) -> GraphExtraction:
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
        return self.parse(text, raw)

    def parse(self, source_text: str, raw_json: str) -> GraphExtraction:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as error:
            raise ValueError("Graph extractor returned invalid JSON.") from error

        entities = payload.get("entities")
        edges = payload.get("edges")
        if not isinstance(entities, list) or not isinstance(edges, list):
            raise ValueError("Graph JSON must contain entities and edges arrays.")
        if len(entities) > self.max_entities or len(edges) > self.max_edges:
            raise ValueError("Extracted graph exceeds configured limits.")

        graph = KnowledgeGraph()
        for item in entities:
            if not isinstance(item, dict):
                raise ValueError("Each entity must be an object.")
            graph.add_entity(
                Entity(
                    id=str(item.get("id", "")).strip(),
                    kind=str(item.get("kind", "")).strip(),
                    name=str(item.get("name", "")).strip(),
                    description=str(item.get("description", "")).strip(),
                )
            )

        source_casefold = source_text.casefold()
        for item in edges:
            if not isinstance(item, dict):
                raise ValueError("Each edge must be an object.")
            evidence = str(item.get("evidence", "")).strip()
            if not evidence:
                raise ValueError("Every extracted relationship requires evidence.")
            if evidence.casefold() not in source_casefold:
                raise ValueError("Relationship evidence must be a verbatim source substring.")
            graph.add_edge(
                Edge(
                    source=str(item.get("source", "")).strip(),
                    relation=str(item.get("relation", "")).strip(),
                    target=str(item.get("target", "")).strip(),
                    evidence=evidence,
                )
            )

        return GraphExtraction(
            graph=graph,
            quality=analyze_graph(graph),
            source_length=len(source_text),
        )
