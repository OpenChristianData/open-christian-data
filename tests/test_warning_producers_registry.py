from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from build.lib import warning_producers as warning_producers_module
from build.lib.warning_producers import ProducerContractError, discover_producers, run_all_producers


OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"warnings": {"type": "array"}},
    "required": ["warnings"],
}


def _producer(**overrides):
    def run(record, meta, upstream_outputs):
        return {"warnings": []}

    attrs = {
        "PRODUCER_ID": "fake",
        "SIGNATURE_VERSION": 1,
        "WARNING_CODES": {
            "fake_code": {
                "severity": "info",
                "description": "Fake warning.",
                "signature_fields": ["code"],
            }
        },
        "APPLIES_TO_RESOURCE_TYPES": None,
        "REQUIRES_CAPABILITIES": {},
        "CONSUMES": [],
        "PRODUCES_SCHEMA": OUTPUT_SCHEMA,
        "SCOPE": "record_local",
        "run": run,
    }
    attrs.update(overrides)
    return SimpleNamespace(**attrs)


def _record():
    return {"meta": {"schema_type": "commentary", "id": "r"}, "data": []}


def test_discover_producers_returns_expected_ids() -> None:
    assert [producer.PRODUCER_ID for producer in discover_producers()] == [
        "attestation_coverage",
        "attested_by_reference_resolution",
        "coverage",
        "disagreement_classification",
        "historical_lexicon",
        "language_confidence",
        "modernisation_completeness",
        "modernisation_coverage_consistency",
        "paired_record_invariant",
        "paired_with_reference_resolution",
        "source_page_coverage",
        "structural_integrity",
        "taxonomy_consistency",
        "text_suspicion",
        "transliteration_completeness",
        "within_edition_divergence",
    ]


def test_duplicate_warning_codes_raise_contract_error() -> None:
    class DuplicateCodes(dict):
        def keys(self):
            return ["same", "same"]

    duplicate_codes = DuplicateCodes(
        {
            "same": {
                "severity": "info",
                "description": "Duplicate.",
                "signature_fields": ["code"],
            }
        }
    )

    with pytest.raises(ProducerContractError):
        run_all_producers(_record(), {"resource_type": "commentary"}, producers=[_producer(WARNING_CODES=duplicate_codes)])


def test_cyclic_consumes_raise_contract_error() -> None:
    a = _producer(PRODUCER_ID="a", CONSUMES=["b"])
    b = _producer(PRODUCER_ID="b", CONSUMES=["a"])

    with pytest.raises(ProducerContractError):
        run_all_producers(_record(), {"resource_type": "commentary"}, producers=[a, b])


def test_missing_produces_schema_raises_contract_error() -> None:
    producer = _producer()
    delattr(producer, "PRODUCES_SCHEMA")

    with pytest.raises(ProducerContractError):
        run_all_producers(_record(), {"resource_type": "commentary"}, producers=[producer])


def test_missing_signature_version_raises_contract_error() -> None:
    producer = _producer()
    delattr(producer, "SIGNATURE_VERSION")

    with pytest.raises(ProducerContractError):
        run_all_producers(_record(), {"resource_type": "commentary"}, producers=[producer])


def test_missing_requires_capabilities_raises_contract_error() -> None:
    producer = _producer()
    delattr(producer, "REQUIRES_CAPABILITIES")

    with pytest.raises(ProducerContractError):
        run_all_producers(_record(), {"resource_type": "commentary"}, producers=[producer])


def test_run_all_producers_skips_not_applicable_resource_type() -> None:
    called = {"value": False}

    def run(record, meta, upstream_outputs):
        called["value"] = True
        return {"warnings": []}

    result = run_all_producers(
        _record(),
        {"resource_type": "commentary"},
        producers=[_producer(APPLIES_TO_RESOURCE_TYPES=["bible_text"], run=run)],
    )

    assert called["value"] is False
    assert result == {"fake": []}


def test_run_all_producers_dedupes_identical_signatures() -> None:
    def run(record, meta, upstream_outputs):
        warning = {
            "code": "fake_code",
            "severity": "info",
            "entry_id": None,
            "field_path": None,
            "message": "Same.",
            "evidence": None,
            "signature": "abc123",
            "ephemeral": False,
        }
        return {"warnings": [warning, dict(warning)]}

    result = run_all_producers(_record(), {"resource_type": "commentary"}, producers=[_producer(run=run)])
    assert result == {"fake": [
        {
            "code": "fake_code",
            "severity": "info",
            "entry_id": None,
            "field_path": None,
            "message": "Same.",
            "evidence": None,
            "signature": "abc123",
            "ephemeral": False,
        }
    ]}


def test_run_all_producers_logs_crashing_producer_and_marks_upstream(capsys):
    """A-F1: producer that raises must log to stderr and produce a marked
    upstream slot rather than swallowing silently."""
    def run(record, meta, upstream_outputs):
        raise RuntimeError("simulated_producer_crash")

    crash_producer = _producer(PRODUCER_ID="crash_a", run=run)
    downstream_called = {"upstream": None}

    def downstream_run(record, meta, upstream_outputs):
        downstream_called["upstream"] = upstream_outputs.get("crash_a")
        return {"warnings": []}

    downstream = _producer(
        PRODUCER_ID="downstream_b",
        CONSUMES=["crash_a"],
        run=downstream_run,
    )

    result = run_all_producers(
        _record(),
        {"resource_type": "commentary"},
        producers=[crash_producer, downstream],
    )

    # Result still includes the crashed producer with an empty list (so the
    # run doesn't abort), but the downstream consumer sees crashed=True.
    assert result["crash_a"] == []
    assert downstream_called["upstream"] is not None
    assert downstream_called["upstream"].get("crashed") is True
    assert downstream_called["upstream"].get("crash_class") == "RuntimeError"

    # Loud failure: stderr carries the producer id and exception class.
    err = capsys.readouterr().err
    assert "crash_a" in err
    assert "RuntimeError" in err
    assert "simulated_producer_crash" in err


