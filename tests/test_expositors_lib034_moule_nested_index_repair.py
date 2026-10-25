"""Exact source and accepted-master semantics for Moule's nested Index repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib034_readable_moule_index_v4_oracle import check
from build.tools.stage_expositors_lib034_moule_nested_index_repair import _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


MEMBER = "moule-expositorromans"
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/"
                 "expositors-lib034-moule-index-v4-candidate-20260928-v1/moule-expositorromans")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/"
             "expositors-lib034-moule-nested-index-repair-stage-20260928-v1")
WORK = Path("library/works/expositors-bible--h-c-g-moule")
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


def test_source_oracle_and_four_node_delta() -> None:
    result = check(MEMBER, CANDIDATE, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (6373, 14, 36)
    old = _io_path(WORK / "integration/moule-expositorromans-readable-electronic-v1/inputs/package/content.tei.xml").read_bytes()
    new = (CANDIDATE / "content.tei.xml").read_bytes()
    assert [(row["tei_id"], row["after"]) for row in _source_only_delta(old, new)] == [
        (f"{MEMBER}-feature-005655", "div/source-index"),
        (f"{MEMBER}-xxxvi.ii-p0.2", "div/source-hebrew"),
        (f"{MEMBER}-feature-005850", "div/source-index"),
        (f"{MEMBER}-feature-005928", "div/source-index"),
    ]


def test_source_oracle_rejects_index_as_quote(tmp_path: Path) -> None:
    _mutate(tmp_path, "div", "source-index", "quote", "source-div")
    with pytest.raises(ValueError, match="TEI tag differs"):
        check(MEMBER, tmp_path, formal=True)


def test_source_oracle_rejects_hebrew_parent_as_quote(tmp_path: Path) -> None:
    path = _mutate(tmp_path, "div", "source-hebrew", "quote", "source-div")
    tree = etree.parse(str(path))
    hebrew = tree.find(f".//{NS}quote[@{XML_ID}='{MEMBER}-xxxvi.ii-p0.2']")
    assert hebrew is not None and len(hebrew.findall(f".//{NS}div[@type='source-index']")) == 1
    with pytest.raises(ValueError, match="TEI P5"):
        check(MEMBER, tmp_path, formal=True)


def test_other_source_divs_remain_quotations(tmp_path: Path) -> None:
    tree = etree.parse(str(CANDIDATE / "content.tei.xml"))
    assert len(tree.findall(f".//{NS}quote[@type='source-div']")) == 50
    _mutate(tmp_path, "quote", "source-div", "quote", "source-index")
    with pytest.raises(ValueError, match="source div class carrier differs"):
        check(MEMBER, tmp_path, formal=True)


def test_staged_accepted_text_changes_only_at_hebrew_and_indexes() -> None:
    relative = next(path for path in _files(WORK) if path.endswith("/master.tei.xml"))
    prior = _io_path(WORK / "integration" / (MEMBER + "-readable-electronic-v1") / "candidate.tei.xml").read_bytes()
    assert sha256(prior).hexdigest() == "9a3de7a07c719459f0aaae5bb00728a29a4eef642953b2f392ce6c5148aa7095"
    delta = _source_only_delta(prior,
                               _io_path(STAGE / WORK / relative).read_bytes())
    assert len(delta) == 4


def test_full_delta_rejects_other_attribute_change() -> None:
    old = _io_path(WORK / "integration/moule-expositorromans-readable-electronic-v1/inputs/package/content.tei.xml").read_bytes()
    tree = etree.parse(str(CANDIDATE / "content.tei.xml"))
    carrier = tree.find(f".//{NS}div[@{XML_ID}='{MEMBER}-xxxvi.ii-p0.2']")
    assert carrier is not None
    carrier.set("n", "unattested")
    with pytest.raises(ValueError, match="unapproved TEI change"):
        _source_only_delta(old, etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
