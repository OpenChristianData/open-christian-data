"""Exact source and unresolved-href checks for Edwards's CCEL electronic edition."""

from __future__ import annotations

from pathlib import Path
import json
import shutil

from lxml import etree
import pytest

from build.tei.expositors_bible_lib035_readable_edwards import convert
from build.tei.expositors_bible_lib035_readable_edwards_oracle import check
from tests.historical_notice_fixture import frozen_source_note
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path


MEMBER = "edwards-tc-expositorheb"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
REPO = Path(__file__).resolve().parents[1]
NOTICE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib035-edwards-ccel-public-notice-20260927-v1")
STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/expositors-lib035-edwards-stage-20260927-v1")


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
    account = json.loads((tmp_path / "original" / f"{MEMBER}.source-accountability.json").read_bytes())
    assert result["source_elements"] == 3646
    assert result["source_comments"] == 10
    assert result["native_rows"] == 21
    assert result["p5"] is True
    assert account["root_ids_in_order"] == ["i", "ii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi",
                                            "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix",
                                            "xx", "xxi", "xxii"]


def test_oracle_rejects_changed_source_text(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-text")
    tree = etree.parse(str(candidate))
    node = next(node for node in tree.xpath("//tei:text//*[@xml:id]", namespaces=NS)
                if node.text and node.text.strip())
    node.text += " changed"
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source ID or direct text/tail differs"):
        check(MEMBER, candidate.parent)


def test_oracle_rejects_changed_unresolved_href(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "changed-link")
    tree = etree.parse(str(candidate))
    nodes = tree.xpath("//tei:seg[@type='source-unresolved-link']", namespaces=NS)
    assert [node.get("n") for node in nodes] == ["#iii-Page_vii", "#iii-Page_viii"]
    nodes[0].set("n", "#invented")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="source-broken local link differs"):
        check(MEMBER, candidate.parent)


def test_p5_rejects_invented_link_target(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path / "invented-target")
    tree = etree.parse(str(candidate))
    nodes = tree.xpath("//tei:seg[@type='source-unresolved-link']", namespaces=NS)
    assert len(nodes) == 2
    nodes[1].set("target", "#invented")
    tree.write(str(candidate), encoding="utf-8", xml_declaration=True)
    with pytest.raises(ValueError, match="TEI P5"):
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
