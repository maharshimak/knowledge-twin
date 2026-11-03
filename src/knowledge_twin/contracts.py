"""``makma.v1`` execution contract for Knowledge Twin.

Pydantic is not a dependency of this package, so the envelope is a frozen
dataclass with explicit validation in ``__post_init__``. Compatibility with the
shared JSON Schema (``contracts/makma.v1.schema.json``) is enforced by tests.

Every operation here is deterministic, rule-based and offline; none calls a
model, so ``execution_mode`` is always ``deterministic_offline``.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from typing import Any

from knowledge_twin.graph import EDGE_ORIGINS, Edge
from knowledge_twin.imports import ImportVersionConflict, VersionedGraph
from knowledge_twin.paths import explain_path
from knowledge_twin.rule_extraction import MAX_SOURCE_CHARS, extract_candidates
from knowledge_twin.serialization import (
    canonical_sha256,
    entity_from_dict,
    graph_from_dict,
    graph_to_dict,
)
from knowledge_twin.validation import validate_graph

CONTRACT_VERSION = "makma.v1"
SYSTEM = "knowledge-twin"
EXECUTION_MODE = "deterministic_offline"
_STATUSES = frozenset({"ok", "error", "blocked", "pending_approval"})
_EXECUTION_MODES = frozenset({"deterministic_offline", "local_model", "remote_model"})
_PROVENANCE_KINDS = frozenset(
    {"document", "chunk", "artifact", "dataset", "model", "query", "record"}
)
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class InvalidInput(ValueError):
    """Payload failed validation; mapped to ``INVALID_INPUT``."""


class OperationError(Exception):
    """Domain failure with a specific error code."""

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True, slots=True)
class Provenance:
    kind: str
    id: str
    sha256: str | None = None
    span: tuple[int, int] | None = None
    uri: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _PROVENANCE_KINDS:
            raise ValueError(f"provenance kind must be one of {sorted(_PROVENANCE_KINDS)}")
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("provenance id must be non-empty text")
        if self.sha256 is not None and not _HEX64.match(self.sha256):
            raise ValueError("provenance sha256 must be 64 lowercase hex characters")
        if self.span is not None and (
            len(self.span) != 2 or any(type(v) is not int or v < 0 for v in self.span)
        ):
            raise ValueError("provenance span must be two non-negative integers")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "sha256": self.sha256,
            "span": list(self.span) if self.span is not None else None,
            "uri": self.uri,
        }


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: str
    message: str
    retryable: bool = False
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _ERROR_CODE_RE.match(self.code):
            raise ValueError("error code must be UPPER_SNAKE")
        if len(self.message) > 2000:
            raise ValueError("error message is limited to 2000 characters")


@dataclass(frozen=True, slots=True)
class Envelope:
    operation: str
    run_id: str
    correlation_id: str
    trace_id: str
    span_id: str
    status: str
    started_at: str
    duration_ms: float
    data: Any = None
    error: ErrorInfo | None = None
    provenance: tuple[Provenance, ...] = ()
    policy: dict | None = None
    execution_mode: str = EXECUTION_MODE
    contract_version: str = CONTRACT_VERSION
    system: str = SYSTEM

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError("invalid status")
        if self.execution_mode not in _EXECUTION_MODES:
            raise ValueError("invalid execution_mode")
        if (self.status == "ok") != (self.error is None):
            raise ValueError("status 'ok' requires error=None and vice versa")
        if self.status in {"error", "blocked"} and self.data is not None:
            raise ValueError("error/blocked envelopes must have data=None")
        if self.status == "pending_approval" and (
            not self.policy or self.policy.get("decision") != "requires_approval"
        ):
            raise ValueError("pending_approval requires policy.decision == 'requires_approval'")
        for value in (self.run_id, self.correlation_id):
            if not isinstance(value, str) or not 1 <= len(value) <= 128:
                raise ValueError("run_id and correlation_id must be 1..128 characters")
        if not re.fullmatch(r"[0-9a-f]{32}", self.trace_id) or not re.fullmatch(
            r"[0-9a-f]{16}", self.span_id
        ):
            raise ValueError("trace_id/span_id must be lowercase hex of length 32/16")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    def to_dict(self) -> dict:
        return {
            "contract_version": self.contract_version,
            "system": self.system,
            "operation": self.operation,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "data": self.data,
            "error": asdict(self.error) if self.error is not None else None,
            "provenance": [item.to_dict() for item in self.provenance],
            "policy": self.policy,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
        }


# --------------------------------------------------------------------------- inputs

_GRAPH_SCHEMA: dict = {
    "type": "object",
    "description": "Serialized graph (format knowledge-twin.graph.v1).",
    "properties": {
        "format": {"const": "knowledge-twin.graph.v1"},
        "entities": {"type": "array", "items": {"type": "object"}},
        "edges": {"type": "array", "items": {"type": "object"}},
        "retracted_edges": {"type": "array", "items": {"type": "object"}},
    },
}

_ENTITY_SCHEMA: dict = {
    "type": "object",
    "required": ["id", "kind", "name"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "kind": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
    },
}


def _require(payload: dict, key: str, kind: type | tuple[type, ...], *, optional: bool = False):
    if key not in payload or payload[key] is None:
        if optional:
            return None
        raise InvalidInput(f"'{key}' is required")
    value = payload[key]
    if isinstance(value, bool) and bool not in (kind if isinstance(kind, tuple) else (kind,)):
        raise InvalidInput(f"'{key}' has the wrong type")
    if not isinstance(value, kind):
        raise InvalidInput(f"'{key}' has the wrong type")
    return value


def _check_keys(payload: dict, allowed: set[str]) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise InvalidInput(f"unknown field(s): {sorted(unknown)}")


def _load_graph(raw: Any, *, enforce: bool):
    try:
        return graph_from_dict(raw, enforce=enforce)
    except (TypeError, ValueError) as error:
        raise InvalidInput(f"invalid graph: {error}") from error


def _edge_provenance(edge: Edge) -> Provenance | None:
    if edge.provenance is None:
        return None
    return Provenance(
        kind="chunk",
        id=edge.provenance.document_id,
        sha256=edge.provenance.source_sha256,
        span=(edge.provenance.start, edge.provenance.end),
    )


# ----------------------------------------------------------------------- operations

OpResult = tuple[dict, list[Provenance]]


def _op_extract(payload: dict) -> OpResult:
    _check_keys(payload, {"text", "document_id", "entities", "relation_patterns"})
    text = _require(payload, "text", str)
    document_id = _require(payload, "document_id", str)
    raw_entities = _require(payload, "entities", list)
    patterns = _require(payload, "relation_patterns", dict, optional=True)
    try:
        entities = [entity_from_dict(item) for item in raw_entities]
        result = extract_candidates(
            text, document_id=document_id, entities=entities, relation_patterns=patterns
        )
    except (TypeError, ValueError) as error:
        raise InvalidInput(str(error)) from error
    provenance = [Provenance(kind="document", id=document_id, sha256=result.source_sha256)]
    provenance.extend(
        item for item in map(_edge_provenance, result.candidate_edges) if item is not None
    )
    return result.to_dict(), provenance


def _op_import_graph(payload: dict) -> OpResult:
    _check_keys(payload, {"base", "base_version", "incoming", "import_id", "strict",
                          "expected_version"})
    incoming = _require(payload, "incoming", dict)
    import_id = _require(payload, "import_id", str)
    strict = _require(payload, "strict", bool, optional=True)
    base_raw = _require(payload, "base", dict, optional=True)
    base_version = _require(payload, "base_version", int, optional=True) or 0
    expected = _require(payload, "expected_version", int, optional=True)
    if base_version < 0:
        raise InvalidInput("'base_version' must be non-negative")
    base = _load_graph(base_raw, enforce=True) if base_raw is not None else None
    repo = VersionedGraph(version=base_version)
    if base is not None:
        repo.graph = base
    try:
        report = repo.import_graph(
            incoming,
            import_id=import_id,
            strict=True if strict is None else strict,
            expected_version=expected,
        )
    except ImportVersionConflict as error:
        raise OperationError(
            "VERSION_CONFLICT", str(error), {"current_version": repo.version}
        ) from error
    except (TypeError, ValueError) as error:
        raise InvalidInput(f"invalid incoming graph: {error}") from error
    if report.strict and report.has_blocking_conflicts:
        raise OperationError(
            "IMPORT_CONFLICT",
            "import was not applied: conflicting entities or rejected edges",
            {"report": report.to_dict()},
        )
    data = {"report": report.to_dict(), "version": repo.version, "graph": graph_to_dict(repo.graph)}
    provenance = [Provenance(kind="dataset", id=import_id, sha256=report.payload_sha256)]
    return data, provenance


def _op_query_path(payload: dict) -> OpResult:
    _check_keys(payload, {"graph", "source", "target", "max_depth", "relations", "origins"})
    graph = _load_graph(_require(payload, "graph", dict), enforce=True)
    source = _require(payload, "source", str)
    target = _require(payload, "target", str)
    max_depth = _require(payload, "max_depth", int, optional=True)
    relations = _require(payload, "relations", list, optional=True)
    origins = _require(payload, "origins", list, optional=True)
    if relations is not None and not all(isinstance(item, str) for item in relations):
        raise InvalidInput("'relations' must be an array of strings")
    if origins is not None and not set(origins) <= EDGE_ORIGINS:
        raise InvalidInput(f"'origins' must be a subset of {sorted(EDGE_ORIGINS)}")
    missing = [node for node in (source, target) if node not in graph.entities]
    if missing:
        raise OperationError("ENTITY_NOT_FOUND", "path endpoint not in graph", {"missing": missing})
    try:
        explanation = explain_path(
            graph, source, target, max_depth=max_depth, relations=relations, origins=origins
        )
    except ValueError as error:
        raise InvalidInput(str(error)) from error
    provenance = [
        Provenance(kind="dataset", id="graph", sha256=canonical_sha256(payload["graph"]))
    ]
    provenance.extend(item for item in map(_edge_provenance, explanation.hops) if item)
    return explanation.to_dict(), provenance


def _op_validate_graph(payload: dict) -> OpResult:
    _check_keys(payload, {"graph", "allow_self_loops", "documents"})
    graph = _load_graph(_require(payload, "graph", dict), enforce=False)
    allow_self_loops = _require(payload, "allow_self_loops", bool, optional=True) or False
    documents = _require(payload, "documents", dict, optional=True)
    if documents is not None and not all(
        isinstance(key, str) and isinstance(value, str) for key, value in documents.items()
    ):
        raise InvalidInput("'documents' must map document ids to source text")
    report = validate_graph(graph, allow_self_loops=allow_self_loops, documents=documents)
    provenance = [
        Provenance(kind="dataset", id="graph", sha256=canonical_sha256(payload["graph"]))
    ]
    return report.to_dict(), provenance


@dataclass(frozen=True, slots=True)
class _Operation:
    name: str
    handler: Callable[[dict], OpResult]
    input_schema: dict
    timeout_s: int = 30
    side_effects: bool = False
    requires_approval: bool = False


_OPERATIONS: dict[str, _Operation] = {
    op.name: op
    for op in (
        _Operation(
            "extract",
            _op_extract,
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "document_id", "entities"],
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": MAX_SOURCE_CHARS},
                    "document_id": {"type": "string", "minLength": 1},
                    "entities": {"type": "array", "items": _ENTITY_SCHEMA},
                    "relation_patterns": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "string",
                            "pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$",
                        },
                    },
                },
            },
        ),
        _Operation(
            "import_graph",
            _op_import_graph,
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["incoming", "import_id"],
                "properties": {
                    "base": _GRAPH_SCHEMA,
                    "base_version": {"type": "integer", "minimum": 0},
                    "incoming": _GRAPH_SCHEMA,
                    "import_id": {"type": "string", "minLength": 1},
                    "strict": {"type": "boolean", "default": True},
                    "expected_version": {"type": "integer", "minimum": 0},
                },
            },
        ),
        _Operation(
            "query_path",
            _op_query_path,
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["graph", "source", "target"],
                "properties": {
                    "graph": _GRAPH_SCHEMA,
                    "source": {"type": "string", "minLength": 1},
                    "target": {"type": "string", "minLength": 1},
                    "max_depth": {"type": "integer", "minimum": 0},
                    "relations": {"type": "array", "items": {"type": "string"}},
                    "origins": {
                        "type": "array",
                        "items": {"enum": sorted(EDGE_ORIGINS)},
                    },
                },
            },
        ),
        _Operation(
            "validate_graph",
            _op_validate_graph,
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["graph"],
                "properties": {
                    "graph": _GRAPH_SCHEMA,
                    "allow_self_loops": {"type": "boolean", "default": False},
                    "documents": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
            },
        ),
    )
}


def _package_version() -> str:
    try:
        return metadata.version("knowledge-twin")
    except metadata.PackageNotFoundError:
        return "0.0.0+unknown"


def capabilities() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "system": SYSTEM,
        "version": _package_version(),
        "operations": [
            {
                "name": op.name,
                "side_effects": op.side_effects,
                "requires_approval": op.requires_approval,
                "input_schema": op.input_schema,
                "timeout_s": op.timeout_s,
            }
            for op in _OPERATIONS.values()
        ],
    }


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 128


def run_operation(
    operation: str,
    payload: dict,
    *,
    run_id: str | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Run a Knowledge Twin operation and return a ``makma.v1`` envelope dict."""
    started = datetime.now(UTC)
    clock = time.perf_counter()
    run = run_id if _valid_id(run_id) else uuid.uuid4().hex
    correlation = correlation_id if _valid_id(correlation_id) else run
    op_name = operation if isinstance(operation, str) and _OPERATION_RE.match(operation) else (
        "unknown"
    )

    data: Any = None
    error: ErrorInfo | None = None
    provenance: list[Provenance] = []
    op = _OPERATIONS.get(operation) if isinstance(operation, str) else None
    if op is None:
        error = ErrorInfo("UNKNOWN_OPERATION", f"unknown operation; supported: {sorted(_OPERATIONS)}")
    elif (run_id is not None and not _valid_id(run_id)) or (
        correlation_id is not None and not _valid_id(correlation_id)
    ):
        error = ErrorInfo("INVALID_INPUT", "run_id and correlation_id must be 1..128 characters")
    elif not isinstance(payload, dict):
        error = ErrorInfo("INVALID_INPUT", "payload must be a JSON object")
    else:
        try:
            data, provenance = op.handler(payload)
        except InvalidInput as exc:
            error = ErrorInfo("INVALID_INPUT", str(exc)[:2000])
        except OperationError as exc:
            error = ErrorInfo(exc.code, str(exc)[:2000], details=exc.details)
        except Exception:  # noqa: BLE001 - contract boundary: never leak internals
            error = ErrorInfo("INTERNAL_ERROR", "operation failed unexpectedly")
        if error is not None:
            data, provenance = None, []

    envelope = Envelope(
        operation=op_name,
        run_id=run,
        correlation_id=correlation,
        trace_id=uuid.uuid4().hex,
        span_id=secrets.token_hex(8),
        status="ok" if error is None else "error",
        started_at=started.isoformat().replace("+00:00", "Z"),
        duration_ms=round((time.perf_counter() - clock) * 1000, 3),
        data=data,
        error=error,
        provenance=tuple(provenance),
    )
    return envelope.to_dict()
