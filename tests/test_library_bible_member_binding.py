"""Focused regression seams for retained Bible member-set accounting."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from tests.historical_sidecar_packet_fixture import historical_packet_context

from build.tools.library_bible_member_binding import bind_bible_members
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "plans/2026-09-22-source-preflight/five-bible-member-sidecar-packet-20260926.json"
EVIDENCE = ROOT / "plans/2026-09-22-source-preflight/five-bible-member-evidence-20260926.json"


def test_five_bible_packet_uses_all_extracted_text_and_no_zip_as_text() -> None:
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert len(packet["entries"]) == len(evidence["entries"]) == 5
    assert sum(len(entry["textual_members"]) for entry in evidence["entries"]) == 904
    for row, entry in zip(packet["entries"], evidence["entries"], strict=True):
        assert row["work_id"] == entry["work_id"]
        assert row["primary_sources"] == entry["textual_members"]
        assert entry["package"]["path"].endswith(".zip")
        assert all(not member["path"].endswith(".zip") for member in row["primary_sources"])
        assert len(entry["archive_members"]) >= len(entry["textual_members"]) + len(entry["support_members"])


def test_bible_binding_rejects_changed_url_before_staging(tmp_path: Path) -> None:
    root = historical_packet_context(ROOT, tmp_path / "repo", "bible-two")
    row = copy.deepcopy(json.loads(PACKET.read_text(encoding="utf-8"))["entries"][0])
    work = json.loads((root / row["work"]["path"]).read_text(encoding="utf-8"))
    row["url"] = "https://example.invalid/changed"
    with pytest.raises(PipelineError, match="URL or warnings differ"):
        bind_bible_members(root, row, work)


def test_bible_binding_rejects_zip_as_primary(tmp_path: Path) -> None:
    root = historical_packet_context(ROOT, tmp_path / "repo", "bible-two")
    row = copy.deepcopy(json.loads(PACKET.read_text(encoding="utf-8"))["entries"][4])
    work = json.loads((root / row["work"]["path"]).read_text(encoding="utf-8"))
    row["primary_sources"][0]["path"] = "raw/ebible/eng-web/usfm/eng-web_usfm.zip"
    with pytest.raises(PipelineError, match="textual member list differs"):
        bind_bible_members(root, row, work)
