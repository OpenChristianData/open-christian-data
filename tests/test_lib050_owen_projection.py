"""Exact three-child Owen source and public-row checks."""

from copy import deepcopy
from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import lib050_owen
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.release.public_allowlist import _scan

STAGE = Path(r"D:\Library\Open Christian Data\l50-a2")
WORK = "john-owen-apostasy"
SOURCE = Path("raw/ccel/owen/apostasy.xml")
NS = "{http://www.tei-c.org/ns/1.0}"


def _acceptance() -> Path:
    return next((STAGE / "library/works" / WORK).rglob("acceptance.json"))


def test_exact_source_profile_row_and_mutations() -> None:
    acceptance = _acceptance()
    result = project_accepted_prose(STAGE, acceptance_path=acceptance)
    assert len(result["rows"]) == 1
    assert _scan(result["rows"], "LIB-050 Owen regression") == []
    assert result["receipt"]["source_binding"]["processing_instruction_count"] > 0
    assert result["receipt"]["source_binding"]["source_node_count"] > 0
    assert verify_accepted_prose(STAGE, acceptance_path=acceptance,
                                 rows=result["rows"], receipt=result["receipt"]) == []
    changed_rows = deepcopy(result["rows"])
    changed_rows[0]["text"] = changed_rows[0]["text"][1:]
    assert verify_accepted_prose(STAGE, acceptance_path=acceptance,
                                 rows=changed_rows, receipt=result["receipt"])
    changed_receipt = deepcopy(result["receipt"])
    changed_receipt["source_binding"]["processing_instruction_count"] -= 1
    assert verify_accepted_prose(STAGE, acceptance_path=acceptance,
                                 rows=result["rows"], receipt=changed_receipt)


@pytest.mark.parametrize("mutation", ["evidence-reordered", "readable-omitted"])
def test_master_reorder_or_omission_rejected(tmp_path: Path, monkeypatch, mutation: str) -> None:
    acceptance = _acceptance()
    master = next((STAGE / "library/works" / WORK).rglob("master.tei.xml"))
    tree = etree.fromstring(master.read_bytes())
    division = tree.find(NS + "text/" + NS + "body/" + NS + "div")
    if mutation == "evidence-reordered":
        evidence = division[2]
        ledger = evidence[1]
        ledger.insert(0, ledger[1])
    else:
        readable = division[1]
        readable.remove(readable[0])
    altered = tmp_path / "altered.tei.xml"
    altered.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    original_io_path = lib050_owen.io_path
    monkeypatch.setattr(lib050_owen, "io_path", lambda path: altered if Path(path) == master else original_io_path(path))
    with pytest.raises(PipelineError, match="accepted header or master differs"):
        lib050_owen._checked(STAGE, acceptance)


def test_retained_source_tamper_rejected(tmp_path: Path, monkeypatch) -> None:
    acceptance = _acceptance()
    source = STAGE / SOURCE
    altered = tmp_path / "altered-source.xml"
    altered.write_bytes(source.read_bytes() + b" ")
    original_io_path = lib050_owen.io_path
    monkeypatch.setattr(lib050_owen, "io_path", lambda path: altered if Path(path) == source else original_io_path(path))
    with pytest.raises(PipelineError, match="retained source differs"):
        lib050_owen._checked(STAGE, acceptance)


def test_private_annotation_aliases_are_stable_and_fail_closed() -> None:
    rows = [{"attributes": {"source_annotations": "urn:ocd:tei-date-when:1850 urn:ocd:tei-cell-rows:4"}}]
    public_rows, count = lib050_owen._alias_private_source_annotations(rows)
    assert public_rows[0]["attributes"]["source_annotations"] == "source-annotation:00001 source-annotation:00002"
    assert count == 2
    assert rows[0]["attributes"]["source_annotations"].startswith("urn:ocd:")
    assert _scan(public_rows, "LIB-050 Owen regression") == []
    unknown_rows, unknown_count = lib050_owen._alias_private_source_annotations([{
        "attributes": {"source_annotations": "urn:ocd:unrecognized:value"}
    }])
    assert unknown_rows[0]["attributes"]["source_annotations"] == "source-annotation:00001"
    assert unknown_count == 1
    assert _scan(unknown_rows, "LIB-050 Owen regression") == []
