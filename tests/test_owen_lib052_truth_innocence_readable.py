"""Exact source and native checks for Owen's Truth and Innocence Vindicated CCEL edition."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lxml import etree
import pytest

from tests.historical_notice_fixture import frozen_source_note

from build.tei.owen_lib052_truth_innocence_readable import convert
from build.tei.owen_lib052_truth_innocence_readable_oracle import check
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path

MEMBER = "truth-innocence"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
REPO = Path(__file__).resolve().parents[1]
NOTICE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/owen-lib052-truth-innocence-ccel-public-notice-20260928-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/owen-lib052-truth-innocence-stage-20260928-v1")


def _candidate(root: Path) -> Path:
    root.mkdir()
    tei, account = convert(MEMBER)
    candidate = root / f"{MEMBER}.tei.xml"
    candidate.write_bytes(tei)
    (root / f"{MEMBER}.source-accountability.json").write_bytes(account)
    return candidate


def test_exact_source_oracle_index_markers_and_native(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "original")
    result = check(MEMBER, candidate.parent)
    account = json.loads((candidate.parent / f"{MEMBER}.source-accountability.json").read_bytes())
    tree = etree.parse(str(candidate))
    assert (result["source_elements"], result["source_comments"], result["native_rows"]) == (2094, 30, 2)
    assert result["p5"] is True
    assert tree.xpath("string(//tei:teiHeader//tei:title[1])", namespaces=NS) == "Truth and Innocence Vindicated"
    assert account["root_ids_in_order"] == ["i", "ii"]
    assert len(tree.xpath("//tei:p[@rend='source-argument']", namespaces=NS)) == 6
    assert len(tree.xpath("//tei:p[@rend='source-attribution']", namespaces=NS)) == 16
    markers = tree.xpath("//tei:milestone[@unit='insertIndex']", namespaces=NS)
    assert [(node.get("type"), node.get("{http://www.w3.org/XML/1998/namespace}lang"))
            for node in markers] == [("scripRef", None), ("cite", None), ("name", None), ("foreign", "EL"), ("foreign", "HE"),
                                    ("foreign", "LA"), ("pb", None)]


def test_oracle_rejects_changed_source_text(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-text")
    tree = etree.parse(str(candidate))
    node = next(node for node in tree.xpath("//tei:text//*[@xml:id]", namespaces=NS)
                if node.text and node.text.strip())
    node.text += " changed"
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source ID or direct text/tail differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_copied_header_title(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-header")
    tree = etree.parse(str(candidate))
    tree.xpath("//tei:teiHeader//tei:title[1]", namespaces=NS)[0].text = (
        "The Expositor's Bible: Truth and Innocence Vindicated"
    )
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="electronic header title differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_index_language_rewrite(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-index-language")
    tree = etree.parse(str(candidate))
    node = tree.xpath("//tei:milestone[@unit='insertIndex'][@type='foreign']", namespaces=NS)[0]
    node.set("{http://www.w3.org/XML/1998/namespace}lang", "LA")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source index marker type/language differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_argument_type(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-argument")
    tree = etree.parse(str(candidate))
    node = tree.xpath("//tei:p[@rend='source-argument']", namespaces=NS)[0]
    node.set("rend", "ordinary")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source argument type differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_attribution_type(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-attribution")
    tree = etree.parse(str(candidate))
    node = tree.xpath("//tei:p[@rend='source-attribution']", namespaces=NS)[0]
    node.set("rend", "ordinary")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source attribution type differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_index_type(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-index-type")
    tree = etree.parse(str(candidate))
    node = tree.xpath("//tei:milestone[@unit='insertIndex']", namespaces=NS)[0]
    node.set("type", "invented")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source index marker type/language differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_index_comment_change(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-comment")
    ledger_path = candidate.parent / f"{MEMBER}.source-accountability.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["comments"][0]["text"] += " changed"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    with pytest.raises(ValueError, match="source comments ledger differs"):
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
    assert "CCEL.org" in texts[0] and "AGES" in texts[0]
    (tmp_path / index["notice_path"]).write_text(texts[0] + "changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, selected, acceptance)
