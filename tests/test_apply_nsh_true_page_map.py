"""Tests for build/tools/apply_nsh_true_page_map.build_copy_plan.

The plan is the deterministic, high-blast-radius core of the vol_11 rebuild:
it maps each source leaf (jpg + its co-indexed primary-scan sidecars) to its
true-printed-page name, renames plate leaves to a position-tied label, and
excludes quarantined leaves -- raising on any target-name collision.
"""
import importlib.util
from pathlib import Path

import pytest

_MOD_PATH = Path(__file__).resolve().parents[1] / "build" / "tools" / "apply_nsh_true_page_map.py"
_spec = importlib.util.spec_from_file_location("apply_nsh_true_page_map", _MOD_PATH)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_numbered_page_renames_jpg_and_coindexed_sidecars():
    plan, quarantined = mod.build_copy_plan(
        page_map={300: 296},
        plate_map={},
        quarantine=set(),
        present_suffixes_by_fn={300: [".jpg", ".ia-abbyy.json", ".ia-abbyy.raw.xml"]},
    )
    assert quarantined == []
    assert set(plan) == {
        ("page_0300.jpg", "page_0296.jpg"),
        ("page_0300.ia-abbyy.json", "page_0296.ia-abbyy.json"),
        ("page_0300.ia-abbyy.raw.xml", "page_0296.ia-abbyy.raw.xml"),
    }


def test_plate_leaf_renamed_to_position_label():
    plan, _ = mod.build_copy_plan(
        page_map={},
        plate_map={262: "0260_plate01"},
        quarantine=set(),
        present_suffixes_by_fn={262: [".jpg", ".ia-abbyy.json"]},
    )
    assert set(plan) == {
        ("page_0262.jpg", "page_0260_plate01.jpg"),
        ("page_0262.ia-abbyy.json", "page_0260_plate01.ia-abbyy.json"),
    }


def test_quarantined_leaf_excluded_and_reported():
    plan, quarantined = mod.build_copy_plan(
        page_map={300: 296},
        plate_map={},
        quarantine={261},
        present_suffixes_by_fn={300: [".jpg"], 261: [".jpg", ".ia-abbyy.json"]},
    )
    assert quarantined == [261]
    assert all(not src.startswith("page_0261") for src, _ in plan)


def test_collision_on_two_leaves_to_same_true_page_raises():
    with pytest.raises(ValueError, match="collision"):
        mod.build_copy_plan(
            page_map={300: 296, 301: 296},  # both -> 296: must fail
            plate_map={},
            quarantine=set(),
            present_suffixes_by_fn={300: [".jpg"], 301: [".jpg"]},
        )


def test_execute_copy_plan_copies_renamed_and_leaves_source_intact(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "page_0300.jpg").write_text("jpgdata", encoding="utf-8")
    (src / "page_0300.ia-abbyy.json").write_text("abbyydata", encoding="utf-8")
    dst = tmp_path / "fresh"
    plan = [("page_0300.jpg", "page_0296.jpg"),
            ("page_0300.ia-abbyy.json", "page_0296.ia-abbyy.json")]
    copied, missing = mod.execute_copy_plan(plan, src, dst)
    assert copied == 2 and missing == []
    assert (dst / "page_0296.jpg").read_text(encoding="utf-8") == "jpgdata"
    assert (dst / "page_0296.ia-abbyy.json").read_text(encoding="utf-8") == "abbyydata"
    # non-destructive: source untouched
    assert (src / "page_0300.jpg").exists()


def test_execute_copy_plan_reports_missing_source(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    dst = tmp_path / "fresh"
    copied, missing = mod.execute_copy_plan([("page_0500.jpg", "page_0494.jpg")], src, dst)
    assert copied == 0 and missing == ["page_0500.jpg"]


def test_alternate_scan_suffixes_are_not_in_present_list_so_untouched():
    # dli/haucgoog are different scans; the caller only passes co-indexed
    # suffixes, so a leaf with only an alternate sidecar yields no jpg op.
    plan, _ = mod.build_copy_plan(
        page_map={300: 296},
        plate_map={},
        quarantine=set(),
        present_suffixes_by_fn={300: [".jpg", ".azure.json"]},
    )
    assert ("page_0300.azure.json", "page_0296.azure.json") in plan
    # nothing references the leaf-indexed alternate families
    assert not any("haucgoog" in dst or "dli" in dst for _, dst in plan)
