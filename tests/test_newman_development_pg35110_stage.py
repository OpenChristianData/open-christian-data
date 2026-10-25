"""Exact extracted-HTML and mutation checks for frozen Newman PG35110."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.newman_development_pg35110_native import adapt
from build.tei.newman_development_pg35110_oracle import check
from build.tools.install_newman_development_pg35110 import preflight
from build.tools.stage_newman_development_pg35110 import ADAPTED_SHA256, DIRECT, DIRECT_SHA256


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _candidate() -> bytes:
    direct = (DIRECT / "content.tei.xml").read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    return adapted


def test_complete_sixth_edition_extracted_html_oracle() -> None:
    report = check(_candidate())
    assert report["selected_direct_children"] == 1699
    assert report["excluded_layout_pre"] == 2
    assert report["printed_pages"] == 458
    assert report["greek_spans"] == 26
    assert report["note_references"] == 401
    assert report["note_bodies"] == 400
    assert report["chapters"] == 12


def test_oracle_rejects_visible_text_and_title_changes() -> None:
    root = etree.fromstring(_candidate())
    paragraph = root.xpath("//tei:body//tei:p", namespaces=NS)[0]
    paragraph.text = (paragraph.text or "") + " invented"
    with pytest.raises(ValueError, match="complete-body text stream"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)[0].text = "Wrong title"
    with pytest.raises(ValueError, match="electronic title"):
        check(etree.tostring(root))


def test_oracle_rejects_page_greek_and_note_mutations() -> None:
    root = etree.fromstring(_candidate())
    root.xpath("//tei:pb", namespaces=NS)[0].set("n", "wrong")
    with pytest.raises(ValueError, match="printed-page marker sequence"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("//tei:foreign/tei:seg", namespaces=NS)[0].set("n", "wrong")
    with pytest.raises(ValueError, match="Greek/transliteration span 1"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("//tei:ref[@type='note']", namespaces=NS)[0].set("target", "#wrong")
    with pytest.raises(ValueError, match="footnote sequence"):
        check(etree.tostring(root))


def test_frozen_stage_read_only_preflight() -> None:
    import json
    from hashlib import sha256
    from build.tools import install_newman_development_pg35110 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "db60ad8ee6ce9a887fd38f91858b1a4fd8c0daf29c80c5c4fe0432571f107903"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match="PG35110 current preimage or staged work generation differs"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
        return
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["image_support_members"] == 1
    assert result["package_support_members"] == 1
    assert result["native_rows"] == 11