def test_run_all_producers_spills_crash_to_dead_letter(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(warning_producers_module, "REPO_ROOT", tmp_path)

    def run(record, meta, upstream_outputs):
        raise RuntimeError("simulated_producer_crash")

    crash_producer = _producer(PRODUCER_ID="crash_a", run=run)
    downstream_called = {"upstream": None}

    def downstream_run(record, meta, upstream_outputs):
        downstream_called["upstream"] = upstream_outputs.get("crash_a")
        return {"warnings": []}

    downstream = _producer(
        PRODUCER_ID="downstream_b",
        CONSUMES=["crash_a"],
        run=downstream_run,
    )
    resource_id = "resource-crash"

    result = run_all_producers(
        _record(),
        {"resource_type": "commentary", "resource_id": resource_id},
        producers=[crash_producer, downstream],
    )

    assert result["crash_a"] == []
    assert downstream_called["upstream"] is not None
    assert downstream_called["upstream"].get("crashed") is True
    assert downstream_called["upstream"].get("crash_class") == "RuntimeError"

    err = capsys.readouterr().err
    assert "crash_a" in err
    assert "RuntimeError" in err
    assert "simulated_producer_crash" in err

    dead_letter_path = tmp_path / "review" / "dead-letter" / f"{resource_id}.jsonl"
    assert dead_letter_path.exists()
    lines = dead_letter_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["reason"] == "producer_unknown"
    assert record["producer"] == "crash_a"
    assert record["received_at"]
    raw = record["raw_warning"]
    assert raw["resource_id"] == resource_id
    assert raw["crash_class"] == "RuntimeError"
    assert raw["crash_message"] == "simulated_producer_crash"
    assert raw["traceback"]


def test_run_all_producers_marks_upstream_on_produces_schema_failure(capsys):
    """A-F1: PRODUCES_SCHEMA validation failures must surface, not vanish."""
    def run(record, meta, upstream_outputs):
        return {"warnings": "not a list — schema requires array"}

    bad = _producer(PRODUCER_ID="schema_bad", run=run)
    result = run_all_producers(
        _record(),
        {"resource_type": "commentary"},
        producers=[bad],
    )
    assert result["schema_bad"] == []
    err = capsys.readouterr().err
    assert "schema_bad" in err
    assert "PRODUCES_SCHEMA" in err


def test_run_all_producers_spills_schema_failure_to_dead_letter(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(warning_producers_module, "REPO_ROOT", tmp_path)

    def run(record, meta, upstream_outputs):
        return {"warnings": "not a list"}

    bad = _producer(PRODUCER_ID="schema_bad", run=run)
    downstream_called = {"upstream": None}

    def downstream_run(record, meta, upstream_outputs):
        downstream_called["upstream"] = upstream_outputs.get("schema_bad")
        return {"warnings": []}

    downstream = _producer(
        PRODUCER_ID="downstream_b",
        CONSUMES=["schema_bad"],
        run=downstream_run,
    )
    resource_id = "resource-schema"

    result = run_all_producers(
        _record(),
        {"resource_type": "commentary", "resource_id": resource_id},
        producers=[bad, downstream],
    )

    assert result["schema_bad"] == []
    assert downstream_called["upstream"] is not None
    assert downstream_called["upstream"].get("crashed") is True
    assert downstream_called["upstream"].get("crash_class") == "producer_output_schema_failed"

    err = capsys.readouterr().err
    assert "schema_bad" in err
    assert "PRODUCES_SCHEMA" in err

    dead_letter_path = tmp_path / "review" / "dead-letter" / f"{resource_id}.jsonl"
    assert dead_letter_path.exists()
    lines = dead_letter_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["reason"] == "producer_output_schema_failed"
    assert record["producer"] == "schema_bad"
    assert record["received_at"]
    raw = record["raw_warning"]
    assert raw["resource_id"] == resource_id
    assert raw["crash_class"] == "producer_output_schema_failed"
    assert raw["crash_message"]
    assert raw["traceback"]


def test_pass_then_fail_across_two_gates() -> None:
    from build.lib.warning_producers import language_confidence, source_page_coverage

    record = {
        "meta": {
            "id": "sample/work/edition",
            "schema_type": "reconciled_record",
            "pd_anchor": "source-a",
        },
        "blocks": [
            {
                "block_id": "b1",
                "language": "en",
                "language_confidence": 0.98,
                "source_pages": [],
            }
        ],
    }

    result = run_all_producers(
        record,
        {"resource_id": "sample", "resource_type": "commentary"},
        producers=[language_confidence, source_page_coverage],
    )

    assert result["language_confidence"] == []
    assert [warning["code"] for warning in result["source_page_coverage"]] == ["SOURCE_PAGE_COVERAGE_MISSING"]


def test_modernise_gate_enforcement() -> None:
    from build.lib.warning_producers import language_confidence

    record = {
        "meta": {"id": "sample/work/edition", "schema_type": "reconciled_record"},
        "blocks": [
            {
                "block_id": "b1",
                "language": "und",
                "language_confidence": 0.0,
            }
        ],
    }

    result = run_all_producers(
        record,
        {"resource_id": "sample", "resource_type": "commentary"},
        producers=[language_confidence],
    )

    assert [warning["code"] for warning in result["language_confidence"]] == [
        "LANG_BLOCK_NEEDS_REVIEW",
        "LANG_RECORD_NEEDS_REVIEW",
    ]
