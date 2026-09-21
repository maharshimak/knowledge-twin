# Knowledge Twin

**A MAK'MA Studio Product · MAK'MA Labs**

[Live Product Demo](https://maharshimak.github.io/makma-ai-os/projects/knowledge-twin/) · [MAK'MA Labs](https://maharshimak.github.io/makma-ai-os/projects/)

In-memory entity and relationship graph for evidence-bearing edges, directed traversal and keyword retrieval.


## Product contract — engineering upgrade

**Problem and audience:** An evidence-bearing graph inspection tool for engineers examining relationships, identity resolution and data quality.

**Live tool:** https://maharshimak.github.io/makma-ai-os/projects/knowledge-twin/

**Implemented browser workflow:** Editable entities/edges, explicit resolution threshold, top candidates, separate keyword search, directed BFS and shortest paths, node/evidence inspection, orphan/duplicate/coverage/component audit and JSON export.

**Backend and parity contract:** Python now rejects duplicate IDs, blank entities/relations and fractional traversal depth, and provides shortest_path. Browser fuzzy matching is normalized Levenshtein plus Jaccard; Python uses SequenceMatcher plus Jaccard. Scores are explicitly mode-specific; neither is an AI probability.

**Architecture:** `makma-ai-os/demo` is the shared web product source and Pages deployment. This repository owns its Python domain package. The central `tests/e2e` suite exercises all nine products; `tests/fixtures/python-parity.json` plus `scripts/generate_parity.py` guard shared mathematical contracts. Backend revisions used for regeneration are pinned in the central `backend-lock.json`.

**Safety and limitations:** No graph database, automatic entity ingestion or ontology inference. Graph evidence is supplied by the user, not externally verified. Browser caps: 200 entities and 1000 relationships. Inputs are validated, rendered user values are escaped, and deterministic results are not presented as model inference.

**Verification:** Run `python -m ruff check .` and `python -m pytest -q`. `tests/test_engineering_upgrade.py` protects the new rejection/correctness paths. Central web checks: `npm ci`, `npm test`, `npm run build`, `npx playwright install --with-deps chromium`, `npm run test:e2e`. CI gates publishing on browser interactions and validates all public URLs after deployment.

**Highest-value next work:** Versioned graph imports, provenance sources and conflict-aware human entity merging.

**Provenance:** Independent MAK’MA Studio engineering implementation; examples are synthetic and no employer code or data is included. Existing MIT license applies.


## Implemented now

- Typed entities and directed edges with evidence strings.
- Endpoint validation and breadth-first neighborhood traversal with cycle handling.
- Keyword/sub-string matching over names and descriptions; explicit traversal input validation.

## Scope and limitations

Entities and edges are supplied by the caller. There is no automatic entity extraction, trained semantic retrieval, LLM reasoning or graph database. Search uses substring matches and insertion-order ties. Adding an existing entity ID replaces its record. All graph state is in memory; evidence strings are not independently verified.

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

Graph serialization; evidence provenance validation; tokenized/embedding retrieval; entity resolution; model-assisted extraction. These are planned work, not current capabilities.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). CI runs on every push and pull request through `.github/workflows/ci.yml`.

## License and provenance

[MIT](LICENSE), copyright 2026 Maharshi Patel. This public portfolio implementation is independent of employer systems and contains no confidential employer code or data. Examples and test fixtures are synthetic.
