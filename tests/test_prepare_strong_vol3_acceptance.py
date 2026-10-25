"""Focused preparation-only Strong Volume 3 acceptance tests."""

from datetime import datetime, timezone
import hashlib
import json

import pytest

from build.tools import prepare_strong_vol3_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


def test_prepare_existing_v9_handoff_in_fresh_stage(tmp_path_factory):
    stage_parent = tmp_path_factory.mktemp("s")
    stage = stage_parent / "s"
    receipt_before = (helper.ROOT / helper.RECEIPT).read_bytes()
    canonical_before = {
        relative: (helper.ROOT / relative).read_bytes()
        for relative in (helper.WORK / "work.json", helper.WORK / "state.json", helper.ACQUISITION)
    }
    started = datetime.now(timezone.utc)
    acceptance = helper.prepare(helper.ROOT, stage)
    finished = datetime.now(timezone.utc)
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / helper.WORK / "integration/strong-vol3-pg45283-v9-agent-handoff"

    original = (evidence / "inputs/package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()
    assert hashlib.sha256(original).hexdigest() == helper.TEI_SHA
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert record["promotion"]["status"] == "pending"
    assert record["decision"]["agent_assessment"]["status"] == "accepted"
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assert record["review"]["coverage"]["status"] == "partial"
    assert record["review"]["coverage"]["inspected"] == ["opening", "middle", "ending"]
    assert not (stage / helper.EDITION / "master.tei.xml").exists()
    assert (helper.ROOT / helper.RECEIPT).read_bytes() == receipt_before
    for relative, content in canonical_before.items():
        assert (helper.ROOT / relative).read_bytes() == content
    assert (stage / helper.TICKET).read_bytes() == (evidence / "inputs/ticket.md").read_bytes()
    assert (stage / helper.REPORT).read_bytes() == (evidence / "inputs/report.md").read_bytes()
    assessed_at = datetime.fromisoformat(
        record["decision"]["agent_assessment"]["assessed_at"].replace("Z", "+00:00")
    )
    assert started <= assessed_at <= finished
    closure = json.loads((evidence / "closure.json").read_bytes())
    for name in ("ticket.md", "report.md", "receipt.json", "validation.json",
                 "cvw/opening/frame.png", "cvw/middle/frame.png", "cvw/ending/frame.png"):
        binding = closure["details"]["evidence_files"][name]
        content = (evidence / "inputs" / name).read_bytes()
        assert binding["bytes"] == len(content)
        assert binding["sha256"] == hashlib.sha256(content).hexdigest()

    promoted = promote_accepted_master(
        stage, acceptance_path=acceptance, destination=stage_parent / "p"
    )
    promoted_record = validate_acceptance(
        promoted.acceptance_path, root=promoted.destination_root
    )
    validate_state(promoted.state_path, root=promoted.destination_root)
    promoted_state = json.loads(promoted.state_path.read_bytes())
    assert promoted_record["promotion"]["status"] == "promoted"
    assert promoted_record["decision"]["human_decision"]["status"] == "not-recorded"
    assert promoted_state["targets"][0]["stage"] == "accepted"
    assert promoted.master_path.is_file()
    assert (helper.ROOT / helper.RECEIPT).read_bytes() == receipt_before
    for relative, content in canonical_before.items():
        assert (helper.ROOT / relative).read_bytes() == content


def test_preserved_receipt_transcription_must_match_before_stage(tmp_path, monkeypatch):
    original_read = helper._read

    def changed_receipt(path, expected=None):
        content = original_read(path, expected)
        if path == helper.ROOT / helper.RECEIPT:
            receipt = json.loads(content)
            receipt["technical_completion_continuation_20260920"]["route"][
                "profile_sha256"
            ] = helper.PROFILE_SHA
            return json.dumps(receipt).encode("utf-8")
        return content

    monkeypatch.setattr(helper, "_read", changed_receipt)
    stage = tmp_path / "strong-stage"
    with pytest.raises(PipelineError, match="receipt digest transcription"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()