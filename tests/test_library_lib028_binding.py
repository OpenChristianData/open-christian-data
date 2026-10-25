"""LIB-028 five-work accounting is tied to exact retained CCEL XML roots."""
from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from build.tools.library_lib028_binding import bind_lib028_member
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/eusebius-lib028-five-sidecar-packet-20260926.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs(work_id: str):
    row = next(item for item in _load(PACKET)["entries"] if item["work_id"] == work_id)
    work = _load(ROOT / row["work"]["path"])
    config = _load(ROOT / row["config"]["path"])
    manifest = _load(ROOT / row["source_manifest"]["path"])
    return row, work, config, manifest


@pytest.fixture(scope="module")
def historical_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("lib028-original-catalogs")
    (root / ".ocd-storage.json").write_bytes((ROOT / ".ocd-storage.json").read_bytes())
    for row in _load(PACKET)["entries"]:
        _, _, _, manifest = _inputs(row["work_id"])
        for ref in [row["metadata_evidence"], *manifest["authorities"]]:
            relative = Path(ref["path"])
            assert not relative.is_absolute() and ".." not in relative.parts
            if relative.parts[0] == "raw":
                continue
            source = ROOT / relative
            if relative.as_posix().startswith("metadata/source-evidence/catalog/"):
                source = ROOT / "tests/fixtures/reconstruction-runtime/authorities" / f"lib028-{relative.stem}-original-catalog.json"
            raw = source.read_bytes()
            assert sha256(raw).hexdigest() == ref["sha256"], relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return root


def test_all_five_works_bind_distinct_retained_xml_roots(historical_root):
    rows = _load(PACKET)["entries"]
    assert len(rows) == 5
    assert len({row["containing_source"]["locator"] for row in rows}) == 5
    for row in rows:
        current, work, config, manifest = _inputs(row["work_id"])
        evidence = bind_lib028_member(historical_root, current, work, config, manifest, current["primary_source"])
        assert evidence[2].endswith("lib028.work-binding.json")
        assert evidence[3] == f"metadata/source-evidence/catalog/{row['work_id']}.json"


def test_other_volume_source_is_rejected(historical_root):
    row, work, config, manifest = _inputs("eusebius-ecclesiastical-history")
    other = next(item for item in manifest["authorities"]
                 if item.get("name") == "retained-npnf202")
    with pytest.raises(PipelineError, match="work/config/source binding differs"):
        bind_lib028_member(historical_root, row, work, config, manifest, other)


def test_wrong_child_locator_is_rejected(historical_root):
    row, work, config, manifest = _inputs("theodoret-ecclesiastical-history")
    wrong = copy.deepcopy(row)
    wrong["containing_source"]["locator"] = "raw/ccel/schaff/npnf203.xml#iii"
    with pytest.raises(PipelineError, match="containing-source identity differs"):
        bind_lib028_member(historical_root, wrong, work, config, manifest, wrong["primary_source"])


def test_missing_manifest_work_binding_is_rejected(historical_root):
    row, work, config, manifest = _inputs("socrates-ecclesiastical-history")
    altered = copy.deepcopy(manifest)
    altered["authorities"] = [item for item in altered["authorities"]
                              if item.get("name") != "sozomen-binding"]
    with pytest.raises(PipelineError, match="five-work binding/config census differs"):
        bind_lib028_member(historical_root, row, work, config, altered, row["primary_source"])


def test_missing_rights_and_print_limits_is_rejected(historical_root):
    row, work, config, manifest = _inputs("eusebius-life-of-constantine")
    wrong = copy.deepcopy(row)
    wrong["warnings"] = []
    with pytest.raises(PipelineError, match="edition/rights limitations absent"):
        bind_lib028_member(historical_root, wrong, work, config, manifest, wrong["primary_source"])


def test_current_metadata_rejects_historical_packet():
    row, work, config, manifest = _inputs("eusebius-ecclesiastical-history")
    with pytest.raises(PipelineError, match="metadata hash differs"):
        bind_lib028_member(ROOT, row, work, config, manifest, row["primary_source"])
