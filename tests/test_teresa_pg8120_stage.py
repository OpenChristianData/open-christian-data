"""Exact extracted-HTML and mutation checks for the Teresa PG8120 stage."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.teresa_pg8120_native import adapt
from build.tei.teresa_pg8120_oracle import check
from build.tools.install_teresa_pg8120 import preflight
from build.tools.stage_teresa_pg8120 import ADAPTED_SHA256, DIRECT, DIRECT_SHA256
from ocd_kernel.tei.install_accepted import _io_path


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _candidate() -> bytes:
    direct = _io_path(DIRECT / "content.tei.xml").read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    return adapted


def test_complete_third_edition_extracted_html_oracle() -> None:
    report = check(_candidate())
    assert report["selected_direct_roots"] == 2503
    assert report["life_chapters"] == 40
    assert report["relations"] == 11
    assert report["titled_abbreviations"] == 528
    assert report["citations"] == 337
    assert report["note_links"] == report["note_bodies"] == 730


def test_oracle_rejects_body_title_and_expansion_mutations() -> None:
    root = etree.fromstring(_candidate())
    paragraph = root.xpath("//tei:body//tei:p", namespaces=NS)[0]
    paragraph.text = (paragraph.text or "") + " invented"
    with pytest.raises(ValueError, match="complete ordered source/TEI text"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)[0].text = "Wrong title"
    with pytest.raises(ValueError, match="electronic title"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("//tei:seg[@ana='urn:ocd:abbreviation-expansion']", namespaces=NS)[0].set("n", "wrong")
    with pytest.raises(ValueError, match="abbreviation expansion 1"):
        check(etree.tostring(root))


def test_oracle_rejects_citation_and_note_mutations() -> None:
    root = etree.fromstring(_candidate())
    root.xpath("//tei:seg[@rend='citation']", namespaces=NS)[0].set("rend", "wrong")
    with pytest.raises(ValueError, match="cited-title counts"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("//tei:ref[@type='note']", namespaces=NS)[0].set("target", "#missing")
    with pytest.raises(ValueError, match="source note reference/body accounting"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    references = root.xpath("//tei:ref[@type='note']", namespaces=NS)
    references[0].set("target", references[1].get("target"))
    with pytest.raises(ValueError, match="source note target 1"):
        check(etree.tostring(root))


def test_frozen_stage_read_only_preflight() -> None:
    import json
    from hashlib import sha256
    from build.tools import install_teresa_pg8120 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "00f425916e068df4b0b0a9e7151725015655294eb989239437040f418c61628a"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match="PG8120 current preimage or staged work generation differs"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
        return
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["image_support_members"] == result["package_support_members"] == 1
    assert result["native_rows"] == 9
