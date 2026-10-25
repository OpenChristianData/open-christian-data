"""Complete HTML, line, image, and frozen-stage checks for Keble PG4272."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.keble_pg4272_native import DIRECT, DIRECT_SHA256, adapt
from build.tei.keble_pg4272_oracle import check
from build.tools import install_keble_pg4272 as installer
from build.tools.install_keble_pg4272 import preflight
from tests.frozen_install_preimages import copy_recorded_preimage, copy_stage_dependencies
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files
from build.tools.stage_keble_pg4272 import ADAPTED_SHA256
from ocd_kernel.tei.validate import compiled_schema


TEI = "{http://www.tei-c.org/ns/1.0}"


def _candidate() -> bytes:
    direct = DIRECT.read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    assert compiled_schema().validate(etree.fromstring(adapted))
    return adapted


def test_complete_1887_christian_year_source_oracle() -> None:
    report = check(_candidate())
    assert report["selected_direct_children"] == 1459
    assert report["headings"] == 116
    assert report["line_breaks"] == 5369
    assert len(report["image_references"]) == 2
    assert len(report["image_sha256"]) == 4


def test_oracle_rejects_text_heading_and_line_mutations() -> None:
    root = etree.fromstring(_candidate())
    paragraph = next(root.find(TEI + "text").iter(TEI + "p"))
    paragraph.text = (paragraph.text or "") + " invented"
    with pytest.raises(ValueError, match="complete ordered source/TEI text"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "head")).text = "Wrong heading"
    with pytest.raises(ValueError, match="complete ordered source/TEI text|full heading sequence"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    line_break = next(root.iter(TEI + "lb"))
    line_break.tag = TEI + "seg"
    with pytest.raises(ValueError, match="line-break sequence"):
        check(etree.tostring(root))


def test_oracle_rejects_image_and_wrapper_mutations() -> None:
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "graphic")).set("url", "images/coverb.jpg")
    with pytest.raises(ValueError, match="referenced image 1"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "graphic")).set("ana", "urn:ocd:source-alt-and-title:Wrong")
    with pytest.raises(ValueError, match="referenced image 1"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "graphic")).getparent().set("target", "images/tpb.jpg")
    with pytest.raises(ValueError, match="referenced image 1"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    provider = next(node for node in root.iter(TEI + "div") if node.get("type") == "provider-footer")
    provider.set("type", "other")
    with pytest.raises(ValueError, match="provider wrapper"):
        check(etree.tostring(root))


def test_frozen_stage_read_only_preflight(tmp_path, monkeypatch) -> None:
    original_root = installer.ROOT
    before = _files(original_root / installer.WORK)
    root = tmp_path / "original-acquired"
    root.mkdir()
    copy_stage_dependencies(installer.STAGE, installer.WORK, root)
    copy_recorded_preimage(installer.STAGE, installer.WORK, installer.RECEIPT_SHA256, root)
    monkeypatch.setattr(installer, "ROOT", root)
    result = preflight()
    assert _files(original_root / installer.WORK) == before
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["before_files"] == 3
    assert result["after_files"] == 18
    assert result["image_support_members"] == 4
    assert result["package_support_members"] == 1
    assert result["native_rows"] == 1


def test_current_accepted_generation_rejects_frozen_preimage() -> None:
    import json
    record = json.loads((installer.STAGE / "stage-receipt.json").read_bytes())
    before = _files(installer.ROOT / installer.WORK)
    assert before != record["before"]
    with pytest.raises(PipelineError, match="current preimage or staged work generation differs"):
        preflight()
    assert _files(installer.ROOT / installer.WORK) == before
