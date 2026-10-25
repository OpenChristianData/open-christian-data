"""Complete retained HTML and mutation checks for frozen PG55819."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.singmaster_pg55819_native import adapt
from build.tei.singmaster_pg55819_oracle import check
from build.tools.install_singmaster_pg55819 import preflight
from build.tools.stage_singmaster_pg55819 import ADAPTED_SHA256, DIRECT, DIRECT_SHA256


NS = {"tei": "http://www.tei-c.org/ns/1.0",
      "xml": "http://www.w3.org/XML/1998/namespace"}


def _candidate() -> bytes:
    direct = (DIRECT / "candidate.tei.xml").read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    return adapted


def test_complete_html_carriers_and_extracted_images() -> None:
    report = check(_candidate())
    assert report["selected_direct_children"] == 774
    assert report["carriers"] == 1010
    assert report["unique_extracted_images"] == 36
    assert report["page_breaks"] == 21
    assert report["notes"] == 11
    assert report["tables"] == 2
    assert len(report["chapters"]) == 6


def test_oracle_rejects_text_mutation() -> None:
    root = etree.fromstring(_candidate())
    carrier = root.xpath("//*[@xml:id='slm-src-B0100']", namespaces=NS)[0]
    carrier.text = (carrier.text or "") + " invented"
    with pytest.raises(ValueError, match="first carrier mismatch at 100"):
        check(etree.tostring(root))


def test_oracle_rejects_image_and_page_mutations() -> None:
    root = etree.fromstring(_candidate())
    root.xpath("//tei:graphic", namespaces=NS)[0].set("url", "https://example.invalid/other.jpg")
    with pytest.raises(ValueError, match="source image order"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    root.xpath("//tei:pb", namespaces=NS)[0].set("n", "999")
    with pytest.raises(ValueError, match="page-marker sequence"):
        check(etree.tostring(root))


def test_frozen_stage_read_only_preflight() -> None:
    import json
    from hashlib import sha256
    from build.tools import install_singmaster_pg55819 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "e2590a6b11213ccff21dff61c7ad04a5264e256cf0b294acbdf1a1192d6f26fd"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match="PG55819 current preimage or staged work generation differs"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
        return
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["image_support_members"] == 36
    assert result["package_support_members"] == 1
    assert result["native_rows"] == 13
