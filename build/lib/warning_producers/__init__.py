"""Warning producer registry for OCD review tooling."""

from __future__ import annotations

import hashlib
import importlib
import json
import pkgutil
import sys
import traceback
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema

from build.lib.paths import REPO_ROOT
import ocd_kernel.lib.warning_producers as kernel_warning_producers

METRIC_FIELDS = (
    "warnings_emitted",
    "warnings_dismissed",
    "warnings_acknowledged_real",
    "warnings_acknowledged_expected",
    "corrections_generated",
    "false_positive_ratio",
    "silenced_by_threshold",
)


class ProducerContractError(Exception):
    """Raised when a warning producer violates the registry contract."""


WARNING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "warnings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "severity": {"type": "string"},
                    "entry_id": {"type": ["string", "null"]},
                    "field_path": {"type": ["string", "null"]},
                    "message": {"type": "string"},
                    "evidence": {"type": ["object", "null"]},
                    "signature": {"type": "string"},
                    "ephemeral": {"type": "boolean"},
                },
                "required": [
                    "code",
                    "severity",
                    "entry_id",
                    "field_path",
                    "message",
                    "evidence",
                    "signature",
                    "ephemeral",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["warnings"],
    "additionalProperties": False,
}


def build_warning(
    producer: Any,
    code: str,
    *,
    entry_id: str | None,
    field_path: str | None,
    message: str,
    evidence: dict[str, Any] | None = None,
    signature_values: Mapping[str, Any] | None = None,
    ephemeral: bool = False,
) -> dict[str, Any]:
    """Build a canonical producer warning with a stable signature."""
    code_contract = producer.WARNING_CODES[code]
    values: dict[str, Any] = {
        "code": code,
        "entry_id": entry_id,
        "field_path": field_path,
        "resource_id": None,
        "entry_index": None,
        "surface": None,
        "normalised": None,
        "declared_type": None,
        "schema_default": None,
    }
    if evidence:
        values.update(evidence)
    if signature_values:
        values.update(signature_values)
    signature = warning_signature(code_contract["signature_fields"], values)
    return {
        "code": code,
        "severity": code_contract["severity"],
        "entry_id": entry_id,
        "field_path": field_path,
        "message": message,
        "evidence": evidence,
        "signature": signature,
        "ephemeral": ephemeral,
    }


