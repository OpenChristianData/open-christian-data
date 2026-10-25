"""Complete retained HTML and mutation checks for Lightfoot PG18191."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.lightfoot_essays_pg18191_native import adapt
from build.tei.lightfoot_essays_pg18191_oracle import check
from build.tools.install_lightfoot_essays_pg18191 import preflight
from build.tools.stage_lightfoot_essays_pg18191 import ADAPTED_SHA256, DIRECT, DIRECT_SHA256


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _candidate() -> bytes:
    direct = (DIRECT / "candidate.tei.xml").read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    return adapted


def test_full_electronic_html_group_and_package_oracle() -> None:
    report = check(_candidate())
    assert report["selected_direct_children"] == 1872
    assert report["source_groups"] == 18
    assert report["source_ids"] == 1880
    assert report["relocated_notes"] == 708
    assert report["package_count"] == 3
    assert report["provider_header_footer_included"]


def test_oracle_rejects_body_text_and_group_reordering() -> None:
    root = etree.fromstring(_candidate())
    root.xpath("//tei:body//tei:p", namespaces=NS)[0].text = "invented"
    with pytest.raises(ValueError, match="complete ordered HTML/TEI text"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    body = root.xpath("//tei:body", namespaces=NS)[0]
    first = body[0]
    body.remove(first)
    body.insert(1, first)
    with pytest.raises(ValueError, match="complete ordered HTML/TEI text"):
        check(etree.tostring(root))


def test_oracle_rejects_source_identifier_and_title_changes() -> None:
    root = etree.fromstring(_candidate())
    root.xpath("//*[@xml:id]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0].set(
        "{http://www.w3.org/XML/1998/namespace}id", "wrong"
    )
    with pytest.raises(ValueError, match="source ID accounting"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS)[0].text = "Wrong title"
    with pytest.raises(ValueError, match="electronic title"):
        check(etree.tostring(root))


def test_frozen_stage_read_only_preflight() -> None:
    import json
    from hashlib import sha256
    from build.tools import install_lightfoot_essays_pg18191 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "95ce58f8fb542bc0a9707bdd6ad55a0cf3537e1af33d5e6bd345ee57211929bb"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match="PG18191 current preimage or staged work generation differs"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
        return
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["package_support_members"] == 3
    assert result["package_only_cover_members"] == 1
    assert result["native_rows"] == 18
