"""test_ocr_report.py -- unit tests for the OCR report writer.

Run: py -3 -m pytest tests/test_ocr_report.py -v
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_scanner import report  # noqa: E402
from build.tools.ocr_scanner.models import Candidate, ScanResult  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "ocr_scanner" / "expected_report.json"


def _fixture_scan_result() -> ScanResult:
    """Build the ScanResult that matches expected_report.json."""
    c1 = Candidate(
        id="cand-0001", tier=1, reason="digit_in_letter",
        source_id="test-fixture", entry_id="test-fixture.theotokos",
        field_path="term", value="THE0T0K0S", suggestion="THEOTOKOS",
        suggestion_source="digit_substitution_table", confidence=0.95,
        context_before="prior entry", context_after="Greek theological term",
        occurrences=1,
    )
    c2 = Candidate(
        id="cand-0002", tier=2, reason="apparent_space_insertion",
        source_id="test-fixture", entry_id="test-fixture.theatines",
        field_path="definition_blocks[0]", value="THE ATINES",
        suggestion="THEATINES", suggestion_source="dictionary", confidence=0.7,
        context_before="a Catholic order called", context_after="was founded in Rome",
        occurrences=1,
    )
    return ScanResult(
        source_id="test-fixture",
        scanned_at="2026-04-15T10:00:00+11:00",
        entries_scanned=5,
        pattern_set="ia_djvu",
        pattern_set_version="1",
        candidates=[c1, c2],
    )


# ---------------------------------------------------------------------------
# Test 1: write_report produces both files
# ---------------------------------------------------------------------------

def test_write_report_produces_two_files():
    """write_report() creates a .json and a .md file in the output directory."""
    result = _fixture_scan_result()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        json_path, md_path = report.write_report(result, tmp_path, date_str="2026-04-15")
        assert json_path.exists(), f"JSON report not created at {json_path}"
        assert md_path.exists(), f"Markdown report not created at {md_path}"
        assert json_path.suffix == ".json"
        assert md_path.suffix == ".md"


# ---------------------------------------------------------------------------
# Test 2: Golden-file test -- JSON output matches expected_report.json exactly
# ---------------------------------------------------------------------------

def test_write_report_json_matches_golden():
    """JSON output exactly matches the checked-in golden fixture."""
    result = _fixture_scan_result()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        json_path, _ = report.write_report(result, tmp_path, date_str="2026-04-15")
        produced = json.loads(json_path.read_text(encoding="utf-8"))
        expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        assert produced == expected, (
            f"JSON output does not match golden fixture.\n"
            f"Produced: {json.dumps(produced, indent=2)}\n"
            f"Expected: {json.dumps(expected, indent=2)}"
        )


# ---------------------------------------------------------------------------
# Test 3: Markdown ordering -- Tier 1 before Tier 2, grouped by reason
# ---------------------------------------------------------------------------

def test_write_report_markdown_tier_ordering():
    """Markdown groups candidates Tier 1 -> Tier 2, Tier 1 appears before Tier 2."""
    result = _fixture_scan_result()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _, md_path = report.write_report(result, tmp_path, date_str="2026-04-15")
        md = md_path.read_text(encoding="utf-8")
        tier1_pos = md.find("Tier 1")
        tier2_pos = md.find("Tier 2")
        assert tier1_pos != -1, "Markdown missing 'Tier 1' heading"
        assert tier2_pos != -1, "Markdown missing 'Tier 2' heading"
        assert tier1_pos < tier2_pos, "Tier 1 section must appear before Tier 2"
        # Candidate IDs must both appear
        assert "cand-0001" in md
        assert "cand-0002" in md
