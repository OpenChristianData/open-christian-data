"""Exact-receipt, read-only guard for the staged Bounds Power handoff."""

from pathlib import Path

import pytest

from build.tools.preflight_lib031_bounds_power_acceptance import preflight
from tests.lib031_historical_fixture import historical_bounds_power
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.library._common import PipelineError

STAGE = Path(r"D:\Library\Open Christian Data\bpow3")
RECEIPT_SHA256 = "ff395f392b73b882b75893a0dda63d16346295e959ec80b67803d87f7e8886ce"


def test_exact_staged_generation_passes_without_installing(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    work = Path("library/works/bounds-power-through-prayer")
    before = _files(root / work)
    historical = historical_bounds_power(root, tmp_path / "historical", STAGE)
    result = preflight(STAGE, RECEIPT_SHA256, root_override=historical)
    assert _files(root / work) == before
    assert result["status"] == "pass-read-only"
    assert result["canonical_action"] == "none"
    assert result["current_work_files"] == 3
    assert result["staged_work_files"] == 31
    assert result["projection_independent_verifier_errors"] == []


def test_stale_receipt_pin_is_rejected() -> None:
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64)


def test_current_accepted_generation_is_not_the_acquired_before() -> None:
    with pytest.raises(PipelineError, match="not the declared three-file acquired baseline"):
        preflight(STAGE, RECEIPT_SHA256)
