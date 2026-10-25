"""Focused M0 tests for the closed source-metadata engine."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from build.lib import source_metadata_evidence as evidence

from build.tools.report_source_metadata import main as metadata_main
import build.lib.source_metadata as source_metadata
from build.lib import source_metadata_review as review
from build.tools.review_source_metadata import main as review_main

from build.lib.source_metadata import (
    EvidenceError,
    MetadataError,
    build_report,
    canonical_bytes,
    check_outputs,
    coverage_report,
    dimension_names,
    expected_outputs,
    lookup_sidecar,
    sidecar_relative_path,
    validate_decision_documents,
    validate_worklist,
    verify_evidence,
    write_outputs,
)


DIMENSIONS = dimension_names()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(root: Path, relative: str, value: object) -> tuple[str, int, str]:
    path = root / relative
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative, len(data), _sha(data)


def _fixture(tmp_path: Path, *, repair_required: bool = False, adoption: str = "source_evidence_only") -> tuple[dict, dict, Path, Path]:
    packet = {"title": "Synthetic title"}
    packet_rel, packet_bytes, packet_sha = _write_json(tmp_path, "evidence.json", packet)
    target = {"title": "Synthetic title"}
    target_rel, _target_bytes, target_sha = _write_json(tmp_path, "target.json", target)
    item = {
        "item_id": "work:title",
        "field": "title",
        "source_packet": packet_rel,
        "input_pointer": "/title",
        "input_value": "Synthetic title",
        "input_sha256": packet_sha,
        "requirement": "required" if repair_required else "useful_optional",
        "repair_required": repair_required,
    }
    dimensions = {
        dimension: {"items": [copy.deepcopy(item)] if dimension == "work" else []}
        for dimension in DIMENSIONS
    }
    for dimension in DIMENSIONS[1:]:
        extra = copy.deepcopy(item)
        extra["item_id"] = f"{dimension}:sample"
        extra["field"] = f"{dimension}_sample"
        dimensions[dimension]["items"] = [extra]
    worklist = {
        "schema_version": "source-metadata-worklist-v1",
        "writer": "ocd-source-metadata-v1",
        "batch_id": "test-batch",
        "subjects": [
            {
                "subject": {"kind": "catalog", "id": "synthetic-work"},
                "dimensions": dimensions,
            }
        ],
    }
    binding = {
        "path": packet_rel,
        "sha256": packet_sha,
        "bytes": packet_bytes,
        "role": "primary",
        "locator": {
            "kind": "json_pointer",
            "value": "/title",
            "expected": "Synthetic title",
        },
    }
    claim = {
        "worklist_item_id": item["item_id"],
        "claim_id": "synthetic-title",
        "scope": {
            "member": "evidence.json",
            "entity": "work",
            "predicate": "title",
            "event_role": "none",
        },
        "evidence": {
            "classification": "supported",
            "value": "Synthetic title",
            "bindings": [binding],
        },
        "requirement": {"classification": item["requirement"], "reason": "synthetic test"},
        "adoption": {
            "classification": "adopted" if adoption == "adopted" else "adopted",
            "destination": adoption,
        },
        "inspection": {"classification": "inspected", "owner": "test", "evidence": "evidence.json#/title"},
    }
    if adoption != "source_evidence_only":
        claim["adoption"]["target"] = {
            "path": target_rel,
            "selector": "/title",
            "expected_value": "Synthetic title",
            "current_raw_sha256": target_sha,
            "value_check": True,
        }
    decision = {
        "schema_version": "source-metadata-decisions-v1",
        "writer": "ocd-source-metadata-v1",
        "batch_id": "test-batch",
        "decisions": [
            {
                "subject": {"kind": "catalog", "id": "synthetic-work"},
                "dimensions": {
                    "work": {
                        "status": "inspected",
                        "owner": "test",
                        "fields": [claim],
                    }
                },
            }
        ],
    }
    worklist_path = tmp_path / "worklist.json"
    decisions_path = tmp_path / "decisions.json"
    worklist_path.write_bytes(canonical_bytes(worklist))
    decisions_path.write_bytes(canonical_bytes(decision))
    return worklist, decision, worklist_path, decisions_path


def test_subject_writer_preserves_unrelated_bytes_and_checks(tmp_path: Path) -> None:
    worklist, document, wp, dp = _fixture(tmp_path)
    other_work = copy.deepcopy(worklist["subjects"][0])
    other_work["subject"]["id"] = "other-work"
    worklist["subjects"].append(other_work)
    other = copy.deepcopy(document["decisions"][0])
    other["subject"]["id"] = "other-work"
    document["decisions"].append(other)
    wp.write_bytes(canonical_bytes(worklist))
    dp.write_bytes(canonical_bytes(document))
    write_outputs(tmp_path, worklist_path=wp, decisions_path=dp)
    other_path = tmp_path / sidecar_relative_path(other["subject"])
    other_bytes = other_path.read_bytes()
    index_path = tmp_path / "metadata/source-evidence/index.json"
    index_before = index_path.read_bytes()
    old_index = json.loads(index_before)
    old_target = next(row for row in old_index["subjects"] if row["subject"]["id"] == "synthetic-work")
    document["decisions"][0]["dimensions"]["work"]["owner"] = "updated reviewer"
    # This unrelated evidence defect must not be visited by a scoped write.
    other["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]["sha256"] = "0" * 64
    dp.write_bytes(canonical_bytes(document))
    kwargs = {"worklist_path": wp, "decisions_path": dp}
    with pytest.raises(EvidenceError):
        write_outputs(tmp_path, **kwargs)
    before_check = source_metadata.persist_subject(tmp_path, "catalog", "synthetic-work", **kwargs)
    assert not before_check["current"]
    assert index_path.read_bytes() == index_before
    result = source_metadata.persist_subject(tmp_path, "catalog", "synthetic-work", write=True, **kwargs)
    assert result["written"]
    assert other_path.read_bytes() == other_bytes
    new_index = json.loads(index_path.read_bytes())
    new_target = next(row for row in new_index["subjects"] if row["subject"]["id"] == "synthetic-work")
    assert index_path.read_bytes() == index_before.replace(
        canonical_bytes(old_target).rstrip(b"\n"), canonical_bytes(new_target).rstrip(b"\n")
    )
    assert source_metadata.persist_subject(tmp_path, "catalog", "synthetic-work", **kwargs)["current"]
    assert lookup_sidecar(tmp_path, "catalog", "synthetic-work")["dimensions"]["work"]["owner"] == "updated reviewer"
    assert metadata_main(["--root", str(tmp_path), "--worklist", str(wp), "--decisions", str(dp),
                          "--check-subject", "--subject-kind", "catalog", "--subject", "synthetic-work"]) == 0
    assert metadata_main(["--root", str(tmp_path), "--worklist", str(wp), "--decisions", str(dp),
                          "--write-subject", "--subject-kind", "catalog", "--subject", "synthetic-work"]) == 0


@pytest.mark.parametrize("failure", ["evidence", "coverage", "missing", "duplicate", "batch", "index-write"])
def test_subject_writer_failure_preserves_outputs(tmp_path: Path, monkeypatch, failure: str) -> None:
    worklist, document, wp, dp = _fixture(tmp_path)
    write_outputs(tmp_path, worklist_path=wp, decisions_path=dp)
    outputs = {path: path.read_bytes() for path in (tmp_path / "metadata").rglob("*.json")}
    decision = document["decisions"][0]
    decision["dimensions"]["work"]["owner"] = "updated reviewer"
    if failure == "evidence":
        (tmp_path / "evidence.json").write_text('{}', encoding="utf-8")
    elif failure == "coverage":
        decision["dimensions"] = {}
    elif failure == "missing":
        document["decisions"] = []
    elif failure == "duplicate":
        document["decisions"].append(copy.deepcopy(decision))
    elif failure == "batch":
        worklist["batch_id"] = "different-batch"
        wp.write_bytes(canonical_bytes(worklist))
    else:
        original_write = source_metadata._write_bytes_atomic
        def fail_index(path, data):
            if path.name == "index.json":
                raise MetadataError("injected index write failure")
            original_write(path, data)
        monkeypatch.setattr(source_metadata, "_write_bytes_atomic", fail_index)
    dp.write_bytes(canonical_bytes(document))
    with pytest.raises(MetadataError):
        source_metadata.persist_subject(tmp_path, "catalog", "synthetic-work", worklist_path=wp,
                                        decisions_path=dp, write=True)
    assert {path: path.read_bytes() for path in outputs} == outputs


def test_schema_and_semantic_validation_accepts_scoped_claim(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    validate_worklist(worklist)
    entries = validate_decision_documents([decision], worklist=worklist)
    assert entries[0]["subject"]["id"] == "synthetic-work"


def test_duplicate_scoped_claim_identity_is_rejected(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    duplicate = copy.deepcopy(decision["decisions"][0]["dimensions"]["work"]["fields"][0])
    decision["decisions"][0]["dimensions"]["work"]["fields"].append(duplicate)
    with pytest.raises(MetadataError, match="duplicate scoped claim"):
        validate_decision_documents([decision], worklist=worklist)


def test_observed_claim_cannot_be_promoted(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path, adoption="v2")
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["evidence"]["classification"] = "observed_claim"
    claim["evidence"]["question"] = "Which authority should own this observation?"
    claim["evidence"]["evidence_needed"] = "A primary source or explicit authority mapping."
    with pytest.raises(MetadataError, match="observed-only"):
        validate_decision_documents([decision], worklist=worklist)


def test_required_repair_cannot_use_source_evidence_only(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path, repair_required=True)
    with pytest.raises(MetadataError, match="source_evidence_only"):
        validate_decision_documents([decision], worklist=worklist)


def test_required_without_repair_cannot_be_source_evidence_only(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    item = worklist["subjects"][0]["dimensions"]["work"]["items"][0]
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    item["requirement"] = "required"
    claim["requirement"]["classification"] = "required"
    with pytest.raises(MetadataError, match="required claim.*source_evidence_only"):
        validate_decision_documents([decision], worklist=worklist)


def test_required_representation_gap_remains_supported_unapplied(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    item = worklist["subjects"][0]["dimensions"]["work"]["items"][0]
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    item["requirement"] = "required"
    claim["requirement"]["classification"] = "required"
    claim["adoption"] = {"classification": "supported_unapplied", "destination": "v2"}
    validate_decision_documents([decision], worklist=worklist)
    report = coverage_report(worklist, decision["decisions"])
    assert report["required_repair"]["status"] == "open"
    assert report["required_repair"]["supported_unapplied"] == 1


def test_optional_supported_unapplied_stays_on_optional_axis(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    subject = worklist["subjects"][0]
    for dimension in DIMENSIONS[1:]:
        subject["dimensions"][dimension]["items"] = []
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["adoption"] = {"classification": "supported_unapplied", "destination": "source_evidence_only"}
    validate_decision_documents([decision], worklist=worklist)

    report = coverage_report(worklist, decision["decisions"])

    assert report["required_repair"]["status"] == "clear"
    assert report["required_repair"]["supported_unapplied"] == 0
    assert report["optional_decision"]["status"] == "open"
    assert report["optional_decision"]["supported_unapplied"] == 1
    assert report["optional_decision"]["open_items"] == 1
    assert len(report["supported_unapplied_repairs"]) == 1


def test_mixed_required_and_optional_unapplied_keep_axis_counts_and_index_aggregate(tmp_path: Path) -> None:
    worklist, decision, worklist_path, decisions_path = _fixture(tmp_path)
    subject = worklist["subjects"][0]
    for dimension in DIMENSIONS[1:]:
        subject["dimensions"][dimension]["items"] = []
    work_item = subject["dimensions"]["work"]["items"][0]
    required_claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    work_item["requirement"] = "required"
    required_claim["requirement"]["classification"] = "required"
    required_claim["adoption"] = {"classification": "supported_unapplied", "destination": "v2"}

    optional_item = copy.deepcopy(work_item)
    optional_item["item_id"] = "work:optional"
    optional_item["requirement"] = "useful_optional"
    optional_item["repair_required"] = False
    subject["dimensions"]["work"]["items"].append(optional_item)
    optional_claim = copy.deepcopy(required_claim)
    optional_claim["worklist_item_id"] = optional_item["item_id"]
    optional_claim["claim_id"] = "synthetic-optional"
    optional_claim["requirement"] = {"classification": "useful_optional", "reason": "synthetic test"}
    optional_claim["adoption"] = {"classification": "supported_unapplied", "destination": "source_evidence_only"}
    decision["decisions"][0]["dimensions"]["work"]["fields"].append(optional_claim)
    validate_decision_documents([decision], worklist=worklist)

    report = coverage_report(worklist, decision["decisions"])

    assert report["required_repair"]["supported_unapplied"] == 1
    assert report["required_repair"]["open_items"] == 1
    assert report["optional_decision"]["supported_unapplied"] == 1
    assert report["optional_decision"]["open_items"] == 1
    assert len(report["supported_unapplied_repairs"]) == 2
    worklist_path.write_bytes(canonical_bytes(worklist))
    decisions_path.write_bytes(canonical_bytes(decision))
    _outputs, _report, index = expected_outputs(
        tmp_path, worklist_path=worklist_path, decisions_path=decisions_path
    )
    assert index["counts"]["supported_unapplied"] == 2


def test_repair_required_optional_item_axis_count_is_once_but_legacy_rows_are_preserved(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    subject = worklist["subjects"][0]
    for dimension in DIMENSIONS[1:]:
        subject["dimensions"][dimension]["items"] = []
    item = subject["dimensions"]["work"]["items"][0]
    item["repair_required"] = True
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["adoption"] = {"classification": "supported_unapplied", "destination": "source_evidence_only"}

    report = coverage_report(worklist, decision["decisions"])

    assert report["required_repair"]["status"] == "open"
    assert report["required_repair"]["supported_unapplied"] == 1
    assert report["required_repair"]["open_items"] == 2
    assert report["optional_decision"]["status"] == "clear"
    assert report["optional_decision"]["supported_unapplied"] == 0
    assert report["optional_decision"]["open_items"] == 0
    assert len(report["supported_unapplied_repairs"]) == 2


def test_inspected_and_unavailable_claims_need_inspection_evidence(tmp_path: Path) -> None:
    for classification in ("inspected", "unavailable"):
        worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
        claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
        claim["inspection"]["classification"] = classification
        claim["inspection"].pop("evidence")
        with pytest.raises(MetadataError, match="inspection evidence or reason"):
            validate_decision_documents([decision], worklist=worklist)


def test_authority_target_must_equal_claim_value(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path, adoption="v2")
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["adoption"]["target"]["expected_value"] = "Different title"
    with pytest.raises(MetadataError, match="expected_value.*evidence.value"):
        validate_decision_documents([decision], worklist=worklist)


def test_archive_member_binding_requires_member_hash_and_bytes(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    binding = decision["decisions"][0]["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]
    binding["member"] = "member.json"
    with pytest.raises(MetadataError, match="member_sha256"):
        validate_decision_documents([decision], worklist=worklist)


def test_unexpected_decision_subject_is_rejected_before_output(tmp_path: Path) -> None:
    _worklist, decision, worklist_path, decisions_path = _fixture(tmp_path)
    extra = copy.deepcopy(decision["decisions"][0])
    extra["subject"] = {"kind": "catalog", "id": "outside-frozen-worklist"}
    extra["dimensions"] = {}
    decision["decisions"].append(extra)
    decisions_path.write_bytes(canonical_bytes(decision))
    with pytest.raises(MetadataError, match="outside the frozen worklist"):
        write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert not (tmp_path / "metadata/source-evidence/index.json").exists()


def test_stale_adoption_and_raw_locator_are_reported(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path, adoption="v2")
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["adoption"]["target"]["current_raw_sha256"] = "0" * 64
    issues = verify_evidence(tmp_path, worklist, decision["decisions"])
    assert any("target hash mismatch" in item["message"] for item in issues)
    claim["adoption"]["target"]["current_raw_sha256"] = _sha((tmp_path / "target.json").read_bytes())
    claim["evidence"]["bindings"][0]["locator"]["expected"] = "wrong"
    issues = verify_evidence(tmp_path, worklist, decision["decisions"])
    assert any("expected" in item["message"] for item in issues)


def test_path_escape_is_rejected_before_filesystem_access(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["evidence"]["bindings"][0]["path"] = "../outside.json"
    with pytest.raises(MetadataError):
        validate_decision_documents([decision], worklist=worklist)


def test_missing_subject_dimension_and_claim_are_independent_report_axes(tmp_path: Path) -> None:
    worklist, _decision, worklist_path, decisions_path = _fixture(tmp_path)
    report = build_report(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert report["persistence"]["decided_subjects"] == 1
    assert report["inspection"]["missing_dimensions"] == 4
    assert report["inspection"]["missing_claims"] == 4
    assert "complete" not in report

    empty_decisions = copy.deepcopy(_decision)
    empty_decisions["decisions"] = []
    # The structural schema rejects an authored empty decision document; an
    # absent decision file is the valid pending-subject representation.
    decisions_path.unlink()
    report = build_report(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert report["persistence"]["missing_subjects"] == 1


def test_deterministic_write_check_and_index_bound_lookup(tmp_path: Path) -> None:
    _worklist, _decision, worklist_path, decisions_path = _fixture(tmp_path)
    result = write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert result["written"] == [
        "metadata/source-evidence/catalog/synthetic-work.json",
        "metadata/source-evidence/index.json",
    ]
    assert check_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path) == []
    sidecar = lookup_sidecar(tmp_path, "catalog", "synthetic-work")
    assert sidecar["subject"]["id"] == "synthetic-work"
    sidecar_path = tmp_path / sidecar_relative_path(sidecar["subject"])
    sidecar_path.write_text(sidecar_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(MetadataError, match="hash differs"):
        lookup_sidecar(tmp_path, "catalog", "synthetic-work")


def test_atomic_outputs_write_sidecars_before_index_and_preserve_index_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _worklist, _decision, worklist_path, decisions_path = _fixture(tmp_path)
    write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    sidecar_path = tmp_path / "metadata/source-evidence/catalog/synthetic-work.json"
    index_path = tmp_path / "metadata/source-evidence/index.json"
    old_sidecar = sidecar_path.read_bytes()
    old_index = index_path.read_bytes()
    real_replace = source_metadata.os.replace
    calls: list[str] = []

    def interrupt_before_index(source: Path, destination: Path) -> None:
        calls.append(Path(destination).name)
        if Path(destination) == index_path:
            raise OSError("simulated interruption")
        real_replace(source, destination)

    monkeypatch.setattr(source_metadata.os, "replace", interrupt_before_index)
    with pytest.raises(MetadataError, match="index.json"):
        write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert calls == [sidecar_path.name, index_path.name]
    assert sidecar_path.read_bytes() == old_sidecar
    assert index_path.read_bytes() == old_index


def test_check_reports_orphan_without_deleting_it(tmp_path: Path) -> None:
    _worklist, _decision, worklist_path, decisions_path = _fixture(tmp_path)
    write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    orphan = tmp_path / "metadata/source-evidence/catalog/orphan.json"
    orphan.write_text("{}\n", encoding="utf-8")
    issues = check_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert {item["message"] for item in issues} == {"unexpected managed sidecar"}
    assert orphan.is_file()


def test_write_refuses_unverified_claim_before_creating_outputs(tmp_path: Path) -> None:
    _worklist, decision, worklist_path, decisions_path = _fixture(tmp_path)
    decision["decisions"][0]["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]["sha256"] = "0" * 64
    decisions_path.write_bytes(canonical_bytes(decision))
    with pytest.raises(EvidenceError, match="unverified evidence"):
        write_outputs(tmp_path, worklist_path=worklist_path, decisions_path=decisions_path)
    assert not (tmp_path / "metadata/source-evidence/index.json").exists()


def test_cli_write_lookup_and_corrupt_output_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _worklist, _decision, worklist_path, decisions_path = _fixture(tmp_path)
    args = ["--root", str(tmp_path), "--worklist", str(worklist_path), "--decisions", str(decisions_path)]
    assert metadata_main([*args, "--write"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["evidence"]["unverified_edges"] == 0
    assert metadata_main(["--root", str(tmp_path), "--subject-kind", "catalog", "--subject", "synthetic-work"]) == 0
    assert json.loads(capsys.readouterr().out)["subject"]["id"] == "synthetic-work"
    sidecar = tmp_path / "metadata/source-evidence/catalog/synthetic-work.json"
    sidecar.write_bytes(b"{}\n")
    assert metadata_main([*args, "--check"]) == 2
    assert json.loads(capsys.readouterr().out)["output_check"]
    assert metadata_main(["--root", str(tmp_path), "--subject-kind", "catalog", "--subject", "synthetic-work"]) == 2
    assert "hash differs from index" in capsys.readouterr().err


def test_xml_evidence_rejects_duplicate_ids_even_with_current_raw_hash(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    source = tmp_path / "primary.xml"
    raw = b'<root><p id="title">Synthetic title</p></root>'
    source.write_bytes(raw)
    binding = {"path": "primary.xml", "sha256": _sha(raw), "bytes": len(raw), "role": "primary",
               "locator": {"kind": "xml_id", "value": "title", "expected": "Synthetic title"}}
    claim["evidence"]["bindings"] = [binding]
    assert verify_evidence(tmp_path, worklist, decision["decisions"]) == []
    raw = b'<root><p id="title">Synthetic title</p><p id="title">Different title</p></root>'
    source.write_bytes(raw)
    binding.update(sha256=_sha(raw), bytes=len(raw))
    issues = verify_evidence(tmp_path, worklist, decision["decisions"])
    assert any("resolve uniquely" in issue["message"] for issue in issues)


def test_whole_file_evidence_rejects_false_verification_marker(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    binding = decision["decisions"][0]["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]
    binding["locator"] = {"kind": "whole_file", "value": "retained file", "expected": False}
    issues = verify_evidence(tmp_path, worklist, decision["decisions"])
    assert any("whole_file expected" in issue["message"] for issue in issues)


def test_declared_latin1_locator_preserves_raw_source_bytes(tmp_path: Path) -> None:
    worklist, decision, _worklist_path, _decisions_path = _fixture(tmp_path)
    raw = "Retained imprint: édition ancienne.".encode("latin-1")
    path = tmp_path / "retained-latin1.txt"
    path.write_bytes(raw)
    binding = {"path": path.name, "sha256": _sha(raw), "bytes": len(raw), "role": "primary",
               "encoding": "latin-1", "locator": {"kind": "text", "value": "édition ancienne", "expected": "édition ancienne"}}
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["evidence"]["bindings"] = [binding]
    validate_decision_documents([decision], worklist=worklist)
    assert verify_evidence(tmp_path, worklist, decision["decisions"]) == []
    binding.pop("encoding")
    assert any("cannot decode utf-8" in x["message"] for x in verify_evidence(tmp_path, worklist, decision["decisions"]))
    assert path.read_bytes() == raw


def test_xml_cache_is_lazy_and_preserves_dual_attribute_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worklist, decision, _, _ = _fixture(tmp_path)
    raw = b'<root><p id="title" xml:id="title">Synthetic title</p><p id="other">Other</p></root>'
    (tmp_path / "primary.xml").write_bytes(raw)
    first = {"path": "primary.xml", "bytes": len(raw), "sha256": _sha(raw), "role": "primary",
             "locator": {"kind": "xml_id", "value": "title", "expected": "Synthetic title"}}
    second = copy.deepcopy(first)
    second["locator"] = {"kind": "xml_id", "value": "other", "expected": "Other"}
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["evidence"]["bindings"] = [first, second, first]
    calls = []
    parse = evidence.ET.fromstring
    def count(data: bytes):
        calls.append(data)
        return parse(data)
    monkeypatch.setattr(evidence.ET, "fromstring", count)
    assert verify_evidence(tmp_path, worklist, decision["decisions"]) == []
    assert len(calls) == 1
    first["sha256"] = "0" * 64
    claim["evidence"]["bindings"] = [first]
    assert verify_evidence(tmp_path, worklist, decision["decisions"])
    assert len(calls) == 1  # Invalid bytes never reach the XML parser.


@pytest.mark.parametrize("kind", ["json_pointer", "xml_id"])
def test_structured_locators_reject_misleading_encoding(kind: str, tmp_path: Path) -> None:
    raw = b"{}"
    (tmp_path / "source").write_bytes(raw)
    with pytest.raises(EvidenceError, match="does not use a declared"):
        evidence.BindingVerifier(tmp_path).verify({"path": "source", "bytes": len(raw), "sha256": _sha(raw), "role": "primary", "encoding": "latin-1", "locator": {"kind": kind, "value": "/x", "expected": True}})


def test_invalid_archive_hash_is_rejected_before_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "archive.zip").write_bytes(b"invalid archive")
    called = []
    monkeypatch.setattr(evidence, "_archive_member", lambda *args: called.append(args))
    binding = {"path": "archive.zip", "bytes": 15, "sha256": "0" * 64, "member": "a.txt"}
    with pytest.raises(EvidenceError, match="hash mismatch"):
        evidence.BindingVerifier(tmp_path).verify(binding)
    assert called == []


@pytest.mark.parametrize("mode", ["--write", "--check", "--verify-evidence"])
def test_cli_verifies_once_and_preserves_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str) -> None:
    _, _, worklist, decisions = _fixture(tmp_path)
    write_outputs(tmp_path, worklist_path=worklist, decisions_path=decisions)
    expected = build_report(tmp_path, worklist_path=worklist, decisions_path=decisions)
    if mode == "--write":
        expected["written"] = sorted(expected_outputs(tmp_path, worklist_path=worklist, decisions_path=decisions)[0])
    elif mode == "--check":
        expected["output_check"] = []
    calls = []
    verify = source_metadata.verify_evidence
    def counted(*args, **kwargs):
        calls.append(1)
        return verify(*args, **kwargs)
    monkeypatch.setattr(source_metadata, "verify_evidence", counted)
    assert metadata_main(["--root", str(tmp_path), "--worklist", str(worklist), "--decisions", str(decisions), mode, "--full-report"]) == 0
    assert len(calls) == 1
    assert capsys.readouterr().out == json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _review_fixture(tmp_path: Path):
    worklist, decision, work_path, decision_path = _fixture(tmp_path)
    entry = decision["decisions"][0]
    prototype = entry["dimensions"]["work"]["fields"][0]
    for dimension in DIMENSIONS[1:]:
        claim = copy.deepcopy(prototype)
        claim["worklist_item_id"] = f"{dimension}:sample"
        claim["claim_id"] = f"{dimension}-sample"
        claim["scope"]["predicate"] = dimension
        entry["dimensions"][dimension] = {"status": "inspected", "owner": "test", "fields": [claim]}
    decision_path.write_bytes(canonical_bytes(decision))
    selection_path = tmp_path / "selection.json"
    selection_path.write_bytes(canonical_bytes({"subjects": [entry["subject"]], "worklist_sha256": _sha(work_path.read_bytes())}))
    return worklist, decision, work_path, decision_path, selection_path


def test_preflight_complete_scope_and_missing_item(tmp_path: Path) -> None:
    _, decision, work, candidate, selection = _review_fixture(tmp_path)
    receipt, view, _ = review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)
    assert receipt["mechanical_status"] == "pass"
    assert receipt["semantic_review"] == "required"
    assert receipt["counts"]["expected_items"] == 5
    assert len(view["evidence"]) == 1
    assert len(view["claims"]) == 5
    decision["decisions"][0]["dimensions"]["work"]["fields"] = []
    candidate.write_bytes(canonical_bytes(decision))
    receipt, _, _ = review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)
    assert receipt["mechanical_status"] == "fail"
    assert [row["key"][-1] for row in receipt["failures"] if row["kind"] == "missing_item"] == ["work:title"]


def test_preflight_detects_missing_subject_from_independent_selection(tmp_path: Path) -> None:
    worklist, _, work, candidate, selection = _review_fixture(tmp_path)
    other = copy.deepcopy(worklist["subjects"][0])
    other["subject"]["id"] = "other-work"
    worklist["subjects"].append(other)
    work.write_bytes(canonical_bytes(worklist))
    selection.write_bytes(canonical_bytes({"subjects": [e["subject"] for e in worklist["subjects"]], "worklist_sha256": _sha(work.read_bytes())}))
    receipt, _, _ = review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)
    assert {"kind": "missing_subject", "key": ["catalog", "other-work"]} in receipt["failures"]
    selection.write_bytes(canonical_bytes({"subjects": [other["subject"]], "worklist_sha256": _sha(work.read_bytes())}))
    receipt, _, _ = review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)
    assert any(row["kind"] == "extra_subject" for row in receipt["failures"])


def test_preflight_rejects_wrong_dimension_and_unexamined(tmp_path: Path) -> None:
    _, decision, work, candidate, selection = _review_fixture(tmp_path)
    dims = decision["decisions"][0]["dimensions"]
    dims["edition"]["fields"][0]["worklist_item_id"] = "work:title"
    dims["work"]["status"] = "inherited_unexamined"
    candidate.write_bytes(canonical_bytes(decision))
    receipt, _, _ = review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)
    assert {row["kind"] for row in receipt["failures"]} >= {"missing_item", "extra_item", "unexamined"}


def test_review_receipt_drift_and_no_overwrite(tmp_path: Path) -> None:
    _, _, work, candidate, selection = _review_fixture(tmp_path)
    receipt, view, delta = review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)
    directory = tmp_path / "review"
    review.write_review(directory, tmp_path, receipt, view, delta)
    assert review.verify_receipt(receipt) == []
    with pytest.raises(FileExistsError):
        review.write_review(directory, tmp_path, receipt, view, delta)
    candidate.write_bytes(candidate.read_bytes() + b"\n")
    assert review.verify_receipt(receipt) == [{"artifact": "candidate", "message": "artifact identity changed"}]
    with pytest.raises(MetadataError, match="changed before"):
        review.write_review(tmp_path / "other-review", tmp_path, receipt, view, delta)


def test_preflight_requires_frozen_worklist_pin(tmp_path: Path) -> None:
    _, _, work, candidate, selection = _review_fixture(tmp_path)
    work.write_bytes(work.read_bytes() + b"\n")
    with pytest.raises(MetadataError, match="pin the exact"):
        review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)


def test_diff_catches_nonvalue_and_dimension_changes(tmp_path: Path) -> None:
    _, decision, _, _, _ = _review_fixture(tmp_path)
    before = decision["decisions"]
    after = copy.deepcopy(before)
    after[0]["dimensions"]["work"]["fields"][0]["inspection"]["owner"] = "new-owner"
    after[0]["dimensions"]["edition"]["status"] = "unavailable"
    delta = review.claim_diff(before, after)
    assert len(delta["changed"]) == 1
    assert len(delta["unchanged"]) == 4
    assert delta["structure_changed"]


def test_view_preserves_claims_and_flags_without_approving(tmp_path: Path) -> None:
    _, decision, _, _, _ = _review_fixture(tmp_path)
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["evidence"]["value"] = 426
    claim["evidence"]["bindings"][0]["locator"]["expected"] = "426 or 427"
    claim["adoption"]["classification"] = "not_applicable"
    view = review.review_view(decision["decisions"])
    assert {row["reason"].split(":")[0] for row in view["alerts"]} >= {"applicability", "date_qualifier"}
    for row in view["claims"]:
        restored = copy.deepcopy(row["claim"])
        refs = restored["evidence"].pop("binding_references")
        restored["evidence"]["bindings"] = [view["evidence"][ref] for ref in refs]
        assert restored == review._claim_map(decision["decisions"])[tuple(row["key"])]


def test_direct_unicode_and_latin1_extraction(tmp_path: Path) -> None:
    xml = '<root><p id="title">“Title”—author’s text</p></root>'.encode("utf-8")
    latin = 'Edition: édition ancienne.\r\n'.encode("latin-1")
    (tmp_path / "source.xml").write_bytes(xml)
    (tmp_path / "latin.txt").write_bytes(latin)
    result = review.extract_bindings(tmp_path, [
        {"id": "title", "path": "source.xml", "kind": "xml_id", "value": "title", "role": "primary"},
        {"id": "edition", "path": "latin.txt", "kind": "text", "encoding": "latin-1", "start_line": 1, "end_line": 1, "role": "primary"},
    ])
    assert result["bindings"]["title"]["locator"]["expected"] == '“Title”—author’s text'
    assert result["bindings"]["edition"]["locator"]["expected"] == 'Edition: édition ancienne.\r\n'
    assert (tmp_path / "latin.txt").read_bytes() == latin
    assert (tmp_path / "source.xml").read_bytes() == xml


def test_extraction_rejects_ambiguous_excerpt_and_path_escape(tmp_path: Path) -> None:
    (tmp_path / "text.txt").write_bytes(b"same\nsame\n")
    request = {"id": "x", "path": "text.txt", "kind": "text", "encoding": "utf-8", "start_line": 1, "end_line": 1, "role": "primary"}
    with pytest.raises(EvidenceError, match="not unique"):
        review.extract_bindings(tmp_path, [request])
    request["path"] = "../outside.txt"
    with pytest.raises(MetadataError):
        review.extract_bindings(tmp_path, [request])


def test_review_cli_complete_and_stale_receipt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, _, work, candidate, selection = _review_fixture(tmp_path)
    directory = tmp_path / "review"
    args = ["preflight", "--root", str(tmp_path), "--worklist", str(work), "--decisions", str(candidate), "--selection", str(selection), "--output-dir", str(directory)]
    assert review_main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["semantic_review"] == "required"
    assert review_main(["verify-receipt", str(directory / "receipt.json")]) == 0
    capsys.readouterr()
    (directory / "review.json").write_bytes(b"damaged")
    assert review_main(["verify-receipt", str(directory / "receipt.json")]) == 2
    assert json.loads(capsys.readouterr().out)["artifact_identity"] == "stale"


def test_xml_cache_separates_archive_members(tmp_path: Path) -> None:
    import zipfile
    path = tmp_path / "sources.zip"
    payloads = {"first.xml": b'<r id="t">First</r>', "second.xml": b'<r id="t">Second</r>'}
    with zipfile.ZipFile(path, "w") as archive:
        for name, raw in payloads.items():
            archive.writestr(name, raw)
    raw_archive = path.read_bytes()
    verifier = evidence.BindingVerifier(tmp_path)
    for name, raw in payloads.items():
        expected = "First" if name == "first.xml" else "Second"
        binding = {"path": path.name, "bytes": len(raw_archive), "sha256": _sha(raw_archive), "role": "primary",
                   "member": name, "member_bytes": len(raw), "member_sha256": _sha(raw),
                   "locator": {"kind": "xml_id", "value": "t", "expected": expected}}
        verifier.verify(binding)


def test_extraction_cli_writes_utf8_and_refuses_overwrite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "retained.txt"
    source.write_bytes('“Quoted”—text.\r\n'.encode('utf-8'))
    requests = tmp_path / "requests.json"
    requests.write_bytes(canonical_bytes({"requests": [{"id": "quote", "path": source.name, "kind": "text",
        "encoding": "utf-8", "start_line": 1, "end_line": 1, "role": "primary"}]}))
    output = tmp_path / "extracted.json"
    args = ["extract", "--root", str(tmp_path), "--requests", str(requests), "--output", str(output)]
    assert review_main(args) == 0
    capsys.readouterr()
    first = output.read_bytes()
    assert json.loads(first)["bindings"]["quote"]["locator"]["expected"] == '“Quoted”—text.\r\n'
    assert review_main(args) == 2
    assert output.read_bytes() == first


def test_review_outputs_cannot_target_authority_directory(tmp_path: Path) -> None:
    _, _, work, candidate, selection = _review_fixture(tmp_path)
    receipt, view, delta = review.preflight(tmp_path, worklist_path=work, decisions_path=candidate, selection_path=selection)
    with pytest.raises(MetadataError, match="authority directory"):
        review.write_review(tmp_path / "metadata/review", tmp_path, receipt, view, delta)
    assert not (tmp_path / "metadata").exists()


@pytest.mark.parametrize(
    "authority_name",
    [".git", "raw", "sources", "metadata", "data", "ir", "library", "schemas", "reports", "exports"],
)
def test_report_file_rejects_all_authority_directories(
    tmp_path: Path, authority_name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, work, candidate, _ = _review_fixture(tmp_path)
    authority = tmp_path / authority_name
    authority.mkdir()
    report_file = authority / "evidence-report.json"
    args = [
        "--root",
        str(tmp_path),
        "--worklist",
        str(work),
        "--decisions",
        str(candidate),
        "--verify-evidence",
        "--report-file",
        str(report_file),
    ]

    assert metadata_main(args) == 2
    assert "authority directory" in capsys.readouterr().err
    assert not report_file.exists()


def test_claim_view_preserves_absent_bindings(tmp_path: Path) -> None:
    _, decision, _, _, _ = _review_fixture(tmp_path)
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["evidence"] = {"classification": "unresolved", "question": "Which witness?", "evidence_needed": "Matching imprint"}
    row = next(row for row in review.review_view(decision["decisions"])["claims"] if row["key"][2] == "work")
    assert row["claim"]["evidence"] == claim["evidence"]


def test_scope_alert_distinguishes_workflow_from_factual_unknown(tmp_path: Path) -> None:
    _, decision, _, _, _ = _review_fixture(tmp_path)
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["worklist_item_id"] = "work:assessment_scope"
    claim["evidence"] = {"classification": "unresolved", "question": "Which atomic facts apply?", "evidence_needed": "Assess this dimension"}
    assert any(x["reason"].startswith("scope_question:") for x in review.review_view(decision["decisions"])["alerts"])
    claim["evidence"]["question"] = "Do the retained provider statements establish a physical edition?"
    claim["evidence"]["evidence_needed"] = "A primary edition imprint"
    assert not any(x["reason"].startswith("scope_question:") for x in review.review_view(decision["decisions"])["alerts"])


def test_verification_stdout_is_packet_summary_with_explicit_full_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    worklist, _, work, candidate = _fixture(tmp_path)
    for number in range(40):
        entry = copy.deepcopy(worklist["subjects"][0])
        entry["subject"]["id"] = f"unselected-{number}"
        worklist["subjects"].append(entry)
    work.write_bytes(canonical_bytes(worklist))
    args = ["--root", str(tmp_path), "--worklist", str(work), "--decisions", str(candidate), "--verify-evidence"]
    assert metadata_main(args) == 0
    compact = capsys.readouterr().out
    assert json.loads(compact)["scope"] == {"decision_subjects": 1}
    assert "unselected-" not in compact
    assert len(compact) < 2000
    assert metadata_main([*args, "--full-report"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["persistence"]["expected_subjects"] == 41
    assert "catalog:unselected-0" in full["missing_subjects"]


@pytest.mark.parametrize("mode", ["report", "check", "write", "verify"])
@pytest.mark.parametrize("render", ["default", "report-file", "full", "file-and-full"])
def test_report_cli_modes_emit_one_bounded_or_full_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    render: str,
) -> None:
    _worklist, _decision, worklist, decisions = _fixture(tmp_path)
    if mode == "check":
        write_outputs(tmp_path, worklist_path=worklist, decisions_path=decisions)

    args = ["--root", str(tmp_path), "--worklist", str(worklist), "--decisions", str(decisions)]
    args.extend({"report": [], "check": ["--check"], "write": ["--write"], "verify": ["--verify-evidence"]}[mode])
    report_file = tmp_path / "full-report.json"
    if render in {"report-file", "file-and-full"}:
        args.extend(["--report-file", str(report_file)])
    if render in {"full", "file-and-full"}:
        args.append("--full-report")

    calls: list[int] = []
    verify = source_metadata.verify_evidence

    def counted(*call_args, **call_kwargs):
        calls.append(1)
        return verify(*call_args, **call_kwargs)

    monkeypatch.setattr(source_metadata, "verify_evidence", counted)
    assert metadata_main(args) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    emitted = json.loads(captured.out)
    assert len(calls) == 1

    if render in {"full", "file-and-full"}:
        assert emitted["schema_version"] == "source-metadata-report-v1"
        if mode == "check":
            assert emitted["output_check"] == []
        if mode == "write":
            assert isinstance(emitted["written"], list)
    else:
        assert emitted["mode"] == mode
        assert isinstance(emitted["unverified_edges"], list)
        assert emitted["issues_omitted"] == 0
        if mode == "check":
            assert emitted["output_check"] == []
        if mode == "write":
            assert emitted["written"] == {"count": 2}

    if render in {"report-file", "file-and-full"}:
        retained = json.loads(report_file.read_text(encoding="utf-8"))
        assert retained["schema_version"] == "source-metadata-report-v1"
        if mode == "write":
            assert isinstance(retained["written"], list)
        if render == "file-and-full":
            assert retained == emitted


def test_check_summary_preserves_failure_exit_and_full_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, decision, worklist, decisions = _fixture(tmp_path)
    write_outputs(tmp_path, worklist_path=worklist, decisions_path=decisions)
    sidecar = tmp_path / sidecar_relative_path(decision["decisions"][0]["subject"])
    sidecar.write_bytes(b"changed")
    report_file = tmp_path / "failed-check.json"
    assert metadata_main([
        "--root", str(tmp_path), "--worklist", str(worklist), "--decisions", str(decisions),
        "--check", "--report-file", str(report_file),
    ]) == 2
    summary = json.loads(capsys.readouterr().out)
    full = json.loads(report_file.read_text(encoding="utf-8"))
    assert summary["mode"] == "check"
    assert len(summary["output_check"]) == len(full["output_check"]) == 1
    assert summary["output_check"][0]["message"] == full["output_check"][0]["message"]
    assert "missing_claims" not in summary
    assert "missing_claims" in full


def test_verification_cp1252_preserves_error_exit_and_utf8_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import sys
    _, decision, work, candidate = _fixture(tmp_path)
    decision["decisions"][0]["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]["locator"]["expected"] = "Missing α — text"
    candidate.write_bytes(canonical_bytes(decision))
    report_path = tmp_path / "full-report.json"
    output = io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
    args = ["--root", str(tmp_path), "--worklist", str(work), "--decisions", str(candidate), "--verify-evidence", "--report-file", str(report_path)]
    with monkeypatch.context() as context:
        context.setattr(sys, "stdout", console)
        assert metadata_main(args) == 2
        console.flush()
    emitted = output.getvalue()
    assert emitted.isascii()
    summary = json.loads(emitted)
    assert summary["evidence"]["unverified_edges"] == 1
    assert "α" in summary["unverified_edges"][0]["message"]
    full_bytes = report_path.read_bytes()
    assert 'α'.encode('utf-8') in full_bytes
    assert json.loads(full_bytes)["evidence"]["unverified_edges"] == 1
    assert metadata_main(args) == 2  # An existing report is never overwritten.
    assert report_path.read_bytes() == full_bytes


def test_full_stdout_and_error_diagnostics_are_console_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import sys
    from build.tools.report_source_metadata import _print
    output, errors = io.BytesIO(), io.BytesIO()
    console = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
    diagnostics = io.TextIOWrapper(errors, encoding="cp1252", errors="strict")
    with monkeypatch.context() as context:
        context.setattr(sys, "stdout", console)
        context.setattr(sys, "stderr", diagnostics)
        _print({"value": "α — edition"})
        assert metadata_main(["--root", str(tmp_path), "--worklist", str(tmp_path / "missing-α.json"), "--verify-evidence"]) == 2
        console.flush()
        diagnostics.flush()
    assert json.loads(output.getvalue())["value"] == "α — edition"
    assert errors.getvalue().isascii()


def test_verification_error_details_are_bounded_and_signal_omission() -> None:
    from build.tools.report_source_metadata import _verification_summary

    report = {
        "persistence": {"decided_subjects": 2},
        "evidence": {"unverified_edges": 25},
        "unverified_edges": [
            {"kind": "claim", "subject": "catalog:x", "claim_id": "title", "message": "x" * 10000}
            for _ in range(25)
        ],
        "output_check": [{"path": "p" * 10000, "message": "m" * 10000} for _ in range(25)],
        "written": [f"metadata/source-evidence/catalog/{number}.json" for number in range(25)],
    }
    summary = _verification_summary(report, "check")
    assert summary["mode"] == "check"
    assert summary["issues_omitted"] == 5
    assert summary["issues_truncated"] is True
    assert all(row["truncated"] for row in summary["unverified_edges"])
    assert summary["output_check_issues_omitted"] == 5
    assert summary["output_check_issues_truncated"] is True
    assert all(row["truncated"] for row in summary["output_check"])
    assert summary["written"] == {"count": 25}
    assert len(json.dumps(summary)) < 60000
