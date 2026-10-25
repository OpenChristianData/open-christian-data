"""Bounded source and candidate checks for seven LIB-050 Owen children."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tools import prepare_owen_lib050_child_candidates as owen
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.validate import validate_file


STAGE = owen.LIBRARY / "candidate-reviews/lib050-seven-work-local-20260926-v1"


def test_seven_source_bound_children_match_frozen_stage() -> None:
    stage = json.loads((STAGE / "stage-receipt.json").read_bytes())
    profile = json.loads((owen.ROOT / owen.PROFILE).read_bytes())
    rows = {row["work_id"]: row for row in profile["works"]}
    assert stage["status"] == "nonaccepted"
    assert stage["acceptance"] == "not-staged"
    assert tuple(stage["work_ids"]) == owen.CHILDREN
    for work_id in owen.CHILDREN:
        source, divisions = owen._source_boundary(rows[work_id])
        candidate = STAGE / work_id / "candidate.tei.xml"
        receipt_path = STAGE / work_id / "receipt.json"
        receipt = json.loads(receipt_path.read_bytes())
        assert not validate_file(candidate)
        assert receipt["source_sha256"] == hashlib.sha256(source).hexdigest()
        assert receipt["source_divisions"] == divisions
        assert receipt["tei_sha256"] == hashlib.sha256(candidate.read_bytes()).hexdigest()
        assert stage["work_tei_sha256"][work_id] == receipt["tei_sha256"]
        assert stage["work_receipt_sha256"][work_id] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()


def test_new_titled_constituent_blocks_work_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = owen.ROOT / "raw/ccel/owen/eshcol.xml"
    tree = etree.fromstring(source.read_bytes(), etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True,
    ))
    etree.SubElement(tree.find("ThML.body"), "div1", id="new", title="Another Owen Work")
    changed = etree.tostring(tree)
    target = tmp_path / "raw/ccel/owen/eshcol.xml"
    target.parent.mkdir(parents=True)
    target.write_bytes(changed)
    monkeypatch.setattr(owen, "ROOT", tmp_path)
    row = {"work_id": "john-owen-eshcol", "path": "raw/ccel/owen/eshcol.xml",
           "bytes": len(changed), "sha256": hashlib.sha256(changed).hexdigest()}
    with pytest.raises(PipelineError, match="another titled constituent"):
        owen._source_boundary(row)


def test_source_digest_change_blocks_candidate_derivation() -> None:
    with pytest.raises(PipelineError, match="source changed"):
        owen._source_boundary({"work_id": "john-owen-eshcol", "path": "raw/ccel/owen/eshcol.xml",
                               "bytes": 210148, "sha256": "0" * 64})
