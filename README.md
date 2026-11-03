# Knowledge Twin

**A MAK'MA Studio Product · MAK'MA Labs**

[Live Product Demo](https://maharshimak.github.io/makma-ai-os/projects/knowledge-twin/) · [MAK'MA Labs](https://maharshimak.github.io/makma-ai-os/projects/)

Evidence-bearing entity and relationship graph with directed traversal, keyword retrieval and optional SQLite persistence.


## Product contract — engineering upgrade

**Problem and audience:** An evidence-bearing graph inspection tool for engineers examining relationships, identity resolution and data quality.

**Live tool:** https://maharshimak.github.io/makma-ai-os/projects/knowledge-twin/

**Implemented browser workflow:** Editable entities/edges, explicit resolution threshold, top candidates, separate keyword search, directed BFS and shortest paths, node/evidence inspection, orphan/duplicate/coverage/component audit and JSON export.

**Backend and parity contract:** Python now rejects duplicate IDs, blank entities/relations and fractional traversal depth, and provides shortest_path. Browser fuzzy matching is normalized Levenshtein plus Jaccard; Python uses SequenceMatcher plus Jaccard. Scores are explicitly mode-specific; neither is an AI probability.

**Architecture:** `makma-ai-os/demo` is the shared web product source and Pages deployment. This repository owns its Python domain package. The central `tests/e2e` suite exercises all nine products; `tests/fixtures/python-parity.json` plus `scripts/generate_parity.py` guard shared mathematical contracts. Backend revisions used for regeneration are pinned in the central `backend-lock.json`.

**Safety and limitations:** SQLite persistence is available, but there is no dedicated graph database, automatic entity ingestion, semantic embedding pipeline or ontology inference. Graph evidence is supplied by the user, not externally verified. Browser caps: 200 entities and 1000 relationships. Inputs are validated, rendered user values are escaped, and deterministic results are not presented as model inference.

**Verification:** Run `python -m ruff check .` and `python -m pytest -q`. `tests/test_engineering_upgrade.py` protects the new rejection/correctness paths. Central web checks: `npm ci`, `npm test`, `npm run build`, `npx playwright install --with-deps chromium`, `npm run test:e2e`. CI gates publishing on browser interactions and validates all public URLs after deployment.

**Grounded graph extraction:** the optional OpenAI-compatible extractor builds entities and relationships from source text but rejects any relationship whose evidence is not a verbatim substring of the source, preserving an explicit anti-hallucination boundary. Accepted relationships are stored as `extracted` edges with the matching source span and the SHA-256 of the source text.

**Highest-value next work:** A human review workflow for import ambiguity candidates, and storage-level optimistic concurrency (open PR #12).

**Provenance:** Independent MAK’MA Studio engineering implementation; examples are synthetic and no employer code or data is included. Existing MIT license applies.


## Implemented now

- Typed entities and directed edges with evidence strings.
- Edge origin (`unspecified`, `extracted`, `human`). Extracted edges must carry an `EvidenceSpan`: document id, character span, SHA-256 of the full source text and the quoted slice, which must name both endpoints as whole words. Human edges must not carry extraction evidence; `correct_edge` replaces an edge with a human assertion and records the original as retracted so re-imports cannot undo it.
- Endpoint validation and breadth-first neighborhood traversal with cycle handling.
- Directed shortest-path explanations (`explain_path`) that return each hop with its evidence, with optional relation/origin filters and a depth limit.
- Keyword/sub-string matching over names and descriptions; explicit traversal input validation.
- Entity resolution that refuses ambiguous matches (`resolve_unique_entity`).
- Versioned, conflict-aware imports (`VersionedGraph.import_graph`): strict all-or-nothing or partial merges, entity field conflicts reported and never overwritten, similar names reported as candidates and never merged, exact duplicate edges skipped, invalid edges rejected with a reason.
- Graph integrity validator (`validate_graph`): dangling edges, self-loops (policy flag), exact duplicate edges, repeated relationships, blank relations, origin/evidence policy, adjacency drift, provenance hash/span mismatch against supplied documents, same-name entities.
- Deterministic rule-based candidate extraction (`extract_candidates`) from caller-supplied entity names and a relation-phrase lexicon; ambiguous surface forms are reported, not linked.
- JSON serialization (`graph_to_dict` / `graph_from_dict`) and optional SQLite persistence that round-trip origin, provenance and retracted edges; older databases are migrated in place.

## Scope and limitations

There is no trained semantic retrieval or dedicated graph database. The rule-based extractor is pattern matching over caller-supplied names: direction follows text order (passive voice is not handled), only consecutive mentions within one sentence are linked, and aliases or pronouns are not recognised. The optional model extractor needs a configured OpenAI-compatible endpoint; tests exercise only its offline `parse` path. Search uses substring matches and insertion-order ties. Duplicate entity IDs are rejected. Evidence hashes prove that an edge's quote is a slice of a specific text; they do not prove the text is true. Spans are Python code-point offsets. Canonical-name comparison currently drops non-Latin scripts (addressed separately in PR #13); such names are excluded from ambiguity candidates rather than matched by accident.

## `makma.v1` operations

`knowledge_twin.contracts.run_operation(operation, payload, *, run_id=None, correlation_id=None)` returns the shared `makma.v1` envelope (schema vendored at `contracts/makma.v1.schema.json`); `capabilities()` lists the operations and their input schemas. All operations are pure, offline and rule-based, so `execution_mode` is always `deterministic_offline`. Pydantic is not a dependency of this package, so the envelope is a validated frozen dataclass.

| Operation | Input | `data` | Provenance |
| --- | --- | --- | --- |
| `extract` | `text`, `document_id`, `entities`, optional `relation_patterns` | mentions, ambiguous mentions, candidate edges with evidence spans, skipped pairs with reasons | the document (SHA-256 of the text) and one `chunk` per candidate edge span |
| `import_graph` | `incoming` graph, `import_id`, optional `base` graph, `base_version`, `strict` (default true), `expected_version` | merge report, new version, merged graph | `dataset` with the canonical-JSON SHA-256 of the incoming payload |
| `query_path` | `graph`, `source`, `target`, optional `max_depth`, `relations`, `origins` | found, length, reason, hops with evidence | graph payload hash and one `chunk` per evidenced hop |
| `validate_graph` | `graph`, optional `allow_self_loops`, `documents` | ok, error/warning counts, issues | graph payload hash |

Error codes: `UNKNOWN_OPERATION`, `INVALID_INPUT`, `ENTITY_NOT_FOUND`, `IMPORT_CONFLICT` (strict import blocked; the merge report is in `error.details`), `VERSION_CONFLICT`, `INTERNAL_ERROR` (no internal details exposed).

## Installation and development

Requires Python 3.12 or newer. Run from this project directory.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
python -m pip wheel --no-deps . -w dist
```

On Windows, activate with `.venv\Scripts\Activate.ps1`.

## Library usage

```python
from knowledge_twin.graph import KnowledgeGraph, Entity, Edge
graph = KnowledgeGraph()
graph.add_entity(Entity("rag", "system", "RAG", "retrieval augmented generation"))
graph.add_entity(Entity("index", "component", "Index", "document retrieval"))
graph.add_edge(Edge("rag", "USES", "index", "Synthetic architecture example"))
print(graph.neighborhood("rag"))
print(graph.search("retrieval"))
```

Evidence-backed extraction, validation and path explanation:

```python
from knowledge_twin import (
    Entity, KnowledgeGraph, explain_path, extract_candidates, validate_graph,
)

text = "Synthetic note. MAKMA uses the RAG Engine. The RAG Engine depends on Postgres."
entities = [Entity("makma", "system", "MAKMA"), Entity("rag", "service", "RAG Engine"),
            Entity("pg", "database", "Postgres")]
result = extract_candidates(text, document_id="note-1", entities=entities)

graph = KnowledgeGraph()
for entity in entities:
    graph.add_entity(entity)
for edge in result.candidate_edges:
    graph.add_edge(edge)

print(validate_graph(graph, documents={"note-1": text}).ok)
print(explain_path(graph, "makma", "pg").to_dict()["hops"])
```

## Configuration

Configuration is supplied through Python function/constructor arguments. No credentials or environment file are needed for the offline example.

## Container

```bash
docker build -t knowledge-twin .
docker run --rm knowledge-twin
```

## Repository structure

| Path | Purpose |
| --- | --- |
| `src/knowledge_twin/` | Implementation |
| `tests/` | Offline unit and regression tests |
| `docs/DESIGN.md` | Architecture and trust boundaries |
| `.github/workflows/ci.yml` | Install, lint, tests, wheel and container build |
| `pyproject.toml` | Dependencies and package configuration |

## Next engineering work

Human review workflow for ambiguity candidates; alias-aware extraction; tokenized/embedding retrieval. These are planned work, not current capabilities.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). CI runs on every push and pull request through `.github/workflows/ci.yml`.

## License and provenance

[MIT](LICENSE), copyright 2026 Maharshi Patel. This public portfolio implementation is independent of employer systems and contains no confidential employer code or data. Examples and test fixtures are synthetic.
