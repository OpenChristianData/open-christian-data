"""Exact HTML and image-support mutations for the frozen PG55955 stage."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.ports_of_entry_pg55955_native import adapt
from build.tei.ports_of_entry_pg55955_oracle import check
from build.tools.install_ports_of_entry_pg55955 import preflight
from build.tools.stage_ports_of_entry_pg55955 import ADAPTED_SHA256, DIRECT, DIRECT_SHA256


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _candidate() -> bytes:
    source = (DIRECT / "candidate.tei.xml").read_bytes()
    assert sha256(source).hexdigest() == DIRECT_SHA256
    adapted = adapt(source)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    return adapted


def test_complete_source_and_image_support_oracle() -> None:
    report = check(_candidate())
    assert report["source_carriers"] == 868
    assert report["image_occurrences"] == 12
    assert report["image_members"] == 11
    assert report["page_markers"] == 30
    assert report["tables"] == 7
    assert report["sections"] == 5


def test_oracle_rejects_mutated_carrier_and_order() -> None:
    root = etree.fromstring(_candidate())
    carrier = root.xpath("//*[@xml:id='poe-src-B0100']", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
    carrier.text = (carrier.text or "") + " invented"
    with pytest.raises(ValueError, match="source carrier 100 differs"):
        check(etree.tostring(root))


def test_oracle_rejects_missing_image_or_page() -> None:
    root = etree.fromstring(_candidate())
    graphic = root.xpath("//tei:figure/tei:graphic", namespaces=NS)[0]
    graphic.set("url", "https://example.invalid/other.jpg")
    with pytest.raises(ValueError, match="image occurrence order"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    page = root.xpath("//tei:pb", namespaces=NS)[0]
    page.set("n", "999")
    with pytest.raises(ValueError, match="page-marker sequence"):
        check(etree.tostring(root))


def test_frozen_stage_read_only_preflight() -> None:
    import json
    from hashlib import sha256
    from build.tools import install_ports_of_entry_pg55955 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "8db75a7dc1e3acd81aff9e078e4d37b3efc8042796435b6fab1c746b6677a2ad"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match="PG55955 current preimage or staged work generation differs"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
        return
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["image_support_members"] == 11
    assert result["native_rows"] == 10
