import json
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from knowledge_twin.contracts import capabilities, run_operation
from knowledge_twin.graph import EvidenceSpan

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "makma.v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

TEXT = "Synthetic memo. MAKMA uses the RAG Engine. The RAG Engine depends on Postgres."
ENTITIES = [
    {"id": "makma", "kind": "system", "name": "MAKMA"},
    {"id": "rag", "kind": "service", "name": "RAG Engine"},
    {"id": "pg", "kind": "database", "name": "Postgres"},
]


def check(envelope: dict) -> dict:
    VALIDATOR.validate(envelope)
    assert envelope["system"] == "knowledge-twin"
    assert envelope["execution_mode"] == "deterministic_offline"
    datetime.fromisoformat(envelope["started_at"])
    json.dumps(envelope)  # JSON-serializable
    return envelope


def extracted_graph() -> dict:
    result = check(
        run_operation("extract", {"text": TEXT, "document_id": "memo", "entities": ENTITIES})
    )
    return {"entities": ENTITIES, "edges": result["data"]["candidate_edges"]}


def test_vendored_schema_is_a_valid_json_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)


def test_capabilities_declare_real_operations() -> None:
    caps = capabilities()
    assert caps["contract_version"] == "makma.v1" and caps["system"] == "knowledge-twin"
    names = [op["name"] for op in caps["operations"]]
    assert names == ["extract", "import_graph", "query_path", "validate_graph"]
    for op in caps["operations"]:
        Draft202012Validator.check_schema(op["input_schema"])
        assert op["side_effects"] is False and op["requires_approval"] is False


def test_extract_envelope_has_hash_backed_provenance() -> None:
    envelope = check(
        run_operation(
            "extract",
            {"text": TEXT, "document_id": "memo", "entities": ENTITIES},
            run_id="run-1",
            correlation_id="corr-1",
        )
    )
    assert envelope["status"] == "ok" and envelope["error"] is None
    assert envelope["run_id"] == "run-1" and envelope["correlation_id"] == "corr-1"
    document, *chunks = envelope["provenance"]
    assert document == {
        "kind": "document",
        "id": "memo",
        "sha256": EvidenceSpan.from_source("memo", TEXT, 0, 1).source_sha256,
        "span": None,
        "uri": None,
    }
    assert len(chunks) == 2
    for chunk, edge in zip(chunks, envelope["data"]["candidate_edges"], strict=True):
        start, end = chunk["span"]
        assert TEXT[start:end] == edge["evidence"]


def test_import_query_and_validate_round_trip() -> None:
    graph = extracted_graph()
    imported = check(run_operation("import_graph", {"incoming": graph, "import_id": "i1"}))
    assert imported["status"] == "ok"
    assert imported["data"]["version"] == 1
    assert imported["provenance"][0]["kind"] == "dataset"

    merged = imported["data"]["graph"]
    path = check(
        run_operation("query_path", {"graph": merged, "source": "makma", "target": "pg"})
    )
    assert path["data"]["found"] and path["data"]["length"] == 2
    assert [p["kind"] for p in path["provenance"]] == ["dataset", "chunk", "chunk"]

    report = check(
        run_operation("validate_graph", {"graph": merged, "documents": {"memo": TEXT}})
    )
    assert report["data"]["ok"] is True


def test_validate_reports_problems_as_data_not_errors() -> None:
    graph = extracted_graph()
    graph["edges"].append({"source": "makma", "relation": "X", "target": "ghost"})
    envelope = check(run_operation("validate_graph", {"graph": graph}))
    assert envelope["status"] == "ok"
    assert envelope["data"]["ok"] is False
    assert "DANGLING_EDGE" in {issue["code"] for issue in envelope["data"]["issues"]}


def test_strict_import_conflict_is_an_error_envelope() -> None:
    base = extracted_graph()
    incoming = {"entities": [{"id": "pg", "kind": "database", "name": "MySQL"}]}
    envelope = check(
        run_operation(
            "import_graph",
            {"base": base, "base_version": 3, "incoming": incoming, "import_id": "i2"},
        )
    )
    assert envelope["status"] == "error" and envelope["data"] is None
    assert envelope["error"]["code"] == "IMPORT_CONFLICT"
    report = envelope["error"]["details"]["report"]
    assert report["base_version"] == 3 and report["applied"] is False

    stale = check(
        run_operation(
            "import_graph",
            {"base": base, "base_version": 3, "incoming": {}, "import_id": "i3",
             "expected_version": 2},
        )
    )
    assert stale["error"]["code"] == "VERSION_CONFLICT"


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("extract", {"text": TEXT, "entities": ENTITIES}),
        ("extract", {"text": "", "document_id": "d", "entities": ENTITIES}),
        ("extract", {"text": TEXT, "document_id": "d", "entities": [{"id": "x"}]}),
        ("extract", {"text": TEXT, "document_id": "d", "entities": [], "extra": 1}),
        ("import_graph", {"incoming": {"entities": "nope"}, "import_id": "i"}),
        ("import_graph", {"incoming": {}, "import_id": "i", "strict": "yes"}),
        ("query_path", {"graph": {}, "source": "a", "target": 1}),
        ("query_path", {"graph": {}, "source": "a", "target": "b", "max_depth": True}),
        ("query_path", {"graph": {"edges": [{"source": "a"}]}, "source": "a", "target": "b"}),
        ("validate_graph", {"graph": [], "documents": {}}),
        ("validate_graph", {"graph": {}, "documents": {"d": 1}}),
    ],
)
def test_invalid_input_envelopes(operation: str, payload: dict) -> None:
    envelope = check(run_operation(operation, payload))
    assert envelope["status"] == "error"
    assert envelope["error"]["code"] == "INVALID_INPUT"
    assert envelope["data"] is None and envelope["provenance"] == []


def test_non_object_payload_and_unknown_endpoint() -> None:
    assert check(run_operation("extract", []))["error"]["code"] == "INVALID_INPUT"  # type: ignore[arg-type]
    missing = check(
        run_operation("query_path", {"graph": {}, "source": "a", "target": "b"})
    )
    assert missing["error"]["code"] == "ENTITY_NOT_FOUND"


@pytest.mark.parametrize("operation", ["summarize", "Extract", "", "x" * 100])
def test_unknown_operation(operation: str) -> None:
    envelope = check(run_operation(operation, {}))
    assert envelope["status"] == "error"
    assert envelope["error"]["code"] == "UNKNOWN_OPERATION"


def test_invalid_run_id_is_rejected_but_envelope_stays_valid() -> None:
    envelope = check(run_operation("validate_graph", {"graph": {}}, run_id="x" * 200))
    assert envelope["error"]["code"] == "INVALID_INPUT"
    assert len(envelope["run_id"]) == 32


def test_internal_errors_do_not_leak_details(monkeypatch) -> None:
    from knowledge_twin import contracts

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal path /srv/data")

    monkeypatch.setattr(contracts, "validate_graph", boom)
    envelope = check(run_operation("validate_graph", {"graph": {}}))
    assert envelope["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in json.dumps(envelope)
