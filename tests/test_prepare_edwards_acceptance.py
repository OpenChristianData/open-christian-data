"""Focused preparation contract for the exact Edwards CCEL witness."""

import hashlib
import json

import pytest

from build.tools import prepare_edwards_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


def test_prepare_and_promote_fixture(tmp_path_factory):
    stage_parent = tmp_path_factory.mktemp("e")
    stage = stage_parent / "s"
    canonical = {path: (helper.ROOT / path).read_bytes()
                 for path in (helper.WORK / "work.json", helper.WORK / "state.json", helper.ACQUISITION)}
    old = (helper.CANDIDATE / "package/manifest.json").read_bytes()
    acceptance = helper.prepare(helper.ROOT, stage)
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / helper.WORK / "integration/ccel-thml-agent-handoff"
    original = (evidence / "inputs/package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()
    review = json.loads((evidence / "review.json").read_bytes())

    assert hashlib.sha256(original).hexdigest() == helper.TEI_SHA
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert record["promotion"]["status"] == "pending"
    assert record["decision"]["agent_assessment"]["status"] == "accepted"
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assert record["review"]["coverage"]["status"] == "partial"
    assert record["review"]["coverage"]["inspected"] == ["segment-0", "segment-1", "segment-2", "segment-18", "segment-19"]
    assert len(record["review"]["coverage"]["unreviewed"]) == 15
    assert review["no_new_pixel_review"] is True
    assert not (stage / helper.EDITION / "master.tei.xml").exists()

    promoted = promote_accepted_master(stage, acceptance_path=acceptance,
                                       destination=stage_parent / "p")
    promoted_record = validate_acceptance(promoted.acceptance_path, root=promoted.destination_root)
    validate_state(promoted.state_path, root=promoted.destination_root)
    assert promoted_record["promotion"]["status"] == "promoted"
    assert promoted_record["decision"]["human_decision"]["status"] == "not-recorded"
    assert json.loads(promoted.state_path.read_bytes())["targets"][0]["stage"] == "accepted"
    assert (helper.CANDIDATE / "package/manifest.json").read_bytes() == old
    for path, content in canonical.items():
        assert (helper.ROOT / path).read_bytes() == content


def test_changed_visual_frame_fails_before_staging(tmp_path, monkeypatch):
    original_read = helper._read

    def changed_frame(path, expected=None):
        if path.name == "frame.png" and path.parent.name.endswith("cvw-opening"):
            return original_read(path, "0" * 64)
        return original_read(path, expected)

    monkeypatch.setattr(helper, "_read", changed_frame)
    stage = tmp_path / "stage"
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()
