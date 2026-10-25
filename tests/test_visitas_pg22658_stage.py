"""Complete Portuguese HTML and guarded-stage checks for PG22658."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.visitas_pg22658_native import DIRECT, DIRECT_SHA256, TEI, adapt
from build.tei.visitas_pg22658_oracle import check
from build.tools.install_visitas_pg22658 import preflight
from build.tools.stage_visitas_pg22658 import ADAPTED_SHA256
from ocd_kernel.tei.validate import compiled_schema


XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _candidate() -> bytes:
    direct = DIRECT.read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    assert compiled_schema().validate(etree.fromstring(adapted))
    return adapted


def test_complete_1858_portuguese_witness_oracle() -> None:
    report = check(_candidate())
    assert report["direct_children"] == 5576
    assert report["html_carriers"] == 10601
    assert report["headings"] == 431
    assert report["paragraphs"] == 5070
    assert report["hyperlinks"] == 139
    assert report["images"] == 4
    assert report["container_pairs"] == 7


def test_oracle_rejects_text_heading_and_link_mutations() -> None:
    root = etree.fromstring(_candidate())
    next(root.find(TEI + "text").iter(TEI + "p")).text = "invented"
    with pytest.raises(ValueError, match="complete ordered source/TEI text"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "head")).text = "wrong heading"
    with pytest.raises(ValueError, match="complete ordered source/TEI text|heading sequence"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "ref")).set("target", "#wrong")
    with pytest.raises(ValueError, match="ordered hyperlink targets"):
        check(etree.tostring(root))


def test_oracle_rejects_image_paragraph_and_boundary_mutations() -> None:
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "graphic")).set("url", "images/wrong.png")
    with pytest.raises(ValueError, match="referenced images"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    paragraph = next(node for node in root.iter(TEI + "p")
                     if node.get("rend") == "html-div pg_body_wrapper")
    paragraph.set("rend", "wrong")
    with pytest.raises(ValueError, match="source paragraph sequence"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    marker = next(node for node in root.iter(TEI + "anchor")
                  if node.get("type") == "source-container-start")
    marker.set("type", "wrong")
    with pytest.raises(ValueError, match="provider/container boundary"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "lb")).tag = TEI + "anchor"
    with pytest.raises(ValueError, match="line-break or horizontal-rule positions"):
        check(etree.tostring(root))


def test_frozen_stage_read_only_preflight() -> None:
    import json
    from hashlib import sha256
    from build.tools import install_visitas_pg22658 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "1a49db7db629a7d735898dbe099bc019f65e62ca95d73b75189966d6b03ad107"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match="PG22658 current preimage or staged work generation differs"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
        return
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["before_files"] == 3
    assert result["after_files"] == 18
    assert result["image_support_members"] == 5
    assert result["package_support_members"] == 1
    assert result["native_rows"] == 426
