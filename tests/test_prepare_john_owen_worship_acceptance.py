"""Bounded acceptance handoff for Owen's exact CCEL Worship witness."""

import hashlib
import json

import pytest

from build.tools import prepare_john_owen_worship_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


def test_exact_witness_prepares_and_promotes_without_changing_members(tmp_path_factory):
    stage_parent = tmp_path_factory.mktemp("o")
    stage = stage_parent / "s1"
    acceptance = helper.prepare(helper.ROOT, stage)
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / helper.WORK / "integration/ccel-thml-agent-handoff"
    original = (evidence / "inputs/package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()

    assert hashlib.sha256(original).hexdigest() == helper.TEI_SHA
    assert (
        original.split(b"</ns0:teiHeader>", 1)[1]
        == derived.split(b"</ns0:teiHeader>", 1)[1]
    )
    assert record["promotion"]["status"] == "pending"
    assert record["decision"]["agent_assessment"]["status"] == "accepted"
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assert record["review"]["coverage"]["inspected"] == list(helper.LOCI)
    assert record["review"]["coverage"]["status"] == "partial"
    assert not (stage / helper.EDITION / "master.tei.xml").exists()

    promoted = promote_accepted_master(
        stage, acceptance_path=acceptance, destination=stage_parent / "p"
    )
    promoted_record = validate_acceptance(
        promoted.acceptance_path, root=promoted.destination_root
    )
    validate_state(promoted.state_path, root=promoted.destination_root)
    assert promoted_record["promotion"]["status"] == "promoted"
    assert promoted_record["decision"]["human_decision"]["status"] == "not-recorded"
    assert (
        json.loads(promoted.state_path.read_bytes())["targets"][0]["stage"]
        == "accepted"
    )
    assert (
        helper.ROOT / helper.WORK / "state.json"
    ).read_bytes() != promoted.state_path.read_bytes()


def test_stale_package_member_fails_before_stage(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(helper, "TEI_SHA", "0" * 64)
    stage_parent = tmp_path_factory.mktemp("o")
    stage = stage_parent / "s2"
    with pytest.raises(PipelineError, match="ticket no longer binds"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()


def test_header_binding_refuses_changed_reviewed_member():
    original = (helper.CANDIDATE / "package/content.tei.xml").read_bytes()
    source = dict(
        source_bytes=841339, source_url="https://www.ccel.org/ccel/owen/worship.html"
    )
    revision = dict(
        id="owen-worship-ccel-thml-agent-v1", date="2026-09-25", note="test"
    )
    with pytest.raises(PipelineError, match="reviewed Owen Worship TEI differs"):
        helper._bind_corpus_header(original + b" ", source, revision)


def test_changed_visual_frame_fails_before_stage(tmp_path_factory, monkeypatch):
    original_read = helper._read

    def changed_frame(path, expected=None):
        if path.name == "frame.png" and path.parent.name == "01-title-page":
            return original_read(path, "0" * 64)
        return original_read(path, expected)

    monkeypatch.setattr(helper, "_read", changed_frame)
    stage_parent = tmp_path_factory.mktemp("o")
    stage = stage_parent / "s3"
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()
