"""WU-09 proof for an ordinary primary-source-supported metadata correction."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from build.lib import source_metadata as sm
from tests.test_source_metadata import _fixture


def test_primary_source_title_correction_uses_supported_writer_route(tmp_path: Path) -> None:
    worklist, decision, worklist_path, decisions_path = _fixture(tmp_path)
    corrected = "Corrected title from the primary source"

    evidence = json.loads((tmp_path / "evidence.json").read_text(encoding="utf-8"))
    evidence["title"] = corrected
    (tmp_path / "evidence.json").write_bytes(sm.canonical_bytes(evidence))

    evidence_bytes = (tmp_path / "evidence.json").read_bytes()
    evidence_sha = sm.sha256_bytes(evidence_bytes)
    for dimension in worklist["subjects"][0]["dimensions"].values():
        for work_item in dimension["items"]:
            work_item["input_value"] = corrected
            work_item["input_sha256"] = evidence_sha
    claim = decision["decisions"][0]["dimensions"]["work"]["fields"][0]
    claim["evidence"]["value"] = corrected
    claim["evidence"]["bindings"][0]["sha256"] = evidence_sha
    claim["evidence"]["bindings"][0]["bytes"] = len(evidence_bytes)
    claim["evidence"]["bindings"][0]["locator"]["expected"] = corrected
    claim["adoption"]["destination"] = "source_evidence_only"
    decisions = copy.deepcopy(decision)
    worklist_path.write_bytes(sm.canonical_bytes(worklist))
    decisions_path.write_bytes(sm.canonical_bytes(decisions))

    before_target = (tmp_path / "target.json").read_bytes()
    result = sm.write_outputs(
        tmp_path, worklist_path=worklist_path, decisions_path=decisions_path
    )
    sidecar = sm.lookup_sidecar(tmp_path, "catalog", "synthetic-work")

    assert result["written"] == [
        "metadata/source-evidence/catalog/synthetic-work.json",
        "metadata/source-evidence/index.json",
    ]
    assert sidecar["dimensions"]["work"]["fields"][0]["evidence"]["value"] == corrected
    assert (tmp_path / "target.json").read_bytes() == before_target
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "library").exists()
