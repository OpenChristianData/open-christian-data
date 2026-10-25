"""Focused guards for exact LIB-055 electronic-witness acceptance preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools import prepare_lib055_electronic_witness_acceptance as handoff
from ocd_kernel.library._common import PipelineError


@pytest.fixture(scope="module")
def rows() -> dict[str, dict]:
    packet = json.loads((handoff.ROOT / handoff.PREFLIGHT).read_text(encoding="utf-8"))
    return {row["work_id"]: row for row in packet["works"]}


def _candidate(row: dict) -> bytes:
    return (Path(row["candidate_package"]) / "content.tei.xml").read_bytes()


@pytest.mark.parametrize("work_id", sorted(handoff.SOURCE_URLS))
def test_exact_header_binding_preserves_reviewed_text(rows: dict[str, dict], work_id: str) -> None:
    row = rows[work_id]
    original = _candidate(row)
    source = dict(source_path=row["source_member"], source_sha256=row["source_member_sha256"],
                  source_bytes=row["source_member_bytes"], source_scope="Exact retained ThML[1] member")
    derived = handoff._bind_header(
        original, row=row, identity=handoff._identity(work_id), source=source,
        revision=dict(id=f"{work_id}-test-revision", date="2026-09-25", note="Test binding"),
    )
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert b"Agent-accepted exact CCEL electronic witness" in derived.split(b"</teiHeader>", 1)[0]
    assert handoff.OLD_AVAILABILITY[work_id] not in derived
    with pytest.raises(PipelineError, match="hash mismatch"):
        handoff._bind_header(
            original + b" ", row=row, identity=handoff._identity(work_id), source=source,
            revision=dict(id=f"{work_id}-test-revision", date="2026-09-25", note="Test binding"),
        )


def test_ryle_heading_role_and_order_are_bound_to_source(rows: dict[str, dict]) -> None:
    row = rows["ryle-expository-thoughts-matthew"]
    source = (handoff.ROOT / row["source_member"]).read_bytes()
    original = _candidate(row)
    result = handoff._assess_ryle_headings(source, original)
    assert result["source_headings"] == result["tei_heading_carriers"] == 132
    assert result["explicit_p_rend_roles"] == 101
    assert result["exact_heading_text_order"] is True
    assert b"source-heading-h2" in original
    with pytest.raises(PipelineError, match="role differs"):
        handoff._assess_ryle_headings(source, original.replace(b"source-heading-h2", b"source-heading-h3", 1))


@pytest.mark.parametrize("work_id", sorted(handoff.SOURCE_URLS))
def test_historical_receipt_rejects_wrong_candidate(rows: dict[str, dict], work_id: str) -> None:
    row = rows[work_id]
    receipt = json.loads((handoff.ROOT / row["review_receipt"]).read_text(encoding="utf-8"))
    assert handoff._historical_proof(receipt, row)
    altered = dict(row, candidate_manifest_sha256="0" * 64)
    with pytest.raises(PipelineError, match="does not bind"):
        handoff._historical_proof(receipt, altered)


def test_categories_follow_document_structure() -> None:
    assert handoff.CATEGORY == {
        "flavel-fountain-of-life": "sermons",
        "flavel-method-of-grace": "sermons",
        "ryle-expository-thoughts-matthew": "commentary",
    }


def test_ryle_identity_uses_stable_short_internal_ids() -> None:
    assert handoff._identity("ryle-expository-thoughts-matthew") == {
        "work_id": "ryle-expository-thoughts-matthew",
        "textual_form_id": "ryle-matthew-retained-english",
        "edition_id": "ccel-matthew-electronic-witness",
        "acquisition_id": "ccel-matthew-retained",
    }
