"""Complete HTML, hymn, link, and frozen-stage checks for Gerhardt PG30362."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.gerhardt_pg30362_native import DIRECT, DIRECT_SHA256, adapt
from build.tei.gerhardt_pg30362_oracle import check
from build.tools import install_gerhardt_pg30362 as installer
from build.tools.install_gerhardt_pg30362 import preflight
from tests.frozen_install_preimages import copy_recorded_preimage, copy_stage_dependencies
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files
from build.tools.stage_gerhardt_pg30362 import ADAPTED_SHA256
from ocd_kernel.tei.validate import compiled_schema


TEI = "{http://www.tei-c.org/ns/1.0}"


def _candidate() -> bytes:
    direct = DIRECT.read_bytes()
    assert sha256(direct).hexdigest() == DIRECT_SHA256
    adapted = adapt(direct)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    assert compiled_schema().validate(etree.fromstring(adapted))
    return adapted


def test_complete_kelly_1867_gerhardt_oracle() -> None:
    report = check(_candidate())
    assert report["selected_direct_children"] == 10
    assert report["headings"] == 97
    assert report["hymns"] == 74
    assert report["hyperlink_targets"] == 125
    assert report["first_line_labels"] == 94


def test_oracle_rejects_text_heading_and_link_mutations() -> None:
    root = etree.fromstring(_candidate())
    paragraph = next(root.find(TEI + "text").iter(TEI + "p"))
    paragraph.text = (paragraph.text or "") + " invented"
    with pytest.raises(ValueError, match="complete ordered source/TEI text"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "head")).text = "Wrong hymn"
    with pytest.raises(ValueError, match="complete ordered source/TEI text|heading/hymn sequence"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "ref")).set("target", "#wrong")
    with pytest.raises(ValueError, match="hyperlink targets"):
        check(etree.tostring(root))


def test_oracle_rejects_index_and_cover_role_mutations() -> None:
    root = etree.fromstring(_candidate())
    next(root.iter(TEI + "label")).tag = TEI + "seg"
    with pytest.raises(ValueError, match="first-line index labels"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    etree.SubElement(root.find(TEI + "text").find(TEI + "body")[0], TEI + "graphic", url="30362-cover.png")
    with pytest.raises(ValueError, match="cover role"):
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
    assert result["image_support_members"] == result["package_support_members"] == 1
    assert result["native_rows"] == 1


def test_current_accepted_generation_rejects_frozen_preimage() -> None:
    import json
    record = json.loads((installer.STAGE / "stage-receipt.json").read_bytes())
    before = _files(installer.ROOT / installer.WORK)
    assert before != record["before"]
    with pytest.raises(PipelineError, match="current preimage or staged work generation differs"):
        preflight()
    assert _files(installer.ROOT / installer.WORK) == before
