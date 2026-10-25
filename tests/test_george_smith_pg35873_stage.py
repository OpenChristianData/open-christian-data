"""Source-bound and guarded checks for the complete PG35873 biography."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.george_smith_pg35873_native import DIRECT, DIRECT_SHA256, TEI, adapt
from build.tei.george_smith_pg35873_oracle import check
from build.tools import install_george_smith_pg35873 as installer
from build.tools.install_george_smith_pg35873 import preflight
from tests.frozen_install_preimages import copy_recorded_preimage, copy_stage_dependencies
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files
from build.tools.stage_george_smith_pg35873 import ADAPTED_SHA256
from ocd_kernel.tei.validate import compiled_schema


XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _candidate() -> bytes:
    direct = DIRECT.read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    assert compiled_schema().validate(etree.fromstring(adapted))
    return adapted


def test_complete_1892_biography_oracle() -> None:
    report = check(_candidate())
    assert report["direct_children"] == 662
    assert report["html_carriers"] == 7230
    assert report["chapters"] == 15
    assert report["links"] == 1378
    assert report["internal_links"] == 1373
    assert report["images"] == 10
    assert report["notes"] == 109


def test_oracle_rejects_text_link_and_target_mutations() -> None:
    root = etree.fromstring(_candidate())
    paragraph = next(root.find(TEI + "text").iter(TEI + "p"))
    paragraph.text = (paragraph.text or "") + " invented"
    with pytest.raises(ValueError, match="complete ordered source/TEI text"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "ref")).set("target", "#wrong")
    with pytest.raises(ValueError, match="ordered hyperlink targets"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    target = next(node for node in root.iter() if node.get(XML_ID) == "Page_1")
    target.set(XML_ID, "wrong-page")
    with pytest.raises(ValueError, match="source target IDs"):
        check(etree.tostring(root))


def test_oracle_rejects_image_caption_table_and_rule_mutations() -> None:
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "figDesc")).text = "wrong alternate description"
    with pytest.raises(ValueError, match="alternate text"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "figure")).set("corresp", "#wrong")
    with pytest.raises(ValueError, match="caption attachment"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "cell")).text = "wrong table value"
    with pytest.raises(ValueError, match="complete ordered source/TEI text|table cell"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "milestone")).set("unit", "wrong")
    with pytest.raises(ValueError, match="line-break or horizontal-rule positions"):
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
    assert result["image_support_members"] == 11
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
