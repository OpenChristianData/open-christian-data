"""test_apply_corrections.py -- unit tests for the approved-corrections applicator.

Run: py -3 -m pytest tests/test_apply_corrections.py -v
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_scanner import apply_approved_corrections as aac  # noqa: E402


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SCAN_REPORT = {
    "source_id": "test-source",
    "candidates": [
        {
            "id": "cand-0001", "reason": "digit_in_letter", "tier": 1,
            "value": "THE0T0K08", "suggestion": "THEOTOKOS",
            "suggestion_source": "digit_substitution_table",
            "entry_id": "test.theotokos", "field_path": "term",
        },
        {
            "id": "cand-0002", "reason": "apparent_space_insertion", "tier": 2,
            "value": "THE ATINES", "suggestion": "THEATINES",
            "suggestion_source": "dictionary",
            "entry_id": "test.theatines", "field_path": "definition_blocks[0]",
        },
        {
            "id": "cand-0003", "reason": "digit_in_letter", "tier": 1,
            "value": "H2O", "suggestion": "HOO",
            "suggestion_source": "digit_substitution_table",
            "entry_id": "test.chemistry", "field_path": "definition_blocks[0]",
        },
    ],
}

APPROVED_FILE = {
    "scan_report": "test-source_2026-04-15.json",
    "reviewed_by": "reviewer",
    "reviewed_at": "2026-04-15T22:45:00+11:00",
    "approved": ["cand-0001", "cand-0002"],
    "rejected": ["cand-0003"],
    "deferred": [],
    "notes": {"cand-0003": "H2O is chemistry notation, add to whitelist_patterns"},
}


def _write_fixtures(tmp: Path) -> tuple[Path, Path]:
    """Write mock scan report and approved.json to tmp dir, return their paths."""
    scan_path = tmp / "test-source_2026-04-15.json"
    approved_path = tmp / "test-source_2026-04-15_approved.json"
    scan_path.write_text(json.dumps(SCAN_REPORT, indent=2), encoding="utf-8")
    approved_path.write_text(json.dumps(APPROVED_FILE, indent=2), encoding="utf-8")
    return scan_path, approved_path


# ---------------------------------------------------------------------------
# Test 1: 2 approved -> 2 new entries in corrections file
# ---------------------------------------------------------------------------

def test_apply_writes_two_corrections():
    """Two approved candidates produce two correction entries, idempotent on re-run."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        scan_path, approved_path = _write_fixtures(tmp_path)
        corrections_dir = tmp_path / "corrections"

        # First run
        aac.apply(scan_path, approved_path, corrections_dir, dry_run=False)
        corrections_file = corrections_dir / "test-source.json"
        assert corrections_file.exists()
        data = json.loads(corrections_file.read_text(encoding="utf-8"))
        assert len(data["corrections"]) == 2

        # Second run (idempotent -- same candidates not added again)
        aac.apply(scan_path, approved_path, corrections_dir, dry_run=False)
        data2 = json.loads(corrections_file.read_text(encoding="utf-8"))
        assert len(data2["corrections"]) == 2, "Re-run must not duplicate corrections"


# ---------------------------------------------------------------------------
# Test 2: Whitelist note in rejected candidate is surfaced
# ---------------------------------------------------------------------------

def test_apply_surfaces_whitelist_notes(capsys):
    """Rejected candidates with whitelist notes are printed (but not auto-applied)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        scan_path, approved_path = _write_fixtures(tmp_path)
        corrections_dir = tmp_path / "corrections"

        aac.apply(scan_path, approved_path, corrections_dir, dry_run=False)
        captured = capsys.readouterr()
        assert "H2O" in captured.out or "whitelist" in captured.out.lower()


# ---------------------------------------------------------------------------
# Test 3: Missing candidate ID -> error, writes nothing
# ---------------------------------------------------------------------------

def test_apply_missing_cand_id_raises():
    """approved.json referencing a non-existent cand_id raises ValueError."""
    bad_approved = {
        **APPROVED_FILE,
        "approved": ["cand-9999"],  # does not exist in scan report
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        scan_path = tmp_path / "test-source_2026-04-15.json"
        approved_path = tmp_path / "test-source_2026-04-15_approved.json"
        scan_path.write_text(json.dumps(SCAN_REPORT), encoding="utf-8")
        approved_path.write_text(json.dumps(bad_approved), encoding="utf-8")
        corrections_dir = tmp_path / "corrections"

        try:
            aac.apply(scan_path, approved_path, corrections_dir, dry_run=False)
            assert False, "Expected ValueError for unknown candidate ID"
        except ValueError as e:
            assert "cand-9999" in str(e)
        # Corrections file must not have been created
        assert not (corrections_dir / "test-source.json").exists()


# ---------------------------------------------------------------------------
# Test 4: Collision with existing entry -> refuses to overwrite
# ---------------------------------------------------------------------------

def test_apply_refuses_to_overwrite_existing():
    """Conflicting fix for the same bad value (different good) raises ValueError.

    A same-bad-same-good entry from a different candidate is idempotent and is
    silently skipped (that path is tested implicitly by test_apply_writes_two_corrections
    on re-run). This test covers the true-collision case: an existing correction
    maps THE0T0K08 -> THEOTOKE while the new approval maps it -> THEOTOKOS.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        corrections_dir = tmp_path / "corrections"
        corrections_dir.mkdir()
        existing = {
            "source_id": "test-source",
            "corrections": [
                {
                    "bad": "THE0T0K08",
                    # Conflicting fix: different good value from what the scan report suggests.
                    # Simulates a previous manual correction that disagrees with the new approval.
                    "good": "THEOTOKE",
                    "reason": "digit_in_letter",
                    "approved_by": "reviewer",
                    "approved_at": "2026-04-14T10:00:00+11:00",
                    "candidate_id": "cand-prev-001",
                }
            ],
        }
        corr_file = corrections_dir / "test-source.json"
        corr_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        scan_path, approved_path = _write_fixtures(tmp_path)
        try:
            aac.apply(scan_path, approved_path, corrections_dir, dry_run=False)
            assert False, "Expected ValueError for collision"
        except ValueError as e:
            assert "THE0T0K08" in str(e) or "collision" in str(e).lower() or "already" in str(e).lower()
