# Knowledge Twin

In-memory entity and relationship graph for evidence-bearing edges, directed traversal and keyword retrieval.

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

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). The standalone CI workflow runs after migration; while nested in the profile repository, the parent CI validates this project.

## License and provenance

[MIT](LICENSE), copyright 2026 Maharshi Patel. This public portfolio implementation is independent of employer systems and contains no confidential employer code or data. Examples and test fixtures are synthetic.
