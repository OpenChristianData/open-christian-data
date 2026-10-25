"""Bounded acceptance handoff for the exact current Conscience witness."""

import hashlib
import json

import pytest

from tests.retained_handoff_runtime_fixture import (
    assert_original_handoff_is_currently_rejected, current_handoff_context,
)

from build.tools import prepare_owen_conscience_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


def test_exact_witness_stages_and_promotes(tmp_path, current_handoff):
    stage = tmp_path / "stage"
    acceptance = helper.prepare(helper.ROOT, stage)
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / helper.WORK / "integration/ccel-electronic-witness-agent-handoff"
    original = (evidence / "inputs/package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()
    review = json.loads((evidence / "review.json").read_text(encoding="utf-8"))

    assert hashlib.sha256(original).hexdigest() == helper.TEI_SHA
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert record["promotion"]["status"] == "pending"
    assert record["decision"]["agent_assessment"]["status"] == "accepted"
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assert record["scope"]["included_members"][0]["scope"] == helper.SCOPE
    assert len(review["screenshot_bindings"]) == 21
    assert review["no_new_pixel_review"] is True
    assert not (stage / helper.EDITION / "master.tei.xml").exists()

    promoted = promote_accepted_master(stage, acceptance_path=acceptance,
                                       destination=tmp_path / "promoted")
    promoted_record = validate_acceptance(promoted.acceptance_path, root=promoted.destination_root)
    validate_state(promoted.state_path, root=promoted.destination_root)
    assert promoted_record["promotion"]["status"] == "promoted"
    assert promoted_record["decision"]["human_decision"]["status"] == "not-recorded"
    assert promoted.master_sha256 == hashlib.sha256(derived).hexdigest()


def test_changed_review_frame_fails_before_staging(tmp_path, monkeypatch, current_handoff):
    original_read = helper._read

    def changed_frame(path, expected=None):
        if path.name == "01-dii-iiv.png":
            return original_read(path, "0" * 64)
        return original_read(path, expected)

    monkeypatch.setattr(helper, "_read", changed_frame)
    stage = tmp_path / "stage"
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()




@pytest.fixture
def current_handoff(tmp_path, monkeypatch):
    with current_handoff_context(helper, 'john-owen-conscience', tmp_path / "runtime", monkeypatch):
        yield


def test_original_handoff_remains_conserved_and_currently_rejected(tmp_path):
    assert_original_handoff_is_currently_rejected(helper, 'john-owen-conscience', tmp_path / "original-stage")


@pytest.mark.parametrize("work_id", ("john-owen-conscience", "augustine-on-christian-doctrine"))
def test_handoff_work_uses_declared_held_bytes_and_rejects_drift(tmp_path, work_id):
    from pathlib import Path
    from tests import retained_handoff_runtime_fixture as runtime

    repository = Path(__file__).resolve().parents[1]
    case = runtime.CASES[work_id]
    raw = (repository / case["runtime"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == case["runtime_sha256"]
    record = json.loads(raw)
    binding = next(item for item in record["authorities"] if item["name"] == "work")
    held = tmp_path / binding["path"]
    held.parent.mkdir(parents=True)
    original = (repository / binding["path"]).read_bytes()
    held.write_bytes(original)
    logical = Path("library/works") / work_id / "work.json"
    assert runtime._handoff_work_bytes(tmp_path, logical, record) == original
    held.write_bytes(original + b"\n")
    with pytest.raises(AssertionError, match="handoff work authority drifted"):
        runtime._handoff_work_bytes(tmp_path, logical, record)
