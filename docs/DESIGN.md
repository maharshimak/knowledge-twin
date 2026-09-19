# Design and operating boundaries

In-memory entity and relationship graph for evidence-bearing edges, directed traversal and keyword retrieval.

## Scope

Entities and edges are supplied by the caller. There is no automatic entity extraction, trained semantic retrieval, LLM reasoning or graph database. Search uses substring matches and insertion-order ties. Adding an existing entity ID replaces its record. All graph state is in memory; evidence strings are not independently verified.

## Interfaces

Implementation lives in `src/knowledge_twin/`. Public examples in the README use its Python API. This project is a library, without a service layer.

## Validation

Tests include synthetic regression fixtures. Package and container checks verify installation separately from source-tree imports. Tests do not certify general model quality, clinical correctness or multi-tenant isolation.

## Planned evolution

Graph serialization; evidence provenance validation; tokenized/embedding retrieval; entity resolution; model-assisted extraction.
