"""Origo's future data README is bound to the retained MGH/BSB source note."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from build.tools import prepare_openmgh_bsb754_origo_public_notice as notice
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path


def test_origo_future_public_notice_binding(tmp_path: Path) -> None:
    index_path = notice.HOME / "notice-index.json"
    index = json.loads(_io_path(index_path).read_bytes())
    assert index["freeze_sha256"] == notice.FREEZE_SHA
    assert len(index["items"]) == 1
    item = index["items"][0]
    assert item["work_id"] == notice.WORK_ID
    assert item["notice_path"] == "data/structured-text/origo-francorum/README.md"
    note = _io_path(notice.ROOT / item["source_path"]).read_bytes()
    data_readme = _io_path(notice.HOME / item["notice_path"]).read_bytes()
    assert sha256(note).hexdigest() == item["source_sha256"]
    assert sha256(data_readme).hexdigest() == item["notice_sha256"]
    assert b"Monumenta Germaniae Historica" in data_readme
    assert b"Bavarian State Library" in data_readme
    for relative, content in ((item["source_path"], note), (item["notice_path"], data_readme)):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps({"identity": {"work_id": notice.WORK_ID}}), encoding="utf-8")
    selected = {key: item[key] for key in ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    request = {"work_id": notice.WORK_ID, "public_notices": [selected]}
    assert len(notice_texts_for_item(tmp_path, request, acceptance)) == 1
    (tmp_path / item["notice_path"]).write_text("# Altered notice\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, request, acceptance)
