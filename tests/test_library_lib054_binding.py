"""LIB-054 edition accounting binds ten exact retained CCEL XML witnesses."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from build.tools.library_lib054_binding import bind_lib054_member
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "sources/structured-text/lib054-ccel-puritan"
FRAGMENTS = {"edwards-distinguishing-marks", "edwards-history-of-redemption"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs(work_id: str):
    manifest = _load(BASE / "lib054.source-manifest.json")
    member = next(item for item in _load(BASE / "lib054.reconstruction-profile.json")["works"]
                  if item["work_id"] == work_id)
    source = next(item for item in manifest["authorities"]
                  if item.get("name") == member["authority_name"])
    profile = next(item for item in manifest["authorities"]
                   if item.get("role") == "complete-source-feature-profile")
    work = _load(ROOT / "library/works" / work_id / "work.json")
    config = _load(BASE / "work-bindings" / work_id / "config.json")
    row = {
        "cohort_source_set": {"path": profile["path"], "sha256": profile["sha256"]},
        "url": member["source_url"],
        "language": "en",
        "source_scope": f"Exact retained {'fragment' if work_id in FRAGMENTS else 'XML'} {source['path']}",
        "warnings": ["Parent-volume extraction provenance unverified", "Source rights clearance open"],
    }
    return manifest, member, source, work, config, row


def test_ten_distinct_xml_witnesses_bind_to_ten_work_identities():
    members = _load(BASE / "lib054.reconstruction-profile.json")["works"]
    assert len(members) == 10
    assert len({item["source_path"] for item in members}) == 10
    for member in members:
        manifest, _, source, work, config, row = _inputs(member["work_id"])
        assert bind_lib054_member(ROOT, row, work, config, manifest, source) == [
            "sources/structured-text/lib054-ccel-puritan/lib054.reconstruction-profile.json"
        ]


def test_swapped_xml_is_rejected():
    manifest, _, _, work, config, row = _inputs("baxter-call-to-unconverted")
    other = next(item for item in manifest["authorities"]
                 if item.get("name") == "source-baxter-pastor")
    with pytest.raises(PipelineError, match="source differs"):
        bind_lib054_member(ROOT, row, work, config, manifest, other)


def test_missing_sibling_source_is_rejected():
    manifest, _, source, work, config, row = _inputs("baxter-call-to-unconverted")
    altered = copy.deepcopy(manifest)
    altered["authorities"] = [item for item in altered["authorities"]
                              if item.get("name") != "source-bunyan-holy-war"]
    with pytest.raises(PipelineError, match="source/config census"):
        bind_lib054_member(ROOT, row, work, config, altered, source)


def test_fragment_cannot_lose_its_parent_provenance_warning():
    manifest, _, source, work, config, row = _inputs("edwards-history-of-redemption")
    row["warnings"] = ["Source rights clearance open"]
    with pytest.raises(PipelineError, match="fragment provenance warning"):
        bind_lib054_member(ROOT, row, work, config, manifest, source)


def test_work_title_mismatch_is_rejected():
    manifest, _, source, work, config, row = _inputs("bunyan-holy-war")
    with pytest.raises(PipelineError, match="work, URL, language, or source"):
        bind_lib054_member(ROOT, row, dict(work, title="Other work"), config, manifest, source)
