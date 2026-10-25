"""Focused proof for the noninstalling LIB-031 acceptance preparation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools.prepare_lib031_family_handoff import prepare
from tests.lib031_historical_fixture import historical_lib031_family


ROOT = Path(__file__).resolve().parents[1]
FAMILY = Path(r"D:\Library\Open Christian Data\candidate-reviews\37c-084-262-bounds-pascal-lib031-20260921-r1\package")


def test_current_family_has_exact_source_bindings_and_no_premature_acceptance(tmp_path: Path) -> None:
    historical = historical_lib031_family(ROOT, tmp_path / "historical")
    result = prepare(historical, FAMILY)
    assert result["counts"] == {
        "works": 10,
        "source_bound": 10,
        "standard_work_local_candidates": 10,
        "parent_crosswalk_rows": 19465,
        "ready_for_agent_acceptance": 0,
        "blocked": 10,
    }
    assert [row["work_id"] for row in result["works"]] == [
        "bounds-essentials-of-prayer",
        "bounds-necessity-of-prayer",
        "bounds-power-through-prayer",
        "bounds-prayer-and-praying-men",
        "bounds-purpose-in-prayer",
        "bounds-reality-of-prayer",
        "bounds-weapon-of-prayer",
        "finney-lectures-on-revivals",
        "finney-systematic-theology",
        "pascal-pensees",
    ]
    assert [row["work_id"] for row in result["works"] if row["existing_standalone_pilot"]] == [
        "bounds-essentials-of-prayer",
        "bounds-necessity-of-prayer",
    ]
    assert sum(row["prior_parent_visual"] is not None for row in result["works"]) == 7
    assert all(row["standard_work_local_candidate"]["status"] == "validated-nonaccepted" for row in result["works"])
    assert all(row["acquisition_rights_warnings"] for row in result["works"])
    assert all(row["gaps"] for row in result["works"])


def test_rejects_stale_parent_validation_before_reporting_works(tmp_path: Path) -> None:
    package = tmp_path / "family" / "package"
    package.mkdir(parents=True)
    (package / "manifest.json").write_bytes((FAMILY / "manifest.json").read_bytes())
    validation = json.loads((FAMILY.parent / "validation.json").read_text(encoding="utf-8"))
    validation["candidate_sha256"] = "0" * 64
    (package.parent / "validation.json").write_text(json.dumps(validation), encoding="utf-8")
    with pytest.raises(ValueError, match="parent candidate validation"):
        prepare(ROOT, package)


def test_current_accepted_work_is_not_a_pending_family() -> None:
    with pytest.raises(ValueError, match="existing acceptance or master requires a different route"):
        prepare(ROOT, FAMILY)
