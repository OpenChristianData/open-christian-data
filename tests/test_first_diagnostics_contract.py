from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.first_diagnostics_contract import (  # noqa: E402
    first_diagnostics_report_present,
    validate_oracle_report,
    validate_segmentation_report,
    write_minimal_valid_reports,
)


def test_oracle_report_missing_gap_reports_problem() -> None:
    doc = {
        "candidate_oracle": 0.95,
        "alignment_oracle": 0.9,
        "by_zone": {
            "body": {
                "candidate_oracle": 0.95,
                "alignment_oracle": 0.9,
                "gap": 0.05,
            }
        },
        "by_script": {
            "latin": {
                "candidate_oracle": 0.95,
                "alignment_oracle": 0.9,
                "gap": 0.05,
            }
        },
    }

    problems = validate_oracle_report(doc)

    assert problems
    assert any("gap" in problem for problem in problems)


def test_valid_oracle_report_has_no_problems() -> None:
    doc = {
        "candidate_oracle": 0.95,
        "alignment_oracle": 0.9,
        "gap": 0.05,
        "by_zone": {
            "body": {
                "candidate_oracle": 0.95,
                "alignment_oracle": 0.9,
                "gap": 0.05,
            }
        },
        "by_script": {
            "latin": {
                "candidate_oracle": 0.95,
                "alignment_oracle": 0.9,
                "gap": 0.05,
            }
        },
    }

    assert validate_oracle_report(doc) == []


def test_segmentation_report_missing_engine_pair_map_reports_problem() -> None:
    doc = {
        "by_zone": {"body": {"tesseract__abbyy": 0.12}},
        "by_script": {"latin": {"tesseract__abbyy": 0.08}},
    }

    problems = validate_segmentation_report(doc)

    assert problems
    assert any("segmentation_difference_by_engine_pair" in problem for problem in problems)


def test_first_diagnostics_presence_reflects_minimal_valid_reports(tmp_path: Path) -> None:
    assert first_diagnostics_report_present(tmp_path) is False

    write_minimal_valid_reports(tmp_path)

    assert first_diagnostics_report_present(tmp_path) is True
