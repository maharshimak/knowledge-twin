# Production engineering

Knowledge graphs are only useful when their structure and evidence are measurable. `knowledge_twin.quality` adds graph-wide quality diagnostics and a release gate.

The report tracks entity/edge counts, orphan entities, duplicate relationships, evidence coverage and connected components. `assert_graph_quality` can enforce minimum evidence coverage and reject structurally suspicious graphs before they are promoted to a searchable knowledge twin.

## Operational practice

- Attach source evidence to relationships whenever possible.
- Treat duplicate edges as an ingestion/idempotency signal.
- Review unexpected connected-component growth after ingestion jobs.
- Set evidence thresholds per data source rather than hiding missing provenance.
