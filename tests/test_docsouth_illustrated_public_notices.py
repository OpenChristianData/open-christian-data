"""Frozen September 28 DocSouth notices stay source-bound and release-safe."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tools import prepare_docsouth_illustrated_public_notices as notices
from ocd_kernel.library._common import PipelineError
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.tei.install_accepted import _io_path
from tests.openmgh_historical_fixture import (
    DOCSOUTH_RIGHTS_APPENDIX as _CURRENT_RIGHTS_APPENDIX,
    historical_docsouth_source_note as _frozen_source_note,
)


def _index() -> dict:
    return json.loads(_io_path(notices.HOME / "notice-index.json").read_bytes())


@pytest.mark.parametrize("with_appendix", [False, True])
def test_frozen_source_note_preserves_exact_prior_bytes(with_appendix: bool) -> None:
    original = b"Retained source rights and credits.\n"
    current = original + _CURRENT_RIGHTS_APPENDIX + b"Current rights remain qualified.\n" if with_appendix else original
    assert _frozen_source_note(current, sha256(original).hexdigest()) == original


@pytest.mark.parametrize("change", ["changed-prefix", "unknown-appendix", "duplicate-marker"])
def test_frozen_source_note_rejects_unproven_history(change: str) -> None:
    original = b"Retained source rights and credits.\n"
    if change == "changed-prefix":
        raw = original.replace(b"credits", b"changed credits") + _CURRENT_RIGHTS_APPENDIX + b"Current rights.\n"
    elif change == "unknown-appendix":
        raw = original + b"\n## Unrecognized later amendment\nCurrent rights.\n"
    else:
        raw = original + _CURRENT_RIGHTS_APPENDIX + _CURRENT_RIGHTS_APPENDIX
    with pytest.raises(ValueError, match="frozen notice-index preimage"):
        _frozen_source_note(raw, sha256(original).hexdigest())


def test_all_22_notices_bind_exact_source_rights_credits_and_file_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = _index()
    inventory = json.loads(_io_path(notices.INVENTORY).read_bytes())
    selected = {work["work_id"]: work for work in inventory["works"]
                if work["element_counts"].get("figure", 0) > 0}
    assert index["contract"] == notices.CONTRACT
    assert index["status"] == "future-release-notice-only"
    assert index["canonical_data_write"] == index["public_release"] == "not-performed"
    assert len(index["items"]) == index["selected_work_count"] == 22
    assert {item["work_id"] for item in index["items"]} == set(selected)
    assert sha256(_io_path(notices.INVENTORY).read_bytes()).hexdigest() == index["inventory_sha256"]

    # The frozen proposal predates current data notices; reconstruct its input-only context.
    original_root = notices.ROOT
    for item in index['items']:
        for relative in (item['source_path'], selected[item['work_id']]['source_path']):
            target = _io_path(tmp_path / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_io_path(original_root / relative).read_bytes())
    monkeypatch.setattr(notices, 'ROOT', tmp_path)
    rights_labels = {}
    for item in index["items"]:
        work_id = item["work_id"]
        source_note = _frozen_source_note(
            _io_path(notices.ROOT / item["source_path"]).read_bytes(), item["source_sha256"]
        )
        public_notice = _io_path(notices.HOME / item["notice_path"]).read_bytes()
        assert sha256(source_note).hexdigest() == item["source_sha256"]
        assert sha256(public_notice).hexdigest() == item["notice_sha256"]
        assert public_notice.endswith(b"\n") and b"raw/docsouth" not in public_notice
        assert not _io_path(notices.ROOT / item["notice_path"]).exists()
        source = etree.fromstring(_io_path(notices.ROOT / selected[work_id]["source_path"]).read_bytes())
        availability = source.find("teiHeader/fileDesc/publicationStmt/availability")
        assert availability is not None and availability.get("status") == "unknown"
        exact = "".join(availability.itertext())
        wording = " ".join(exact.split())
        assert sha256(exact.encode("utf-8")).hexdigest() == item["retained_rights_text_sha256"]
        assert wording in source_note.decode("utf-8") and wording in public_notice.decode("utf-8")
        for statement in source.findall("teiHeader/fileDesc/titleStmt/respStmt"):
            role = " ".join("".join(statement.find("resp").itertext()).split())
            name = " ".join("".join(statement.find("name").itertext()).split())
            assert f"- {role}: {name}" in public_notice.decode("utf-8")
        funder = source.find("teiHeader/fileDesc/titleStmt/funder")
        if funder is None:
            assert "- Funding:" not in public_notice.decode("utf-8")
        else:
            assert "- Funding: " + " ".join("".join(funder.itertext()).split()) in public_notice.decode("utf-8")
        rights_labels[work_id] = item["rights_label"]
    assert sum(label == "Copyright Not Evaluated." for label in rights_labels.values()) == 2
    assert rights_labels["thomas-l-johnson-twenty-eight-years-a-slave"] == "Copyright Not Evaluated."
    assert rights_labels["william-h-heard-from-slavery-to-bishopric"] == "Copyright Not Evaluated."


@pytest.mark.parametrize("work_id", [item["work_id"] for item in _index()["items"]])
def test_source_notice_and_future_data_readme_pass_release_binder(tmp_path: Path, work_id: str) -> None:
    item = next(item for item in _index()["items"] if item["work_id"] == work_id)
    for relative, content in (
        (item["source_path"], _frozen_source_note(
            _io_path(notices.ROOT / item["source_path"]).read_bytes(), item["source_sha256"]
        )),
        (item["notice_path"], _io_path(notices.HOME / item["notice_path"]).read_bytes()),
    ):
        target = _io_path(tmp_path / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(json.dumps({"identity": {"work_id": work_id}}), encoding="utf-8")
    binding = {key: item[key] for key in ("source_path", "source_sha256", "notice_path", "notice_sha256")}
    selected = {"work_id": work_id, "public_notices": [binding]}
    assert len(notice_texts_for_item(tmp_path, selected, acceptance)) == 1
    binding["notice_sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        notice_texts_for_item(tmp_path, selected, acceptance)
