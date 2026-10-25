"""Exact source and feature mutation checks for Milligan's CCEL electronic edition."""

from __future__ import annotations

from pathlib import Path
import json
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib036_readable_milligan import convert
from build.tei.expositors_bible_lib036_readable_milligan_oracle import check
from tests.historical_notice_fixture import frozen_source_note
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path


MEMBER = "milligan-expositorrev"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
REPO = Path(__file__).resolve().parents[1]
NOTICE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib036-milligan-ccel-public-notice-20260927-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib036-milligan-stage-20260927-v2")


def _candidate(root: Path) -> Path:
    root.mkdir()
    tei, account = convert(MEMBER)
    candidate = root / f"{MEMBER}.tei.xml"
    candidate.write_bytes(tei)
    (root / f"{MEMBER}.source-accountability.json").write_bytes(account)
    return candidate


def test_exact_source_oracle_and_native_projection(tmp_path: Path) -> None:
    _candidate(tmp_path / "original")
    result = check(MEMBER, tmp_path / "original")
    assert result["source_elements"] == 4306
    assert result["source_comments"] == 10
    assert result["native_rows"] == 21
    assert result["p5"] is True


def test_oracle_rejects_changed_source_text(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-text")
    tree = etree.parse(str(candidate))
    node = next(node for node in tree.xpath("//tei:text//*[@xml:id]", namespaces=NS)
                if node.text and node.text.strip())
    node.text += " changed"
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source ID or direct text/tail differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_horizontal_rule(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-rule")
    tree = etree.parse(str(candidate))
    nodes = tree.xpath("//tei:milestone[@unit='horizontal-rule']", namespaces=NS)
    assert len(nodes) == 2
    nodes[0].set("unit", "other")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source horizontal rule differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_blockquote(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-quote")
    tree = etree.parse(str(candidate))
    nodes = tree.xpath("//tei:quote[@type='source-blockquote']", namespaces=NS)
    assert len(nodes) == 66
    nodes[0].set("type", "ordinary")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source blockquote type differs"):
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
