"""Exact source and accepted-master semantics for Edwards's nested Index repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib035_readable_edwards_index_v2_oracle import check
from build.tools.stage_expositors_lib035_edwards_nested_index_repair import _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


MEMBER = "edwards-tc-expositorheb"
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/"
                 "expositors-lib035-edwards-index-v2-candidate-20260928-v2/edwards-tc-expositorheb")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/"
             "expositors-lib035-edwards-nested-index-repair-stage-20260928-v1")
WORK = Path("library/works/expositors-bible--thomas-charles-edwards")
NS = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _mutate(tmp_path: Path, tag: str, kind: str, replacement_tag: str, replacement_type: str) -> Path:
    for name in ("content.tei.xml", "source-accountability.json"):
        shutil.copy2(CANDIDATE / name, tmp_path / name)
    path = tmp_path / "content.tei.xml"
    tree = etree.parse(str(path))
    carrier = tree.find(f".//{NS}{tag}[@type='{kind}']")
    assert carrier is not None
    carrier.tag = NS + replacement_tag
    carrier.set("type", replacement_type)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    return path


def test_source_oracle_and_three_node_delta() -> None:
    result = check(MEMBER, CANDIDATE, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (3646, 10, 21)
    old = _io_path(WORK / "integration/edwards-tc-expositorheb-readable-electronic-v1/inputs/package/content.tei.xml").read_bytes()
    new = (CANDIDATE / "content.tei.xml").read_bytes()
    assert [(row["tei_id"], row["after"]) for row in _source_only_delta(old, new)] == [
        (f"{MEMBER}-xxii.i-p0.2", "div/source-greek"),
        (f"{MEMBER}-feature-002857", "div/source-index"),
        (f"{MEMBER}-feature-003310", "div/source-index"),
    ]


def test_source_oracle_rejects_index_as_quote(tmp_path: Path) -> None:
    _mutate(tmp_path, "div", "source-index", "quote", "source-div")
    with pytest.raises(ValueError, match="TEI tag differs"):
        check(MEMBER, tmp_path, formal=True)


def test_source_oracle_rejects_greek_parent_as_quote(tmp_path: Path) -> None:
    path = _mutate(tmp_path, "div", "source-greek", "quote", "source-div")
    tree = etree.parse(str(path))
    greek = tree.find(f".//{NS}quote[@{XML_ID}='{MEMBER}-xxii.i-p0.2']")
    assert greek is not None and len(greek.findall(f".//{NS}div[@type='source-index']")) == 1
    with pytest.raises(ValueError, match="TEI P5"):
        check(MEMBER, tmp_path, formal=True)


def test_source_oracle_preserves_other_quote_divs(tmp_path: Path) -> None:
    _mutate(tmp_path, "quote", "source-div", "quote", "source-index")
    with pytest.raises(ValueError, match="source div class carrier differs"):
        check(MEMBER, tmp_path, formal=True)


def test_staged_accepted_text_changes_only_at_greek_and_indexes() -> None:
    relative = next(path for path in _files(WORK) if path.endswith("/master.tei.xml"))
    prior = _io_path(WORK / "integration" / (MEMBER + "-readable-electronic-v1") / "candidate.tei.xml").read_bytes()
    assert sha256(prior).hexdigest() == "95774d47608c93d2666a19d434b1015a6900f720925deaf2071d6baf4a49c90d"
    delta = _source_only_delta(prior,
                               _io_path(STAGE / WORK / relative).read_bytes())
    assert len(delta) == 3