def warning_signature(signature_fields: Iterable[str], values: Mapping[str, Any]) -> str:
    pairs = sorted((field, values[field]) for field in signature_fields)
    payload = json.dumps(pairs, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def discover_producers() -> list[Any]:
    """Discover, import, validate, and return registered producer modules."""
    modules: list[Any] = []
    for package in (kernel_warning_producers, sys.modules[__name__]):
        package_name = package.__name__
        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name == "__init__" or module_info.name.startswith("_"):
                continue
            modules.append(importlib.import_module(f"{package_name}.{module_info.name}"))
    return _validate_and_sort(modules)


def run_all_producers(record: dict, meta: dict, *, producers: list[Any] | None = None) -> dict[str, list]:
    """Run all applicable producers and return warnings grouped by producer id.

    Producer failures are surfaced two ways: the offending producer's
    upstream slot is marked with ``crashed=True`` so downstream consumers
    can detect it, and the failure reason is logged to stderr. AGENTS.md
    forbids silent failures; this is the minimum loud-failure contract
    without crashing the whole pipeline.
    """
    ordered = _topological_sort(_validate_and_sort(producers if producers is not None else discover_producers()))
    resource_type = meta.get("resource_type")
    results: dict[str, list] = {}
    upstream_outputs: dict[str, dict[str, Any] | None] = {}

    for producer in ordered:
        producer_id = producer.PRODUCER_ID
        results[producer_id] = []
        applies_to = producer.APPLIES_TO_RESOURCE_TYPES
        if applies_to is not None and resource_type not in applies_to:
            upstream_outputs[producer_id] = {"warnings": [], "skipped_reason": "resource_type_not_applicable"}
            continue

        relevant_upstream = {pid: upstream_outputs.get(pid) for pid in producer.CONSUMES}
        try:
            output = producer.run(record, meta, relevant_upstream)
            jsonschema.Draft202012Validator(producer.PRODUCES_SCHEMA).validate(output)
            warnings = _dedupe_warnings(output.get("warnings", []))
            output = {**output, "warnings": warnings}
            upstream_outputs[producer_id] = output
            results[producer_id] = warnings
            _write_producer_metrics(producer_id, meta, output, warnings)
        except jsonschema.ValidationError as exc:
            print(
                f"[warning_producers] {producer_id}: PRODUCES_SCHEMA validation failed: {exc.message}",
                file=sys.stderr,
            )
            _spill_producer_crash(
                producer_id=producer_id,
                resource_id=str(meta.get("resource_id") or "unknown"),
                exc=exc,
                crash_class="producer_output_schema_failed",
                reason="producer_output_schema_failed",
            )
            upstream_outputs[producer_id] = {
                "warnings": [],
                "crashed": True,
                "crash_class": "producer_output_schema_failed",
                "crash_message": exc.message,
            }
        except Exception as exc:
            print(
                f"[warning_producers] {producer_id}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            _spill_producer_crash(
                producer_id=producer_id,
                resource_id=str(meta.get("resource_id") or "unknown"),
                exc=exc,
                crash_class=type(exc).__name__,
                reason="producer_unknown",
            )
            upstream_outputs[producer_id] = {
                "warnings": [],
                "crashed": True,
                "crash_class": type(exc).__name__,
                "crash_message": str(exc),
            }
    return results


def _spill_producer_crash(
    *,
    producer_id: str,
    resource_id: str,
    exc: BaseException,
    crash_class: str,
    reason: str,
    dead_letter_dir: Path | None = None,
) -> None:
    target_dir = dead_letter_dir if dead_letter_dir is not None else REPO_ROOT / "review" / "dead-letter"
    target_dir.mkdir(parents=True, exist_ok=True)
    # Shape conforms to dead_letter_entry in
    # ocd_kernel/schemas/v1/review_state.schema.json: reason + raw_warning +
    # received_at are required; producer is optional but always emitted.
    record = {
        "reason": reason,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "producer": producer_id,
        "raw_warning": {
            "resource_id": resource_id,
            "crash_class": crash_class,
            "crash_message": str(exc),
            "traceback": traceback.format_exc(),
        },
    }
    with open(target_dir / f"{resource_id}.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _write_producer_metrics(
    producer_id: str,
    meta: Mapping[str, Any],
    output: Mapping[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    resource_id = str(meta.get("resource_id") or "unknown")
    metrics = {
        "warnings_emitted": len(warnings),
        "warnings_dismissed": 0,
        "warnings_acknowledged_real": 0,
        "warnings_acknowledged_expected": 0,
        "corrections_generated": 0,
        "false_positive_ratio": 0,
        "silenced_by_threshold": int(output.get("silenced_by_threshold") or 0),
    }
    metrics_dir = REPO_ROOT / "review" / "producer-metrics" / producer_id
    metrics_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = metrics_dir / f"{resource_id}.json"
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dedupe_warnings(warnings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for warning in warnings:
        signature = warning.get("signature")
        if not isinstance(signature, str) or signature in seen:
            continue
        seen.add(signature)
        deduped.append(warning)
    return deduped


def _validate_and_sort(producers: Iterable[Any]) -> list[Any]:
    producer_list = list(producers)
    seen_ids: set[str] = set()
    for producer in producer_list:
        _validate_producer_contract(producer)
        producer_id = producer.PRODUCER_ID
        if producer_id in seen_ids:
            raise ProducerContractError(f"Duplicate PRODUCER_ID: {producer_id}")
        seen_ids.add(producer_id)
    sorted_producers = sorted(producer_list, key=lambda module: module.PRODUCER_ID)
    _topological_sort(sorted_producers)
    return sorted_producers


def _validate_producer_contract(producer: Any) -> None:
    required = [
        "PRODUCER_ID",
        "SIGNATURE_VERSION",
        "WARNING_CODES",
        "APPLIES_TO_RESOURCE_TYPES",
        "REQUIRES_CAPABILITIES",
        "CONSUMES",
        "PRODUCES_SCHEMA",
        "SCOPE",
        "run",
    ]
    for name in required:
        if not hasattr(producer, name):
            raise ProducerContractError(f"{producer} missing {name}")

    if not isinstance(producer.PRODUCER_ID, str) or not producer.PRODUCER_ID:
        raise ProducerContractError("PRODUCER_ID must be a non-empty string")
    if not isinstance(producer.SIGNATURE_VERSION, int):
        raise ProducerContractError(f"{producer.PRODUCER_ID}: SIGNATURE_VERSION must be int")
    if not isinstance(producer.WARNING_CODES, dict):
        raise ProducerContractError(f"{producer.PRODUCER_ID}: WARNING_CODES must be dict")
    code_keys = list(producer.WARNING_CODES.keys())
    if len(code_keys) != len(set(code_keys)):
        raise ProducerContractError(f"{producer.PRODUCER_ID}: duplicate WARNING_CODES")
    for code, contract in producer.WARNING_CODES.items():
        if not isinstance(code, str) or not isinstance(contract, dict):
            raise ProducerContractError(f"{producer.PRODUCER_ID}: invalid warning code contract")
        if "severity" not in contract or "description" not in contract or "signature_fields" not in contract:
            raise ProducerContractError(f"{producer.PRODUCER_ID}: incomplete warning code contract")
        if not isinstance(contract["signature_fields"], list):
            raise ProducerContractError(f"{producer.PRODUCER_ID}: signature_fields must be list")
    applies_to = producer.APPLIES_TO_RESOURCE_TYPES
    if applies_to is not None and not isinstance(applies_to, list):
        raise ProducerContractError(f"{producer.PRODUCER_ID}: APPLIES_TO_RESOURCE_TYPES must be list or None")
    if not isinstance(producer.REQUIRES_CAPABILITIES, dict):
        raise ProducerContractError(f"{producer.PRODUCER_ID}: REQUIRES_CAPABILITIES must be dict")
    if not isinstance(producer.CONSUMES, list):
        raise ProducerContractError(f"{producer.PRODUCER_ID}: CONSUMES must be list")
    if producer.SCOPE not in {"record_local", "resource_local"}:
        raise ProducerContractError(f"{producer.PRODUCER_ID}: invalid SCOPE")
    try:
        jsonschema.Draft202012Validator.check_schema(producer.PRODUCES_SCHEMA)
    except jsonschema.SchemaError as exc:
        raise ProducerContractError(f"{producer.PRODUCER_ID}: invalid PRODUCES_SCHEMA") from exc


def _topological_sort(producers: Iterable[Any]) -> list[Any]:
    producer_list = list(producers)
    by_id = {producer.PRODUCER_ID: producer for producer in producer_list}
    indegree = {producer.PRODUCER_ID: 0 for producer in producer_list}
    outgoing = {producer.PRODUCER_ID: [] for producer in producer_list}
    for producer in producer_list:
        for upstream_id in producer.CONSUMES:
            if upstream_id not in by_id:
                raise ProducerContractError(f"{producer.PRODUCER_ID}: unknown upstream producer {upstream_id}")
            indegree[producer.PRODUCER_ID] += 1
            outgoing[upstream_id].append(producer.PRODUCER_ID)

    ready = sorted(pid for pid, degree in indegree.items() if degree == 0)
    ordered: list[Any] = []
    while ready:
        producer_id = ready.pop(0)
        ordered.append(by_id[producer_id])
        for downstream_id in sorted(outgoing[producer_id]):
            indegree[downstream_id] -= 1
            if indegree[downstream_id] == 0:
                ready.append(downstream_id)
                ready.sort()
    if len(ordered) != len(producer_list):
        raise ProducerContractError("Producer CONSUMES graph is cyclic")
    return ordered
