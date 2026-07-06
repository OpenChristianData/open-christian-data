"""Fail-closed tuning embargo gate for Schaff-Herzog OCR pipeline tuning."""

from __future__ import annotations

import sys
from pathlib import Path

from build.lib.first_diagnostics_contract import (
    REPORTS_FIRST_SUBPATH,
    first_diagnostics_report_present,
)

TUNING_OPERATIONS: frozenset[str] = frozenset(
    {
        "alignment_strategy",
        "matrix_policy",
        "reviewer_sampling",
        "scorer_thresholds",
    }
)


class TuningEmbargoError(RuntimeError):
    """Raised when tuning is blocked until first diagnostics are available."""


def check_tuning_allowed(operation: str, *, reports_root: Path, read_only: bool = False) -> None:
    if read_only:
        return
    if operation not in TUNING_OPERATIONS:
        raise ValueError(f"unknown tuning operation: {operation}")
    if first_diagnostics_report_present(reports_root):
        return

    report_dir = REPORTS_FIRST_SUBPATH.as_posix()
    raise TuningEmbargoError(
        f"tuning operation {operation} is blocked until first diagnostics reports exist "
        f"and validate under {report_dir}"
    )


def enforce_or_exit(operation: str, *, reports_root: Path, read_only: bool = False) -> None:
    try:
        check_tuning_allowed(operation, reports_root=reports_root, read_only=read_only)
    except TuningEmbargoError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
