"""Focused regressions for read-only source-metadata impact rechecks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.lib import source_metadata as sm
from build.lib import source_metadata_review as review
from build.lib.source_metadata_impact import recheck_claim_evidence
from build.tools.review_source_metadata import main as review_main


_REQUIRED_ARTIFACTS = ("worklist", "candidate", "selection", "engine", "review_engine", "schema")


def _review_fixture(
    tmp_path: Path,
    *,
    include_second: bool = False,
    with_target: bool = False,
    typed: bool = False,
    latin1: bool = False,
) -> tuple[Path, dict, dict[str, Path]]:
    """Create a generated review view with one or two exact source bindings."""

    root = tmp_path / "root"
    root.mkdir()
    subject = {"kind": "catalog", "id": "synthetic-work"}
    claims: list[dict] = []
    paths: dict[str, Path] = {}

    specifications = [("evidence.json", "retained-title", "work:title", "Retained title")]
    if include_second:
        specifications.append(("other.json", "other-title", "work:other-title", "Other title"))

    for index, (name, claim_id, item_id, value) in enumerate(specifications):
        path = root / name
        if latin1 and index == 0:
            path.write_bytes("Café\n".encode("latin-1"))
            source_value = "Café"
            source_kind = "text"
            locator = {"kind": source_kind, "value": "Caf", "expected": source_value}
            binding_encoding = "latin-1"
        else:
            path.write_bytes(sm.canonical_bytes({"title": value, "version": "one"}))
            source_value = value
            locator = {"kind": "json_pointer", "value": "/title", "expected": source_value}
            binding_encoding = None
        paths[name] = path
        identity = review.file_identity(path)
        binding = {
            "path": name,
            "sha256": identity["sha256"],
            "bytes": identity["bytes"],
            "role": "primary",
            "locator": locator,
        }
        if binding_encoding is not None:
            binding["encoding"] = binding_encoding

        scope = {
            "member": name,
            "entity": "work",
            "predicate": "publication_date" if typed and index == 0 else "title",
            "event_role": "first_publication" if typed and index == 0 else "none",
        }
        claim = {
            "worklist_item_id": item_id,
            "claim_id": claim_id,
            "scope": scope,
            "evidence": {
                "classification": "supported",
                "value": source_value,
                "bindings": [binding],
            },
            "requirement": {"classification": "useful_optional", "reason": "impact test"},
            "adoption": {"classification": "supported_unapplied", "destination": "source_evidence_only"},
            "inspection": {"classification": "inspected", "owner": "test", "evidence": f"{name}#selected"},
        }
        if typed and index == 0:
            claim["semantics"] = {
                "kind": "publication_event",
                "predicate": "publication_date",
                "event": "first_publication",
                "scope": "work",
            }
        if with_target and index == 0:
            target_path = root / "target.json"
            target_path.write_bytes(sm.canonical_bytes({"title": value, "version": "one"}))
            target_identity = review.file_identity(target_path)
            paths["target.json"] = target_path
            claim["adoption"] = {
                "classification": "adopted",
                "destination": "v2",
                "target": {
                    "path": "target.json",
                    "selector": "/title",
                    "expected_value": value,
                    "current_raw_sha256": target_identity["sha256"],
                    "value_check": True,
                },
            }
        claims.append(claim)

    entry = {
        "subject": subject,
        "dimensions": {
            "work": {"status": "inspected", "owner": "test", "fields": claims},
        },
    }
    return root, review.review_view([entry]), paths


def _stale_receipt(path: Path, review_path: Path | None = None) -> dict:
    identity = review.file_identity(path)
    artifacts = {name: dict(identity) for name in _REQUIRED_ARTIFACTS}
    if review_path is not None:
        artifacts["review.json"] = review.file_identity(review_path)
    return {
        "format": "source-metadata-review-receipt-v1",
        "artifacts": artifacts,
    }


def test_unchanged_binding_reports_detailed_claim_identity(tmp_path: Path) -> None:
    root, view, _paths = _review_fixture(tmp_path)

    result = recheck_claim_evidence(root, view)

    assert result["counts"]["unchanged"] == 1
    assert result["counts"]["changed"] == 0
    assert result["counts"]["missing"] == 0
    assert result["counts"]["unverifiable"] == 0
    assert result["counts"]["checked_claims"] == 1
    assert result["counts"]["unchecked_claims"] == 0
    assert result["receipt_issues"] == []
    row = result["claims"][0]
    assert row["subject"] == {"kind": "catalog", "id": "synthetic-work"}
    assert row["dimension"] == "work"
    assert row["claim_id"] == "retained-title"
    assert row["worklist_item_id"] == "work:title"
    assert row["scope"]["predicate"] == "title"
    assert row["status"] == "unchanged"
    assert row["checks"][0]["selector_status"] == "unchanged"


def test_raw_hash_drift_is_changed_even_when_selected_json_value_is_unchanged(
    tmp_path: Path,
) -> None:
    root, view, paths = _review_fixture(tmp_path)
    paths["evidence.json"].write_bytes(sm.canonical_bytes({"title": "Retained title", "version": "two"}))

    result = recheck_claim_evidence(root, view)

    assert result["counts"]["changed"] == 1
    assert result["counts"]["unchanged"] == 0
    check = result["changed"][0]["checks"][0]
    assert check["status"] == "changed"
    assert "file_hash" in check["changes"]
    assert "selector_value" not in check["changes"]
    assert check["selector_status"] == "unchanged"
    assert check["current"]["selector_value"] == "Retained title"


def test_selected_json_value_drift_is_changed(tmp_path: Path) -> None:
    root, view, paths = _review_fixture(tmp_path)
    paths["evidence.json"].write_bytes(sm.canonical_bytes({"title": "Changed title", "version": "one"}))

    result = recheck_claim_evidence(root, view)

    assert result["counts"]["changed"] == 1
    check = result["changed"][0]["checks"][0]
    assert "selector_value" in check["changes"]
    assert check["selector_status"] == "changed"
    assert check["current"]["selector_value"] == "Changed title"


def test_missing_source_is_reported_as_missing(tmp_path: Path) -> None:
    root, view, paths = _review_fixture(tmp_path)
    paths["evidence.json"].unlink()

    result = recheck_claim_evidence(root, view)

    assert result["counts"]["missing"] == 1
    assert result["counts"]["changed"] == 0
    assert result["missing"][0]["checks"][0]["changes"] == ["path_missing"]


def test_path_filter_leaves_unrelated_claim_unchecked(tmp_path: Path) -> None:
    root, view, _paths = _review_fixture(tmp_path, include_second=True)

    result = recheck_claim_evidence(root, view, paths=["evidence.json"])

    assert result["counts"]["checked_claims"] == 1
    assert result["counts"]["unchecked_claims"] == 1
    assert result["counts"]["unchanged"] == 1
    assert result["counts"]["changed"] == 0
    assert [row["claim_id"] for row in result["claims"]] == ["retained-title"]
    assert result["scope"]["unchecked_claims"] == 1


@pytest.mark.parametrize("reference", ["not-a-digest", "0" * 64])
def test_malformed_or_dangling_binding_reference_fails_closed(
    tmp_path: Path, reference: str
) -> None:
    root, view, _paths = _review_fixture(tmp_path)
    view["evidence"] = {}
    view["claims"][0]["claim"]["evidence"]["binding_references"] = [reference]

    with pytest.raises(sm.MetadataError):
        recheck_claim_evidence(root, view)


def test_adoption_target_drift_marks_claim_changed(tmp_path: Path) -> None:
    root, view, paths = _review_fixture(tmp_path, with_target=True)
    paths["target.json"].write_bytes(sm.canonical_bytes({"title": "Retained title", "version": "two"}))

    result = recheck_claim_evidence(root, view)

    assert result["counts"]["changed"] == 1
    target_check = next(check for check in result["changed"][0]["checks"] if check["kind"] == "adoption_target")
    assert "file_hash" in target_check["changes"]
    assert "selector_value" not in target_check["changes"]
    assert target_check["selector_status"] == "unchanged"


def test_stale_receipt_is_reported_separately_from_claim_status(tmp_path: Path) -> None:
    root, view, _paths = _review_fixture(tmp_path)
    review_path = root / "review.json"
    review_path.write_bytes(sm.canonical_bytes(view))
    receipt_input = tmp_path / "receipt-input.json"
    receipt_input.write_bytes(b"initial\n")
    receipt = _stale_receipt(receipt_input, review_path)
    receipt_input.write_bytes(b"changed\n")

    result = recheck_claim_evidence(root, view, receipt=receipt)

    assert result["counts"]["unchanged"] == 1
    assert result["counts"]["changed"] == 0
    assert result["receipt_issues"]
    assert result["counts"]["receipt_issues"] == len(result["receipt_issues"])


def test_receipt_rejects_a_supplied_view_that_differs_from_review_json(tmp_path: Path) -> None:
    root, view, _paths = _review_fixture(tmp_path)
    review_path = root / "review.json"
    review_path.write_bytes(sm.canonical_bytes(view))
    receipt_input = tmp_path / "receipt-input.json"
    receipt_input.write_bytes(b"stable\n")
    receipt = _stale_receipt(receipt_input, review_path)
    tampered_view = json.loads(json.dumps(view))
    tampered_view["notice"] = "tampered review view"

    with pytest.raises(sm.MetadataError, match="does not match"):
        recheck_claim_evidence(root, tampered_view, receipt=receipt)


def test_typed_claim_is_accepted_from_generated_review_view(tmp_path: Path) -> None:
    root, view, _paths = _review_fixture(tmp_path, typed=True)

    result = recheck_claim_evidence(root, view)

    assert result["counts"]["unchanged"] == 1
    assert result["claims"][0]["scope"]["predicate"] == "publication_date"
    assert view["claims"][0]["claim"]["semantics"]["event"] == "first_publication"


def test_latin1_binding_encoding_is_used_for_selector_recheck(tmp_path: Path) -> None:
    root, view, _paths = _review_fixture(tmp_path, latin1=True)

    result = recheck_claim_evidence(root, view)

    assert result["counts"]["unchanged"] == 1
    check = result["unchanged"][0]["checks"][0]
    assert check["selector_status"] == "unchanged"
    assert check["current"]["selector_value"] == "Café"


def test_cli_impact_returns_zero_for_unchanged_and_two_for_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, view, paths = _review_fixture(tmp_path)
    review_path = root / "review.json"
    review_path.write_bytes(sm.canonical_bytes(view))
    args = ["impact", "--root", str(root), "--review", str(review_path)]

    assert review_main(args) == 0
    unchanged_stdout = json.loads(capsys.readouterr().out)
    assert unchanged_stdout["counts"]["unchanged"] == 1
    assert unchanged_stdout["counts"]["changed"] == 0

    paths["evidence.json"].write_bytes(sm.canonical_bytes({"title": "Changed title", "version": "one"}))
    assert review_main(args) == 2
    changed_stdout = json.loads(capsys.readouterr().out)
    assert changed_stdout["counts"]["unchanged"] == 0
    assert changed_stdout["counts"]["changed"] == 1
    assert "claims" not in changed_stdout
    assert changed_stdout["affected_claims"][0]["claim_id"] == "retained-title"
    assert review_main([*args, "--full-json"]) == 2
    full = json.loads(capsys.readouterr().out)
    assert full["claims"][0]["checks"][0]["historical"]
    assert full["counts"] == changed_stdout["counts"]
