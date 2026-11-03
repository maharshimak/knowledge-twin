# Changelog

All notable engineering changes to this repository are documented here.

The format follows the intent of [Keep a Changelog](https://keepachangelog.com/) and uses semantic versioning principles where releases are created.

## [Unreleased]

### Added
- Edge `origin` and `EvidenceSpan` provenance (document id, span, source SHA-256); extracted edges without attributable evidence are rejected and human corrections never inherit extraction evidence.
- `VersionedGraph.import_graph` with conflict-aware merge reports, ambiguity candidates and retraction-aware re-imports.
- `validate_graph` integrity validator and `explain_path` evidence-carrying path explanations.
- Deterministic rule-based `extract_candidates`, JSON graph serialization, and the `makma.v1` contract (`extract`, `import_graph`, `query_path`, `validate_graph`).

### Fixed
- Non-string entity descriptions and edge evidence are rejected (previously broke search, quality analysis and SQLite saves).
- `analyze_graph` reports dangling edges instead of raising `KeyError`.
- The model extractor only accepts http(s) base URLs, raises `TypeError` for non-object JSON, and checks endpoint mentions on word boundaries.

### Engineering
- Added repository ownership and structured contribution workflows.
- Added Dependabot coverage for Python and GitHub Actions dependencies.
- Added issue and pull-request templates focused on reproducibility, validation, risk, and rollback.
- Added consistent editor configuration and engineering standards.

## Release policy

A release should describe user-visible behavior, compatibility notes, validation evidence, and any migration or rollback requirements. Repository history remains the source of truth for individual commits.
