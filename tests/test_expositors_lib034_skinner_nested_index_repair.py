"""Exact source and accepted-master semantics for Skinner's nested Index repair."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib034_readable_skinner_index_v4_oracle import check
from build.tools.stage_expositors_lib034_skinner_nested_index_repair import _source_only_delta
from ocd_kernel.tei.install_accepted import _files, _io_path


MEMBER = "skinner-expositorezek"
CANDIDATE = Path("D:/Library/Open Christian Data/candidate-reviews/"
                 "expositors-lib034-skinner-index-v4-candidate-20260928-v1/skinner-expositorezek")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/"
             "expositors-lib034-skinner-nested-index-repair-stage-20260928-v2")
WORK = Path("library/works/expositors-bible--john-skinner")
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


def test_source_oracle_and_five_node_delta() -> None:
    result = check(MEMBER, CANDIDATE, formal=True)
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (3752, 18, 8)
    old = _io_path(WORK / "integration/skinner-expositorezek-readable-electronic-v1/inputs/package/content.tei.xml").read_bytes()
    new = (CANDIDATE / "content.tei.xml").read_bytes()
    assert [(row["tei_id"], row["after"]) for row in _source_only_delta(old, new)] == [
        (f"{MEMBER}-feature-003085", "div/source-index"),
        (f"{MEMBER}-viii.ii-p0.2", "div/source-hebrew"),
        (f"{MEMBER}-feature-003127", "div/source-index"),
        (f"{MEMBER}-feature-003249", "div/source-index"),
        (f"{MEMBER}-feature-003262", "div/source-index"),
    ]


def test_source_oracle_rejects_index_as_quote(tmp_path: Path) -> None:
    _mutate(tmp_path, "div", "source-index", "quote", "source-div")
    with pytest.raises(ValueError, match="TEI tag differs"):
        check(MEMBER, tmp_path, formal=True)


def test_source_oracle_rejects_hebrew_parent_as_quote(tmp_path: Path) -> None:
    path = _mutate(tmp_path, "div", "source-hebrew", "quote", "source-div")
    tree = etree.parse(str(path))
    hebrew = tree.find(f".//{NS}quote[@{XML_ID}='{MEMBER}-viii.ii-p0.2']")
    assert hebrew is not None and len(hebrew.findall(f".//{NS}div[@type='source-index']")) == 1
    with pytest.raises(ValueError, match="TEI P5"):
        check(MEMBER, tmp_path, formal=True)


def test_staged_accepted_text_changes_only_at_hebrew_and_indexes() -> None:
    relative = next(path for path in _files(WORK) if path.endswith("/master.tei.xml"))
    prior = _io_path(WORK / "integration" / (MEMBER + "-readable-electronic-v1") / "candidate.tei.xml").read_bytes()
    assert sha256(prior).hexdigest() == "7c884d4128db4961ff48fff44370582e641ec537c34f89925857d209db986ff1"
    delta = _source_only_delta(prior,
                               _io_path(STAGE / WORK / relative).read_bytes())
    assert len(delta) == 5


def test_full_delta_rejects_other_attribute_change() -> None:
    old = _io_path(WORK / "integration/skinner-expositorezek-readable-electronic-v1/inputs/package/content.tei.xml").read_bytes()
    tree = etree.parse(str(CANDIDATE / "content.tei.xml"))
    carrier = tree.find(f".//{NS}div[@{XML_ID}='{MEMBER}-viii.ii-p0.2']")
    assert carrier is not None
    carrier.set("n", "unattested")
    with pytest.raises(ValueError, match="unapproved TEI change"):
        _source_only_delta(old, etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
