from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.first_diagnostics_contract import write_minimal_valid_reports  # noqa: E402
from build.lib.tuning_embargo import (  # noqa: E402
    TuningEmbargoError,
    check_tuning_allowed,
    enforce_or_exit,
)


def test_tuning_operation_with_missing_report_raises(tmp_path: Path) -> None:
    with pytest.raises(TuningEmbargoError):
        check_tuning_allowed("alignment_strategy", reports_root=tmp_path)


def test_enforce_or_exit_with_missing_report_exits_nonzero(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        enforce_or_exit("alignment_strategy", reports_root=tmp_path)

    assert exc_info.value.code != 0


def test_read_only_mode_allows_missing_report(tmp_path: Path) -> None:
    check_tuning_allowed("alignment_strategy", reports_root=tmp_path, read_only=True)


def test_valid_first_diagnostics_report_allows_tuning(tmp_path: Path) -> None:
    write_minimal_valid_reports(tmp_path)

    check_tuning_allowed("alignment_strategy", reports_root=tmp_path)


def test_unrecognized_operation_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        check_tuning_allowed("unknown_tuning", reports_root=tmp_path)
