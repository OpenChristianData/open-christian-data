"""The exact PG42957 row-size carrier stays private and reversible."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.public_allowlist import _scan


HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = HERE / "public_rows.py"
if CANDIDATE.is_file():
    spec = importlib.util.spec_from_file_location("ocd_kernel.release.pg42957_candidate", CANDIDATE)
    assert spec is not None and spec.loader is not None
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
else:
    from ocd_kernel.release import public_rows as boundary

ITEM = "modern-scepticism-christian-evidence-society-1871--modern-scepticism-christian-evidence-society-1871-gutenberg-electronic"
WORK = ROOT / "library/works/modern-scepticism-christian-evidence-society-1871"
EDITION = (WORK / "forms/modern-scepticism-christian-evidence-society-1871-gutenberg-retained-en"
           / "editions/modern-scepticism-christian-evidence-society-1871-gutenberg-electronic")
AUTHORITY = {"acceptance_sha256": "231677839f83d469a0515b8b610f4d4c9b2ddc7fa1084f68796df1a82ee97e32",
             "master_sha256": "fb8d4b5c24eef296b3e0f33468056172751a7e47a2678e8dacc444bf903c6107"}
SCOPE_SHA256 = "88b7c587c973cd320ba08c7ac6469de0eaf4db4be843b82a611b252062d21fa5"


def sample() -> list[dict]:
    return [{"record_id": "pg42957:contents", "text": "Page 1", "language": "en",
             "provenance": {"edition_title": "Modern Scepticism"},
             "source_references": [],
             "structure": [{"kind": "table-row",
                            "attributes": {"source_annotations": boundary.PG42957_ROW_REND},
                            "content": [
                                {"kind": "table-cell", "attributes": {"style": "tdr"},
                                 "content": [{"kind": "text", "text": "Page"}]},
                                {"kind": "table-cell", "attributes": {"style": "tdl"},
                                 "content": [{"kind": "reference", "attributes": {"source_target": "#Page_1"},
                                              "content": [{"kind": "text", "text": "1"}]}]},
                            ]}]}]


@pytest.mark.requires_local_artifacts
def test_pg42957_exact_accepted_source_and_scope_binding() -> None:
    assert sha256((EDITION / "acceptance.json").read_bytes()).hexdigest() == AUTHORITY["acceptance_sha256"]
    master = EDITION / "master.tei.xml"
    assert sha256(master.read_bytes()).hexdigest() == AUTHORITY["master_sha256"]
    root = ET.parse(master).getroot()
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    matched = root.findall(".//tei:row[@ana='urn:ocd:pg42957:legacy-row-rend:smaller']", ns)
    assert len(matched) == 1
    assert ["".join(cell.itertext()) for cell in matched[0].findall("tei:cell", ns)] == ["\xa0", "Page"]
    evidence = (HERE / "scope-evidence.json" if CANDIDATE.is_file() else
                WORK / "integration/pg42957-public-boundary-20261012-v1/scope-evidence.json")
    assert sha256(evidence.read_bytes()).hexdigest() == SCOPE_SHA256
    assert boundary._pg_authority(ITEM, **AUTHORITY)["pg42957_scope_evidence_sha256"] == SCOPE_SHA256


@pytest.mark.requires_local_artifacts
def test_pg42957_one_style_omission_preserves_cells_link_and_exact_inverse() -> None:
    private = sample()
    public, artifact = boundary.public_rows_with_omissions(private, item_id=ITEM, **AUTHORITY)
    assert artifact is not None and artifact["contract"] == boundary.PG_CONTRACT
    assert len(artifact["omissions"]) == 1 and len(artifact["omissions"][0]["fields"]) == 1
    assert artifact["omissions"][0]["fields"][0]["private"] == boundary.PG42957_ROW_REND
    assert artifact["omissions"][0]["fields"][0]["public"] is None
    assert "source_annotations" not in public[0]["structure"][0]["attributes"]
    assert public[0]["structure"][0]["content"] == private[0]["structure"][0]["content"]
    assert public[0]["text"] == private[0]["text"]
    assert not _scan(public, "PG42957 public rows")
    assert boundary.restore_private_source_locations(public, artifact, item_id=ITEM, **AUTHORITY) == private


@pytest.mark.parametrize("mutation", ["text", "link", "cell_style", "receipt_hash", "authority",
                                    "field", "missing_marker", "wrong_kind", "unknown_annotation"])
@pytest.mark.requires_local_artifacts
def test_pg42957_rejects_semantic_and_authority_mutations(mutation: str) -> None:
    private = sample()
    if mutation in {"missing_marker", "wrong_kind", "unknown_annotation"}:
        node = private[0]["structure"][0]
        if mutation == "missing_marker":
            del node["attributes"]["source_annotations"]
        elif mutation == "wrong_kind":
            node["kind"] = "table-cell"
        else:
            node["attributes"]["source_annotations"] = "urn:ocd:pg42957:legacy-row-rend:larger"
        with pytest.raises(PipelineError):
            boundary.public_rows_with_omissions(private, item_id=ITEM, **AUTHORITY)
        return
    public, artifact = boundary.public_rows_with_omissions(private, item_id=ITEM, **AUTHORITY)
    assert artifact is not None
    public, artifact = deepcopy(public), deepcopy(artifact)
    if mutation == "text":
        public[0]["text"] = "changed"
    elif mutation == "link":
        public[0]["structure"][0]["content"][1]["content"][0]["attributes"]["source_target"] = "#wrong"
    elif mutation == "cell_style":
        public[0]["structure"][0]["content"][0]["attributes"]["style"] = "wrong"
    elif mutation == "receipt_hash":
        artifact["omissions"][0]["original_row_sha256"] = "0" * 64
    elif mutation == "authority":
        artifact["authority"]["master_sha256"] = "0" * 64
    else:
        artifact["omissions"][0]["fields"][0]["path"] = ["text"]
    with pytest.raises(PipelineError):
        boundary.restore_private_source_locations(public, artifact, item_id=ITEM, **AUTHORITY)
