"""Focused bsb754 Vita abbatum source, sibling, guard, and notice tests."""

from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb754_vita_abbatum_oracle import check_candidate
from build.tools import install_openmgh_bsb754_vita_abbatum as installer
from build.tools import prepare_openmgh_bsb754_vita_abbatum as source
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[1]
NOTICE_HOME = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-vita-abbatum-dual-public-notice-20260930-v1")


def _candidate() -> tuple[bytes, bytes, dict, dict]:
    retained, tree = source._source(source.ROOT)
    work, acquisition, *_ = source._work(source.ROOT)
    return retained, source._candidate(tree, work), work, acquisition


def test_complete_native_work_and_distinct_bsb750_edition() -> None:
    retained, candidate, work, acquisition = _candidate()
    checked = check_candidate(retained, candidate, work, acquisition)
    assert checked["source_work_index"] == 11
    assert checked["source_volume_works"] == 20
    assert checked["line_count"] == 181
    assert checked["source_page_count"] == 8
    assert checked["source_end_id"] == "bsb00000754_00346_5"
    other = (source.ROOT / "library/works" / source.WORK_ID / "forms" /
             source.FORM_ID / "editions" / source.OTHER_EDITION_ID)
    assert "master.tei.xml" in _files(other)
    assert sha256(_io_path(other / "acquisitions" /
                           f"{source.WORK_ID}-bsb00000750-acquired.json").read_bytes()).hexdigest() == source.OTHER_ACQUISITION_SHA256


def test_oracle_rejects_changed_native_node_and_missing_work() -> None:
    retained, candidate, work, acquisition = _candidate()
    parsed = etree.fromstring(candidate)
    line = parsed.xpath("//*[local-name()='body']//*[local-name()='lb']")[0]
    line.set("{http://www.w3.org/XML/1998/namespace}id", "changed")
    with pytest.raises(ValueError, match="candidate native whole work changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition)
    parsed = etree.fromstring(candidate)
    body = parsed.xpath("//*[local-name()='body']")[0]
    body.remove(body[0])
    with pytest.raises(ValueError, match="candidate native whole work changed"):
        check_candidate(retained, etree.tostring(parsed), work, acquisition)


def test_read_only_guard_and_pin_rejection() -> None:
    receipt, digest = installer._receipt(source.WORK_ID)
    assert digest == installer.RECEIPT_SHA256
    master = (ROOT / "library/works" / source.WORK_ID / "forms" / source.FORM_ID /
              "editions" / source.EDITION_ID / "master.tei.xml")
    assert sha256(_io_path(master).read_bytes()).hexdigest() == "45a3b85edf85686524bb35acdbf8408ea72523e34c4805b37c7590de506c27f0"
    with pytest.raises(PipelineError, match="exact stage receipt hash changed"):
        installer.preflight(receipt, expected_receipt_sha256="0" * 64)


def test_future_notice_binding_rejects_mutation(tmp_path: Path) -> None:
    index = json.loads(_io_path(NOTICE_HOME / "notice-index.json").read_bytes())
    assert {item["edition_id"] for item in index["editions"]} == {source.EDITION_ID, source.OTHER_EDITION_ID}
    for original, relative in ((ROOT / index["source_path"], index["source_path"]),
                               (NOTICE_HOME / index["notice_path"], index["notice_path"])):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(original), target)
    acceptance_source = (ROOT / "library/works" / source.WORK_ID / "forms" /
                         source.FORM_ID / "editions" / source.EDITION_ID / "acceptance.json")
    acceptance = tmp_path / "acceptance.json"
    shutil.copy2(_io_path(acceptance_source), acceptance)
    binding = {key: index[key] for key in
               ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    selected = {"work_id": source.WORK_ID, "public_notices": [binding]}
    texts = notice_texts_for_item(tmp_path, selected, acceptance)
    assert len(texts) == 1 and "bsb00000754" in texts[0]
    (tmp_path / index["notice_path"]).write_text(texts[0] + "changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, selected, acceptance)
