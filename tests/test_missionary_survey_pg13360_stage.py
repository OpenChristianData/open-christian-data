"""Focused source-line and guarded-stage checks for the exact PG13360 witness."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree
import pytest

from build.tei.missionary_survey_pg13360_native import adapt
from build.tei.missionary_survey_pg13360_oracle import check
from build.tools.install_missionary_survey_pg13360 import preflight
from build.tools.stage_missionary_survey_pg13360 import ADAPTED_SHA256, DIRECT, ORIGINAL_SHA256


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _candidate() -> bytes:
    original = (DIRECT / "candidate.tei.xml").read_bytes()
    assert sha256(original).hexdigest() == ORIGINAL_SHA256
    adapted = adapt(original)
    assert sha256(adapted).hexdigest() == ADAPTED_SHA256
    return adapted


def test_complete_source_stream_and_native_roles() -> None:
    report = check(_candidate())
    assert report["source_line_carriers"] == 4095
    assert report["fixed_width_table_blocks"] == 76
    assert report["chapter_count"] == 11
    assert report["before_start_lines"] == 27
    assert report["after_end_lines"] == 350


def test_oracle_rejects_one_changed_source_line() -> None:
    root = etree.fromstring(_candidate())
    carrier = root.xpath("//tei:seg[@type='source-line']", namespaces=NS)[100]
    carrier.text = (carrier.text or "") + " invented"
    with pytest.raises(ValueError, match="source-line mismatch"):
        check(etree.tostring(root))


def test_oracle_rejects_table_orientation_or_title_role_loss() -> None:
    root = etree.fromstring(_candidate())
    table = root.xpath("//tei:ab[@rend='fixed-width project-gutenberg-orientation']", namespaces=NS)[0]
    table.attrib.pop("rend")
    with pytest.raises(ValueError, match="table count/orientation"):
        check(etree.tostring(root))
    root = etree.fromstring(_candidate())
    role = root.xpath("/tei:TEI/tei:text/tei:front/tei:div[@type='title-page']/tei:ab", namespaces=NS)[1]
    role.set("subtype", "author")
    with pytest.raises(ValueError, match="title-page semantic roles"):
        check(etree.tostring(root))


def test_frozen_stage_passes_read_only_preflight() -> None:
    import json
    from hashlib import sha256
    from build.tools import install_missionary_survey_pg13360 as frozen_installer
    from ocd_kernel.library._common import PipelineError as FrozenPreimageError
    from ocd_kernel.tei.install_accepted import _files as frozen_files

    raw = (frozen_installer.STAGE / "stage-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "a9cb9eef32871a6e580096a1e7dc249ed6c22632f2356473ef3b17d9e9899f02"
    record = json.loads(raw)
    before = frozen_files(frozen_installer.ROOT / frozen_installer.WORK)
    assert frozen_files(frozen_installer.STAGE / frozen_installer.WORK) == record["after"]
    if before != record["before"]:
        with pytest.raises(FrozenPreimageError, match="PG13360 canonical preimage or frozen work generation differs"):
            frozen_installer.preflight()
        assert frozen_files(frozen_installer.ROOT / frozen_installer.WORK) == before
        return
    result = preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert result["native_rows"] == 16
