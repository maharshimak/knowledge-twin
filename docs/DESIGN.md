# Design and operating boundaries

In-memory entity and relationship graph for evidence-bearing edges, directed traversal and keyword retrieval.

## Scope

Entities and edges are supplied by the caller, by the deterministic rule-based extractor (`rule_extraction.py`, gazetteer + relation-phrase lexicon) or by the optional OpenAI-compatible model extractor. There is no trained semantic retrieval or graph database. Search uses substring matches and insertion-order ties. Adding an existing entity ID is rejected. Graph state is in memory unless saved through `SQLiteGraphStore`.

## Evidence and origin invariants

- `Edge.origin` is one of `unspecified` (legacy default), `extracted` or `human`.
- `extracted` edges must carry an `EvidenceSpan` (document id, code-point span, SHA-256 of the full UTF-8 source text, quote). The edge evidence must equal the quote, and the quote must mention both endpoint entity names as whole words. Edges violating this are rejected by `KnowledgeGraph.add_edge`, by `graph_from_dict`, by imports and by the validator.
- `human` edges must not carry an `EvidenceSpan` and need a non-empty attribution note. `KnowledgeGraph.correct_edge` replaces an edge with a human edge and records the original in `retracted_edges`; imports skip incoming edges equal to a retracted edge, so re-extraction cannot silently undo a correction.
- `EvidenceSpan.verify(text)` re-hashes a supplied document and compares the span. Hashing proves the evidence is a slice of that exact text; it does not prove the text is true.

## Entity identity

Entities with different IDs are never merged automatically. Imports report possible duplicates (same kind, similarity above a threshold) as `ambiguity_candidates`; the validator reports same-kind entities sharing a canonical name as `AMBIGUOUS_ENTITY_NAME` warnings. Names whose canonical form is empty are never offered as candidates (non-Latin canonicalization is addressed separately in PR #13).

## Imports

`VersionedGraph.import_graph` computes a merge report (added / unchanged / conflicting entities, ambiguity candidates, added / duplicate / suppressed / rejected edges) and the canonical-JSON SHA-256 of the payload. Strict imports are all-or-nothing; non-strict imports apply the non-conflicting parts. Conflicting entity fields never overwrite existing values. The version increments only when something is applied, and `expected_version` rejects stale imports.

## Interfaces

Implementation lives in `src/knowledge_twin/`. Public examples in the README use its Python API. This project is a library, without an HTTP service layer. `knowledge_twin.contracts` exposes the operations through the shared `makma.v1` envelope for in-process callers.

## Validation

Tests include synthetic regression fixtures. Package and container checks verify installation separately from source-tree imports. Tests do not certify general model quality, clinical correctness or multi-tenant isolation.

## Planned evolution

Human review workflow for ambiguity candidates; tokenized/embedding retrieval; storage-level optimistic concurrency (PR #12).
