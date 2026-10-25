"""Focused first-part fidelity and guarded-stage checks for bsb750 Vita abbatum."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tools import install_openmgh_bsb750_vita_abbatum as vita
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path


RECEIPT = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "openmgh-bsb750-vita-abbatum-stage-20260930-v3/stage-receipt.json"
)
RECEIPT_SHA256 = "70e77b85a4187f13a6d7a8dd4fa53f537f4d78ba8943091bac9ace0cc430bd43"
NOTICE_HOME = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "openmgh-vita-abbatum-dual-public-notice-20260930-v1"
)


def test_source_first_part_and_candidate_mutations() -> None:
    source_bytes, source = vita._source(vita.ROOT)
    work, acquisition = vita._context(vita.ROOT)
    candidate = vita._candidate(source, work)
    checked = vita._check(source_bytes, candidate, work, acquisition)
    assert checked["selected_c14n_sha256"] == vita.PART_C14N
    assert checked["source_sibling_parts"] == 2
    assert checked["line_count"] == 233

    changed = etree.fromstring(candidate)
    line = changed.xpath("//*[local-name()='body']//*[local-name()='lb']")[0]
    line.set("{http://www.w3.org/XML/1998/namespace}id", "changed")
    with pytest.raises(PipelineError, match="candidate differs"):
        vita._check(source_bytes, etree.tostring(changed), work, acquisition)

    omitted = etree.fromstring(candidate)
    body = omitted.xpath("//*[local-name()='body']")[0]
    body.remove(body[0])
    with pytest.raises(PipelineError, match="candidate differs"):
        vita._check(source_bytes, etree.tostring(omitted), work, acquisition)


def test_guard_requires_exact_receipt_pin() -> None:
    with pytest.raises(PipelineError, match="exact reviewed stage receipt hash changed"):
        vita.preflight(RECEIPT, "0" * 64)
    assert vita._sha(RECEIPT) == RECEIPT_SHA256


def test_dual_edition_future_public_notice_binding(tmp_path: Path) -> None:
    index = json.loads(_io_path(NOTICE_HOME / "notice-index.json").read_bytes())
    assert len(index["editions"]) == 2
    for origin, relative in (
        (vita.ROOT / index["source_path"], index["source_path"]),
        (NOTICE_HOME / index["notice_path"], index["notice_path"]),
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(origin), target)
    selected = {"work_id": vita.WORK_ID, "public_notices": [{
        key: index[key] for key in
        ("source_path", "source_sha256", "notice_path", "notice_sha256")
    }]}
    for edition in index["editions"]:
        original = (vita.ROOT / "library/works" / vita.WORK_ID / "forms" /
                    vita.FORM_ID / "editions" / edition["edition_id"] / "acceptance.json")
        acceptance = tmp_path / f"{edition['edition_id']}.json"
        shutil.copy2(_io_path(original), acceptance)
        notices = notice_texts_for_item(tmp_path, selected, acceptance)
        assert len(notices) == 1 and "bsb00000750" in notices[0] and "bsb00000754" in notices[0]
    notice_path = tmp_path / index["notice_path"]
    notice_path.write_text(notice_path.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, selected, acceptance)
