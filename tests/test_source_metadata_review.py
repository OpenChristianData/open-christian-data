"""Focused regressions for fail-closed metadata review inputs and outputs."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from build.lib import source_metadata_review as review
from build.lib.source_metadata import MetadataError, canonical_bytes
from build.tools.review_source_metadata import main as review_main


_REQUIRED_ARTIFACTS = ("worklist", "candidate", "selection", "engine", "review_engine", "schema")
_AUTHORITY_ROOTS = (
    ".git",
    "raw",
    "sources",
    "metadata",
    "data",
    "ir",
    "library",
    "schemas",
    "reports",
    "exports",
)


def _receipt(tmp_path: Path) -> tuple[dict, Path]:
    artifact = tmp_path / "input.json"
    artifact.write_bytes(b"{}\n")
    identity = review.file_identity(artifact)
    return {
        "format": "source-metadata-review-receipt-v1",
        "artifacts": {name: dict(identity) for name in _REQUIRED_ARTIFACTS},
    }, artifact


def _view() -> dict:
    return {"notice": "review", "structure": [], "claims": [], "evidence": {}, "alerts": []}


def _comparison_fixture(
    tmp_path: Path,
    *,
    authority_payload: object | None = None,
    selector: str = "/title",
) -> tuple[Path, Path, Path, Path, Path, Path, dict[str, object]]:
    """Build one complete subject and a primary binding for comparison tests."""

    root = tmp_path / "root"
    root.mkdir()
    evidence = {"title": "Retained title"}
    evidence_path = root / "evidence.json"
    evidence_path.write_bytes(canonical_bytes(evidence))
    evidence_identity = review.file_identity(evidence_path)
    subject = {"kind": "catalog", "id": "synthetic-work"}
    scope = {"member": "evidence.json", "entity": "work", "predicate": "title", "event_role": "none"}
    item = {
        "item_id": "work:title",
        "field": "title",
        "source_packet": "evidence.json",
        "input_pointer": "/title",
        "input_value": "Retained title",
        "input_sha256": evidence_identity["sha256"],
        "requirement": "useful_optional",
        "repair_required": False,
    }
    dimensions = {
        name: {"items": [dict(item)] if name == "work" else []}
        for name in ("work", "edition", "textual_form", "witnesses", "parts")
    }
    worklist = {
        "schema_version": "source-metadata-worklist-v1",
        "writer": "ocd-source-metadata-v1",
        "batch_id": "comparison-test",
        "subjects": [{"subject": subject, "dimensions": dimensions}],
    }
    binding = {
        "path": "evidence.json",
        "sha256": evidence_identity["sha256"],
        "bytes": evidence_identity["bytes"],
        "role": "primary",
        "locator": {"kind": "json_pointer", "value": "/title", "expected": "Retained title"},
    }
    claim = {
        "worklist_item_id": "work:title",
        "claim_id": "retained-title",
        "scope": scope,
        "evidence": {
            "classification": "supported",
            "value": "Retained title",
            "bindings": [binding],
        },
        "requirement": {"classification": "useful_optional", "reason": "comparison test"},
        "adoption": {"classification": "supported_unapplied", "destination": "source_evidence_only"},
        "inspection": {"classification": "inspected", "owner": "test", "evidence": "evidence.json#/title"},
    }
    decision = {
        "schema_version": "source-metadata-decisions-v1",
        "writer": "ocd-source-metadata-v1",
        "batch_id": "comparison-test",
        "decisions": [{
            "subject": subject,
            "dimensions": {
                name: {
                    "status": "inspected",
                    "owner": "test",
                    "fields": [claim] if name == "work" else [],
                }
                for name in ("work", "edition", "textual_form", "witnesses", "parts")
            },
        }],
    }
    worklist_path = root / "worklist.json"
    decisions_path = root / "decisions.json"
    selection_path = root / "selection.json"
    worklist_path.write_bytes(canonical_bytes(worklist))
    decisions_path.write_bytes(canonical_bytes(decision))
    selection_path.write_bytes(
        canonical_bytes({
            "subjects": [subject],
            "worklist_sha256": review.file_identity(worklist_path)["sha256"],
        })
    )
    authority_path = root / "authority.json"
    if authority_payload is not None:
        authority_path.write_bytes(canonical_bytes(authority_payload))
    comparison_path = root / "comparisons.json"
    comparison_path.write_bytes(
        canonical_bytes({
            "schema_version": "source-metadata-authority-comparisons-v1",
            "comparisons": [{
                "subject": subject,
                "field": "title",
                "scope": scope,
                "authority": {"path": "authority.json", "selector": selector},
                "evidence_references": [review._binding_reference(binding)],
                "review": {"disposition": "pending", "note": "test review"},
            }],
        })
    )
    return (
        root,
        worklist_path,
        decisions_path,
        selection_path,
        comparison_path,
        authority_path,
        {"subject": subject, "scope": scope, "binding": binding},
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sha256", "not-a-digest", "sha256"),
        ("sha256", b"0" * 32, "sha256"),
        ("bytes", True, "bytes"),
        ("bytes", -1, "bytes"),
        ("path", "relative.json", "absolute"),
    ],
)
def test_receipt_identity_types_fail_closed(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    receipt, _artifact = _receipt(tmp_path)
    receipt["artifacts"]["candidate"][field] = value
    with pytest.raises(MetadataError, match=message):
        review.verify_receipt(receipt)


def test_non_object_receipt_is_a_metadata_error() -> None:
    with pytest.raises(MetadataError, match="JSON object"):
        review.verify_receipt([])


@pytest.mark.parametrize(
    "requests",
    [
        None,
        {},
        [{"id": "x", "path": "source.txt", "kind": [], "role": "primary"}],
        [{"id": "x", "path": "source.txt", "kind": "text", "encoding": [], "start_line": 1, "end_line": 1, "role": "primary"}],
    ],
)
def test_malformed_extraction_requests_raise_metadata_error(
    tmp_path: Path, requests: object
) -> None:
    (tmp_path / "source.txt").write_bytes(b"one\n")
    with pytest.raises(MetadataError):
        review.extract_bindings(tmp_path, requests)  # type: ignore[arg-type]


def test_text_extraction_decode_failure_is_a_metadata_error(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_bytes(b"\xff\n")
    request = {
        "id": "x",
        "path": "source.txt",
        "kind": "text",
        "encoding": "utf-8",
        "start_line": 1,
        "end_line": 1,
        "role": "primary",
    }
    with pytest.raises(MetadataError, match="cannot decode"):
        review.extract_bindings(tmp_path, [request])


def test_write_review_rehashes_generated_artifacts_before_receipt(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    receipt, _artifact = _receipt(tmp_path)
    destination = root / "review"

    review.write_review(destination, root, receipt, _view(), None)

    assert {"review.json", "review.md"} <= set(receipt["artifacts"])
    assert review.verify_receipt(receipt) == []
    on_disk = json.loads((destination / "receipt.json").read_text(encoding="utf-8"))
    assert review.verify_receipt(on_disk) == []
    (destination / "review.md").write_bytes(b"changed")
    assert review.verify_receipt(on_disk) == [{"artifact": "review.md", "message": "artifact identity changed"}]


def test_write_review_rejects_input_and_authority_destinations(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    receipt, artifact = _receipt(tmp_path)

    with pytest.raises(MetadataError, match="input path"):
        review.write_review(artifact, root, receipt, _view(), None)

    with pytest.raises(MetadataError, match="authority directory"):
        review.write_review(root / "metadata" / "review", root, receipt, _view(), None)
    assert not (root / "metadata").exists()


@pytest.mark.parametrize("authority_name", _AUTHORITY_ROOTS)
def test_review_output_rejects_direct_authority_roots(
    tmp_path: Path, authority_name: str
) -> None:
    output = tmp_path / authority_name / "review"

    with pytest.raises(MetadataError, match="authority directory"):
        review._safe_output_path(output, tmp_path, field="review output")


def test_cli_malformed_receipt_returns_exit_two_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt, _artifact = _receipt(tmp_path)
    receipt["artifacts"]["candidate"]["bytes"] = True
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt))

    assert review_main(["verify-receipt", str(receipt_path)]) == 2
    captured = capsys.readouterr()
    assert "metadata review error" in captured.err
    assert "Traceback" not in captured.err


def test_cli_error_diagnostic_is_ascii_on_strict_cp1252(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = tmp_path / "requests.json"
    requests.write_bytes(
        canonical_bytes(
            {
                "requests": [
                    {
                        "id": "x",
                        "path": "é.txt",
                        "kind": "text",
                        "encoding": "utf-8",
                        "start_line": 1,
                        "end_line": 1,
                        "role": "primary",
                    }
                ]
            }
        )
    )
    stderr_bytes = io.BytesIO()
    strict_stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stderr", strict_stderr)

    assert review_main(
        [
            "extract",
            "--root",
            str(tmp_path),
            "--requests",
            str(requests),
            "--output",
            str(tmp_path / "output.json"),
        ]
    ) == 2
    strict_stderr.flush()
    diagnostic = stderr_bytes.getvalue()
    assert b"metadata review error" in diagnostic
    assert b"\\xe9.txt" in diagnostic


def test_cli_extraction_cannot_target_source_or_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(b"one\n")
    requests = tmp_path / "requests.json"
    requests.write_bytes(
        canonical_bytes(
            {
                "requests": [
                    {
                        "id": "x",
                        "path": source.name,
                        "kind": "text",
                        "encoding": "utf-8",
                        "start_line": 1,
                        "end_line": 1,
                        "role": "primary",
                    }
                ]
            }
        )
    )

    assert review_main(
        ["extract", "--root", str(tmp_path), "--requests", str(requests), "--output", str(source)]
    ) == 2
    assert source.read_bytes() == b"one\n"
    assert "Traceback" not in capsys.readouterr().err

    authority_output = tmp_path / "metadata" / "extracted.json"
    assert review_main(
        [
            "extract",
            "--root",
            str(tmp_path),
            "--requests",
            str(requests),
            "--output",
            str(authority_output),
        ]
    ) == 2
    assert not authority_output.exists()
    assert not (tmp_path / "metadata").exists()


def test_authority_comparison_maps_current_value_and_binds_receipt(
    tmp_path: Path,
) -> None:
    root, worklist, decisions, selection, comparisons, _authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    receipt, view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )

    row = view["authority_comparisons"][0]
    assert row["mapped_value"] == "Retained title"
    assert row["mapped_claim"] == {
        "worklist_item_id": "work:title",
        "claim_id": "retained-title",
        "evidence_classification": "supported",
    }
    assert row["comparison"] == "match"
    assert row["authority"]["availability"] == "available"
    assert row["authority"]["value"] == "Retained title"
    assert row["authority"]["raw_sha256"]
    assert row["authority"]["bytes"] > 0
    assert receipt["artifacts"]["authority_comparisons"]["path"] == str(comparisons.resolve())
    assert receipt["authority_comparisons"][0]["authority"]["raw_sha256"]
    assert review.verify_receipt(receipt) == []
    assert all("adopt" not in alert["message"].lower() for alert in view["alerts"] if alert.get("kind") == "authority_comparison")
    rendered = review.render_review(view)
    assert "## Current authority comparisons" in rendered
    assert '"value": "Retained title"' in rendered
    assert '"mapped_value": "Retained title"' in rendered
    assert '"disposition": "pending"' in rendered
    assert receipt["authority_comparisons"][0]["authority"]["raw_sha256"] in rendered


def test_unavailable_authority_is_visible_and_does_not_fail_receipt(
    tmp_path: Path,
) -> None:
    root, worklist, decisions, selection, comparisons, authority, _details = _comparison_fixture(tmp_path)
    receipt, view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )

    authority_view = view["authority_comparisons"][0]["authority"]
    assert authority_view["path"] == "authority.json"
    assert authority_view["selector"] == "/title"
    assert authority_view["availability"] == "unavailable"
    assert authority_view["path_available"] is False
    assert authority_view["selector_available"] is False
    assert authority_view["reason"] == "path_unavailable"
    assert authority_view["raw_sha256"] is None
    assert review.verify_receipt(receipt) == []

    authority.write_bytes(canonical_bytes({"title": "Retained title"}))
    issues = review.verify_receipt(receipt)
    assert issues == [{"artifact": "authority_comparison[0]", "message": "authority availability changed"}]


def test_authority_presence_loss_and_selector_availability_are_stale(
    tmp_path: Path,
) -> None:
    root, worklist, decisions, selection, comparisons, authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"other": "value"}
    )
    receipt, _view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )
    assert review.verify_receipt(receipt) == []
    authority.unlink()
    assert review.verify_receipt(receipt)[0]["message"] == "authority availability changed"

    authority.write_bytes(canonical_bytes({"other": "value", "title": "Retained title"}))
    # The receipt still expects a missing path from the first read; a fresh
    # available file must remain stale even if its mapped value is correct.
    assert review.verify_receipt(receipt)[0]["message"] == "authority availability changed"


def test_authority_raw_value_drift_is_stale(tmp_path: Path) -> None:
    root, worklist, decisions, selection, comparisons, authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    receipt, _view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )
    authority.write_bytes(canonical_bytes({"title": "Changed title"}))
    assert review.verify_receipt(receipt) == [
        {"artifact": "authority_comparison[0]", "message": "authority raw identity changed"}
    ]


@pytest.mark.parametrize(
    "change",
    [
        lambda row: row.update(authority={"path": "../outside.json", "selector": "/title"}),
        lambda row: row.update(authority={"path": "authority.json", "selector": "/bad~2escape"}),
        lambda row: row.update(evidence_references=["0" * 64]),
        lambda row: row.update(review={"disposition": ""}),
        lambda row: row.update(extra=True),
    ],
)
def test_authority_comparison_input_fails_closed(tmp_path: Path, change) -> None:
    root, worklist, decisions, selection, comparisons, _authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    payload = json.loads(comparisons.read_text(encoding="utf-8"))
    change(payload["comparisons"][0])
    comparisons.write_bytes(canonical_bytes(payload))
    with pytest.raises(MetadataError):
        review.preflight(
            root,
            worklist_path=worklist,
            decisions_path=decisions,
            selection_path=selection,
            authority_comparisons_path=comparisons,
        )


def test_numeric_pointer_is_context_sensitive_for_object_and_array(tmp_path: Path) -> None:
    assert review._strict_pointer_value({"00": "object"}, "/00") == "object"
    with pytest.raises(KeyError):
        review._strict_pointer_value(["array"], "/00")


def test_long_array_pointer_is_unavailable_through_preflight_and_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, worklist, decisions, selection, comparisons, _authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": ["Retained title"]}
    )
    payload = json.loads(comparisons.read_text(encoding="utf-8"))
    payload["comparisons"][0]["authority"]["selector"] = "/title/" + ("9" * 5000)
    comparisons.write_bytes(canonical_bytes(payload))

    receipt, view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )
    authority_view = view["authority_comparisons"][0]["authority"]
    assert authority_view["availability"] == "unavailable"
    assert authority_view["reason"] == "selector_unavailable"
    assert review.verify_receipt(receipt) == []

    output = root / "review-long-pointer"
    assert review_main([
        "preflight",
        "--root", str(root),
        "--worklist", str(worklist),
        "--decisions", str(decisions),
        "--selection", str(selection),
        "--authority-comparisons", str(comparisons),
        "--output-dir", str(output),
    ]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"]["authority_comparisons"] == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("availability", [], "availability"),
        ("availability", {}, "availability"),
        ("reason", [], "unavailable reason"),
        ("reason", {}, "unavailable reason"),
    ],
)
def test_verify_receipt_rejects_untyped_authority_snapshot_states(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    root, worklist, decisions, selection, comparisons, _authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    receipt, _view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )
    malformed = json.loads(json.dumps(receipt))
    malformed["authority_comparisons"][0]["authority"][field] = value
    with pytest.raises(MetadataError, match=message):
        review.verify_receipt(malformed)


def test_authority_comparison_references_must_be_same_scope_primary_binding(
    tmp_path: Path,
) -> None:
    root, worklist, decisions, selection, comparisons, _authority, details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    payload = json.loads(comparisons.read_text(encoding="utf-8"))
    payload["comparisons"][0]["scope"]["predicate"] = "other"
    comparisons.write_bytes(canonical_bytes(payload))
    with pytest.raises(MetadataError, match="same-scope claim"):
        review.preflight(
            root,
            worklist_path=worklist,
            decisions_path=decisions,
            selection_path=selection,
            authority_comparisons_path=comparisons,
        )

    # A non-primary reference cannot be smuggled in as a source mapping.
    claim = json.loads(decisions.read_text(encoding="utf-8"))
    claim["decisions"][0]["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]["role"] = "observation"
    decisions.write_bytes(canonical_bytes(claim))
    payload["comparisons"][0]["scope"]["predicate"] = "title"
    observed_binding = claim["decisions"][0]["dimensions"]["work"]["fields"][0]["evidence"]["bindings"][0]
    payload["comparisons"][0]["evidence_references"] = [review._binding_reference(observed_binding)]
    comparisons.write_bytes(canonical_bytes(payload))
    with pytest.raises(MetadataError, match="primary retained-evidence"):
        review.preflight(
            root,
            worklist_path=worklist,
            decisions_path=decisions,
            selection_path=selection,
            authority_comparisons_path=comparisons,
        )


def test_no_authority_comparison_preserves_legacy_view_and_receipt_shape(
    tmp_path: Path,
) -> None:
    root, worklist, decisions, selection, _comparisons, _authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    receipt, view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
    )
    assert "authority_comparisons" not in receipt
    assert "authority_comparison_root" not in receipt
    assert "authority_comparisons" not in view
    assert review.verify_receipt(receipt) == []


def test_write_review_protects_unavailable_authority_path(tmp_path: Path) -> None:
    root, worklist, decisions, selection, comparisons, authority, _details = _comparison_fixture(tmp_path)
    receipt, view, delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )
    with pytest.raises(MetadataError, match="replace input path"):
        review.write_review(authority, root, receipt, view, delta)
    assert not authority.exists()


@pytest.mark.parametrize("authority_name", ["review.json", "receipt.json"])
def test_write_review_rejects_output_ancestor_of_absent_authority(
    tmp_path: Path, authority_name: str
) -> None:
    root, worklist, decisions, selection, comparisons, _authority, _details = _comparison_fixture(tmp_path)
    payload = json.loads(comparisons.read_text(encoding="utf-8"))
    payload["comparisons"][0]["authority"]["path"] = f"review/{authority_name}"
    comparisons.write_bytes(canonical_bytes(payload))
    receipt, view, delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )
    output = root / "review"
    with pytest.raises(MetadataError, match="authority input path"):
        review.write_review(output, root, receipt, view, delta)
    assert not output.exists()
    assert not (output / authority_name).exists()


def test_opt_in_receipt_requires_comparison_input_and_root(tmp_path: Path) -> None:
    root, worklist, decisions, selection, comparisons, _authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    receipt, _view, _delta = review.preflight(
        root,
        worklist_path=worklist,
        decisions_path=decisions,
        selection_path=selection,
        authority_comparisons_path=comparisons,
    )
    missing_artifact = json.loads(json.dumps(receipt))
    del missing_artifact["artifacts"]["authority_comparisons"]
    with pytest.raises(MetadataError, match="input artifact"):
        review.verify_receipt(missing_artifact)

    missing_snapshot = json.loads(json.dumps(receipt))
    del missing_snapshot["authority_comparisons"]
    with pytest.raises(MetadataError, match="incomplete"):
        review.verify_receipt(missing_snapshot)


def test_cli_authority_comparison_writes_current_section(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, worklist, decisions, selection, comparisons, _authority, _details = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"}
    )
    output = root / "review"
    args = [
        "preflight",
        "--root", str(root),
        "--worklist", str(worklist),
        "--decisions", str(decisions),
        "--selection", str(selection),
        "--authority-comparisons", str(comparisons),
        "--output-dir", str(output),
    ]
    assert review_main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"]["authority_comparisons"] == 1
    rendered = (output / "review.md").read_text(encoding="utf-8")
    assert "## Current authority comparisons" in rendered
    assert '"disposition": "pending"' in rendered
    assert review_main(["verify-receipt", str(output / "receipt.json")]) == 0
    capsys.readouterr()
