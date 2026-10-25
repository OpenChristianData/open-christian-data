"""Exact source, index table, and image checks for Horton's CCEL edition."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from build.tei.expositors_bible_lib035_readable_horton import convert
from build.tei.expositors_bible_lib035_readable_horton_oracle import check
from tests.historical_notice_fixture import frozen_source_note
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path

MEMBER = "horton-expositorprov"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
REPO = Path(__file__).resolve().parents[1]
NOTICE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib035-horton-ccel-public-notice-20260927-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib035-horton-stage-20260927-v2")


def _candidate(root: Path) -> Path:
    root.mkdir()
    tei, account = convert(MEMBER)
    candidate = root / f"{MEMBER}.tei.xml"
    candidate.write_bytes(tei)
    (root / f"{MEMBER}.source-accountability.json").write_bytes(account)
    return candidate


def test_exact_source_oracle_table_image_and_native(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "original")
    result = check(MEMBER, candidate.parent)
    account = json.loads((candidate.parent / f"{MEMBER}.source-accountability.json").read_bytes())
    tree = etree.parse(str(candidate))
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (8320, 10, 36)
    assert result["p5"] is True
    assert len(account["root_ids_in_order"]) == 36
    assert len(tree.xpath("//tei:table/tei:row", namespaces=NS)) == 678
    assert len(tree.xpath("//tei:table/tei:row/tei:cell", namespaces=NS)) == 1263
    figures = tree.xpath("//tei:figure", namespaces=NS)
    assert len(figures) == 1
    assert [node.tag.rsplit("}", 1)[-1] for node in figures[0]] == ["graphic", "figDesc", "label"]


def test_oracle_rejects_changed_source_text(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-text")
    tree = etree.parse(str(candidate))
    node = next(node for node in tree.xpath("//tei:text//*[@xml:id]", namespaces=NS)
                if node.text and node.text.strip())
    node.text += " changed"
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source ID or direct text/tail differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_table_span(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-span")
    tree = etree.parse(str(candidate))
    cell = tree.xpath("//tei:table/tei:row/tei:cell[@cols='2']", namespaces=NS)[0]
    cell.set("cols", "1")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="table cell attributes differ"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_image_reference(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-image")
    tree = etree.parse(str(candidate))
    image = tree.xpath("//tei:figure/tei:graphic", namespaces=NS)[0]
    image.set("url", "/invented.png")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="image URL, alt, or title differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_image_alt(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-alt")
    tree = etree.parse(str(candidate))
    tree.xpath("//tei:figure/tei:figDesc", namespaces=NS)[0].text = "invented"
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="image URL, alt, or title differs"):
        check(MEMBER, candidate.parent)


def test_future_visible_notice_binds_exact_source_note(tmp_path: Path) -> None:
    index = json.loads((NOTICE_HOME / "notice-index.json").read_bytes())
    for source, relative in ((REPO / index["source_path"], index["source_path"]),
                             (NOTICE_HOME / index["notice_path"], index["notice_path"])):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if relative == index["source_path"]:
            destination.write_bytes(frozen_source_note(source.read_bytes(), index["source_sha256"]))
        else:
            shutil.copy2(source, destination)
    acceptance_source = (STAGE / "library/works" / index["work_id"] / "forms" /
                         index["textual_form_id"] / "editions" / index["edition_id"] /
                         "acceptance.json")
    assert _io_path(acceptance_source).is_file()
    acceptance = tmp_path / "acceptance.json"
    shutil.copy2(_io_path(acceptance_source), acceptance)
    binding = {key: index[key] for key in
               ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    selected = {"work_id": index["work_id"], "public_notices": [binding]}
    texts = notice_texts_for_item(tmp_path, selected, acceptance)
    assert len(texts) == 1
    assert "CCEL.org" in texts[0]
    (tmp_path / index["notice_path"]).write_text(texts[0] + "changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, selected, acceptance)
