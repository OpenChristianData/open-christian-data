from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _module(name: str):
    spec = importlib.util.find_spec(name)
    assert spec is not None, f"{name} is missing"
    return importlib.import_module(name)


def test_spotcheck_and_sampler_share_gold_strata_contract_by_identity() -> None:
    gold_strata = _module("build.lib.gold_strata")
    sampler = _module("build.tools.build_gold_sample")
    spotcheck = _module("build.tools.gold_representativeness_spotcheck")

    assert sampler.STRATA_CONTRACT is gold_strata.STRATA_CONTRACT
    assert spotcheck.STRATA_CONTRACT is gold_strata.STRATA_CONTRACT
    assert sampler.derive_page_strata is gold_strata.derive_page_strata
    assert spotcheck.derive_page_strata is gold_strata.derive_page_strata


def test_comparison_contract_has_tolerances_and_no_verdict() -> None:
    spotcheck = _module("build.tools.gold_representativeness_spotcheck")

    contract = spotcheck.build_comparison_contract(
        compared_volume=7,
        baseline_volume=1,
    )

    assert contract["compared_volume"] == 7
    assert contract["baseline_volume"] == 1
    assert set(contract["indicators"]) == {"oracle_gap", "segmentation_difference"}
    assert set(contract["tolerance_bands"]) == set(contract["indicators"])
    assert all(
        isinstance(value, (int, float))
        for value in contract["tolerance_bands"].values()
    )
    assert "verdict" not in contract
    assert "pass" not in contract
    assert "fail" not in contract


def test_comparison_contract_helper_classifies_inside_and_outside_tolerance() -> None:
    gold_strata = _module("build.lib.gold_strata")

    result = gold_strata.classify_comparison_tolerances(
        baseline={"oracle_gap": 0.05, "segmentation_difference": 0.10},
        compared={"oracle_gap": 0.07, "segmentation_difference": 0.30},
        tolerance_bands={"oracle_gap": 0.03, "segmentation_difference": 0.05},
    )

    assert result == {
        "oracle_gap": "within_tolerance",
        "segmentation_difference": "outside_tolerance",
    }
