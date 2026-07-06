"""Tests for the Phase F.5 correction-proposal CLI.

Covers propose -> approve / reject / list paths against both pilots, plus the
core invariant: propose_correction.py never mutates anything under data/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from build.tools import propose_correction as pc

REPO_ROOT = Path(__file__).resolve().parents[1]
CLARKE_RECORD = "data/commentaries/adam-clarke/2-john.json"
SH_RECORD = "data/reference/schaff-herzog-encyclopedia.json"


@pytest.fixture(autouse=True)
def _isolate_ledger(tmp_path, monkeypatch):
    """Redirect REPO_ROOT in propose_correction so each test gets a clean ledger root."""
    monkeypatch.setattr(pc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pc, "LEDGER_SCHEMA_PATH", REPO_ROOT / "schemas" / "v1" / "correction_ledger.schema.json")
    return tmp_path


def _propose_clarke():
    return pc.propose(
        resource_record_path=Path(CLARKE_RECORD),
        entry_id="adam-clarke.2John.1.1",
        field_path="commentary_text",
        before_text="shew",
        after_text="show",
        proposed_by="test-reviewer",
        producer_warning_signature="historical_lexicon.archaic_variant.shew",
    )


def _propose_sh():
    return pc.propose(
        resource_record_path=Path(SH_RECORD),
        entry_id="schaff-herzog.aachen-synods-of",
        field_path="definition_blocks.b8f3a1c2",
        before_text="TH0",
        after_text="THE",
        proposed_by="test-reviewer",
        producer_warning_signature="ocr_scanner.digit_in_letter.aachen",
    )


def test_propose_creates_ledger_entry_with_status_proposed(tmp_path):
    correction = _propose_clarke()
    assert correction["status"] == "proposed"
    # B-F3: resource_id mirrors meta.id, not the per-book filename stem.
    assert correction["resource_id"] == "adam-clarke"
    ledger = tmp_path / "review" / "corrections" / "commentaries" / "adam-clarke" / "2-john.jsonl"
    assert ledger.exists()


def test_refuse_data_mutation_blocks_absolute_paths_under_data(tmp_path):
    """A-F5: the DataMutationRefused guard must catch absolute paths and
    ./data variants, not just relative paths whose first segment is exactly
    "data"."""
    abs_data = (pc.REPO_ROOT / "data" / "commentaries" / "fake.json").as_posix()
    with pytest.raises(pc.DataMutationRefused):
        pc._refuse_data_mutation(abs_data)
    with pytest.raises(pc.DataMutationRefused):
        pc._refuse_data_mutation("./data/foo.json")
    # Non-data paths are still permitted.
    pc._refuse_data_mutation("review/corrections/foo.jsonl")
    pc._refuse_data_mutation("/tmp/scratch.json")


def test_propose_resource_id_falls_back_to_stem_when_record_missing(tmp_path):
    """If the record JSON cannot be read, resource_id falls back to the stem."""
    fake_record = Path("data/commentaries/fictional/never-exists.json")
    correction = pc.propose(
        resource_record_path=fake_record,
        entry_id="x.1",
        field_path="commentary_text",
        before_text="a",
        after_text="b",
        proposed_by="test-reviewer",
    )
    assert correction["resource_id"] == "never-exists"


def test_approve_moves_proposed_to_approved(tmp_path):
    correction = _propose_clarke()
    cid = correction["correction_id"]
    approved = pc.approve(
        resource_record_path=Path(CLARKE_RECORD),
        correction_id=cid,
        approved_by="test-reviewer",
    )
    assert approved["status"] == "approved"
    assert approved["approved_at"]
    assert approved["approved_by"] == "test-reviewer"


def test_reject_moves_proposed_to_rejected(tmp_path):
    correction = _propose_clarke()
    rejected = pc.reject(
        resource_record_path=Path(CLARKE_RECORD),
        correction_id=correction["correction_id"],
        rejected_reason="archaic preserved on purpose",
    )
    assert rejected["status"] == "rejected"
    assert rejected["rejected_reason"] == "archaic preserved on purpose"


def test_cannot_approve_already_rejected(tmp_path):
    correction = _propose_clarke()
    pc.reject(
        resource_record_path=Path(CLARKE_RECORD),
        correction_id=correction["correction_id"],
        rejected_reason="x",
    )
    with pytest.raises(ValueError, match="cannot approve"):
        pc.approve(
            resource_record_path=Path(CLARKE_RECORD),
            correction_id=correction["correction_id"],
            approved_by="reviewer",
        )


def test_list_filters_by_status(tmp_path):
    a = _propose_clarke()
    b = _propose_clarke()
    pc.approve(
        resource_record_path=Path(CLARKE_RECORD),
        correction_id=a["correction_id"],
        approved_by="reviewer",
    )
    approved = pc.list_corrections(resource_record_path=Path(CLARKE_RECORD), status="approved")
    proposed = pc.list_corrections(resource_record_path=Path(CLARKE_RECORD), status="proposed")
    assert len(approved) == 1 and approved[0]["correction_id"] == a["correction_id"]
    assert len(proposed) == 1 and proposed[0]["correction_id"] == b["correction_id"]


def test_propose_correction_refuses_to_write_under_data(tmp_path):
    with pytest.raises(pc.DataMutationRefused):
        pc._refuse_data_mutation(Path("data/something/whatever.json"))


def test_data_file_is_not_mutated_at_any_step(tmp_path):
    # Snapshot the real Clarke record before/after the full propose -> approve cycle.
    real_record = REPO_ROOT / CLARKE_RECORD
    if not real_record.exists():
        pytest.skip("Clarke pilot record absent on this checkout")
    before = real_record.read_bytes()
    correction = _propose_clarke()
    pc.approve(
        resource_record_path=Path(CLARKE_RECORD),
        correction_id=correction["correction_id"],
        approved_by="reviewer",
    )
    after = real_record.read_bytes()
    assert before == after


def test_two_pilots_can_carry_approved_corrections_in_parallel(tmp_path):
    clarke = _propose_clarke()
    sh = _propose_sh()
    pc.approve(
        resource_record_path=Path(CLARKE_RECORD),
        correction_id=clarke["correction_id"],
        approved_by="reviewer",
    )
    pc.approve(
        resource_record_path=Path(SH_RECORD),
        correction_id=sh["correction_id"],
        approved_by="reviewer",
    )
    clarke_approved = pc.list_corrections(resource_record_path=Path(CLARKE_RECORD), status="approved")
    sh_approved = pc.list_corrections(resource_record_path=Path(SH_RECORD), status="approved")
    assert len(clarke_approved) == 1
    assert len(sh_approved) == 1
