"""Exact source-member accounting for the ten independent lib031 witnesses."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build.tools.library_ccel_cohort_binding import bind_ccel_cohort_member
from ocd_kernel.library._common import PipelineError, sha256_file


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "sources/structured-text/bounds-essentials-of-prayer"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs(work_id: str):
    manifest = _load(BASE / "lib031.source-manifest.json")
    source = next(item for item in manifest["authorities"]
                  if item.get("name") == f"{work_id}-source")
    work = _load(ROOT / "library/works" / work_id / "work.json")
    config = _load(ROOT / "sources/structured-text" / work_id / "config.json")
    source_set_path = BASE / "lib031-retained-source-set.json"
    row = {"cohort_source_set": {"path": source_set_path.relative_to(ROOT).as_posix(),
                                 "sha256": sha256_file(source_set_path)}}
    return manifest, source, work, config, row


def test_every_cohort_member_binds_to_its_own_retained_xml():
    members = _load(BASE / "lib031-retained-source-set.json")["members"]
    assert len(members) == 10
    for member in members:
        manifest, source, work, config, row = _inputs(member["work_id"])
        evidence = bind_ccel_cohort_member(ROOT, row, work, config, manifest, source)
        assert evidence == [
            "sources/structured-text/bounds-essentials-of-prayer/lib031-retained-source-set.json",
            "sources/structured-text/bounds-essentials-of-prayer/lib031.reconstruction-profile.json",
        ]


def test_swapped_member_is_rejected():
    manifest, _, work, config, row = _inputs("bounds-essentials-of-prayer")
    other = next(item for item in manifest["authorities"]
                 if item.get("name") == "bounds-necessity-of-prayer-source")
    with pytest.raises(PipelineError, match="proposed source differs"):
        bind_ccel_cohort_member(ROOT, row, work, config, manifest, other)


def test_missing_sibling_primary_is_rejected():
    manifest, source, work, config, row = _inputs("bounds-essentials-of-prayer")
    altered = copy.deepcopy(manifest)
    altered["authorities"] = [item for item in altered["authorities"]
                              if item.get("name") != "pascal-pensees-source"]
    with pytest.raises(PipelineError, match="primary source set is incomplete"):
        bind_ccel_cohort_member(ROOT, row, work, config, altered, source)


def test_work_title_mismatch_is_rejected():
    manifest, source, work, config, row = _inputs("bounds-essentials-of-prayer")
    wrong = dict(work, title="Other work")
    with pytest.raises(PipelineError, match="config, work, profile"):
        bind_ccel_cohort_member(ROOT, row, wrong, config, manifest, source)
