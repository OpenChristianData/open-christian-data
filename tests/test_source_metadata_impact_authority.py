"""Impact integration with real preflight authority snapshots and receipts."""

import copy

import pytest

from build.lib import source_metadata as sm, source_metadata_review as review
from build.lib.source_metadata_impact import recheck_claim_evidence
from tests.test_source_metadata_review import _comparison_fixture


def _prepared(tmp_path):
    root, work, decisions, selection, comparisons, authority, _ = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"})
    receipt, view, delta = review.preflight(
        root, worklist_path=work, decisions_path=decisions, selection_path=selection,
        authority_comparisons_path=comparisons)
    review.write_review(tmp_path / "review-output", root, receipt, view, delta)
    return root, authority, receipt, view


def test_authority_change_maps_to_claim_and_receipt_issue(tmp_path):
    root, authority, receipt, view = _prepared(tmp_path)
    assert recheck_claim_evidence(root, view, receipt)["counts"]["unchanged"] == 1
    authority.write_bytes(sm.canonical_bytes({"title": "New title"}))
    result = recheck_claim_evidence(root, view, receipt)
    assert result["counts"]["changed"] == 1
    assert result["changed"][0]["claim_id"] == "retained-title"
    assert result["receipt_issues"]
    assert any(check["kind"] == "authority_comparison" and "selector_value" in check["changes"]
               for check in result["changed"][0]["checks"])


def test_retained_view_must_match_receipt(tmp_path):
    root, _, receipt, view = _prepared(tmp_path)
    altered = copy.deepcopy(view)
    altered["notice"] = "Changed review"
    with pytest.raises(sm.MetadataError, match="does not match"):
        recheck_claim_evidence(root, altered, receipt)


def test_identical_authority_bytes_at_new_route_still_affect_exact_claim(tmp_path, monkeypatch):
    root, authority, receipt, view = _prepared(tmp_path)
    successor = root / "successor.json"
    successor.write_bytes(authority.read_bytes())
    original = sm._resolve

    def retarget(root_path, value, *, field):
        return successor if value == "authority.json" else original(root_path, value, field=field)

    monkeypatch.setattr(sm, "_resolve", retarget)
    result = recheck_claim_evidence(root, view, receipt)
    assert result["counts"]["changed"] == 1
    assert any("resolved_path" in check["changes"] for check in result["changed"][0]["checks"])


def test_receipt_keeps_worklist_disambiguation_for_shared_scope(tmp_path):
    root, work, decisions, selection, comparisons, _, _ = _comparison_fixture(
        tmp_path, authority_payload={"title": "Retained title"})
    worklist = sm.load_json(work)
    items = worklist["subjects"][0]["dimensions"]["work"]["items"]
    items.append({**copy.deepcopy(items[0]), "item_id": "work:alternate_title", "field": "alternate_title"})
    work.write_bytes(sm.canonical_bytes(worklist))
    selected = sm.load_json(selection)
    selected["worklist_sha256"] = review.file_identity(work)["sha256"]
    selection.write_bytes(sm.canonical_bytes(selected))
    document = sm.load_json(decisions)
    fields = document["decisions"][0]["dimensions"]["work"]["fields"]
    fields.append({**copy.deepcopy(fields[0]), "claim_id": "alternate-title", "worklist_item_id": "work:alternate_title"})
    decisions.write_bytes(sm.canonical_bytes(document))
    receipt, view, delta = review.preflight(root, worklist_path=work, decisions_path=decisions,
        selection_path=selection, authority_comparisons_path=comparisons)
    assert receipt["mechanical_status"] == "pass"
    review.write_review(tmp_path / "review-output", root, receipt, view, delta)
    assert recheck_claim_evidence(root, view, receipt)["counts"]["unchanged"] == 2


def test_receipt_cannot_replace_historical_authority_snapshot(tmp_path):
    root, authority, receipt, view = _prepared(tmp_path)
    authority.write_bytes(sm.canonical_bytes({"title": "New title"}))
    receipt["authority_comparisons"][0]["authority"] = review._read_authority(
        authority, path_text="authority.json", selector="/title")
    with pytest.raises(sm.MetadataError, match="snapshot differs"):
        recheck_claim_evidence(root, view, receipt)
