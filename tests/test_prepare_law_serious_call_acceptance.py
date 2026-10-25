"""Preparation-only acceptance regression for the current CCEL Law witness."""

from datetime import datetime, timezone
import hashlib
import json

import pytest

from tests.retained_handoff_runtime_fixture import (
    assert_original_handoff_is_currently_rejected, current_handoff_context,
)

from build.tools import prepare_law_serious_call_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


def test_current_manifest_handoff_promotes_only_in_external_fixture(tmp_path, current_handoff):
    stage = tmp_path / "law-stage"
    canonical_before = {
        path: (helper.ROOT / path).read_bytes()
        for path in (helper.WORK / "work.json", helper.WORK / "state.json", helper.ACQUISITION)
    }
    old_before = (helper.OLD / "package/manifest.json").read_bytes()
    started = datetime.now(timezone.utc)
    acceptance = helper.prepare(helper.ROOT, stage)
    finished = datetime.now(timezone.utc)
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / helper.WORK / "integration/ccel-thml-current-manifest-agent-handoff"
    package = json.loads((evidence / "current-candidate/package/manifest.json").read_bytes())
    validation = json.loads((evidence / "current-candidate/validation.json").read_bytes())
    review = json.loads((evidence / "review.json").read_bytes())
    original = (evidence / "current-candidate/package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()

    assert package["source_manifest"]["sha256"] == helper.MANIFEST_SHA
    assert validation["source_manifest_sha256"] == helper.MANIFEST_SHA
    assert validation["candidate_sha256"] != helper.OLD_PACKAGE_SHA
    assert hashlib.sha256(original).hexdigest() == helper.TEI_SHA
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert review["no_new_pixel_review"] is True
    assert "different hashes" in review["applicability"]
    assert record["scope"]["declared"] == helper.SCOPE
    assert record["decision"]["agent_assessment"]["status"] == "accepted"
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assert record["review"]["coverage"]["status"] == "partial"
    assert len(record["review"]["coverage"]["inspected"]) == 12
    assessed = datetime.fromisoformat(
        record["decision"]["agent_assessment"]["assessed_at"].replace("Z", "+00:00")
    )
    assert started <= assessed <= finished
    assert not (stage / helper.EDITION / "master.tei.xml").exists()

    promoted = promote_accepted_master(
        stage, acceptance_path=acceptance, destination=tmp_path / "promoted"
    )
    promoted_record = validate_acceptance(
        promoted.acceptance_path, root=promoted.destination_root
    )
    validate_state(promoted.state_path, root=promoted.destination_root)
    assert promoted.master_sha256 == hashlib.sha256(derived).hexdigest()
    assert promoted_record["promotion"]["status"] == "promoted"
    assert promoted_record["decision"]["human_decision"]["status"] == "not-recorded"
    assert json.loads(promoted.state_path.read_bytes())["targets"][0]["stage"] == "accepted"
    assert (helper.OLD / "package/manifest.json").read_bytes() == old_before
    for path, content in canonical_before.items():
        assert (helper.ROOT / path).read_bytes() == content


def test_drifted_historical_frame_fails_before_stage(tmp_path, monkeypatch, current_handoff):
    original_read = helper._read

    def changed_frame(path, expected=None):
        content = original_read(path, expected)
        if path.name == "01-title-page.png":
            return content + b"drift"
        return content

    monkeypatch.setattr(helper, "_read", changed_frame)
    stage = tmp_path / "law-stage"
    with pytest.raises(PipelineError, match="recorded PNG"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()




@pytest.fixture
def current_handoff(tmp_path, monkeypatch):
    with current_handoff_context(helper, 'law-serious-call', tmp_path / "runtime", monkeypatch):
        yield


def test_original_handoff_remains_conserved_and_currently_rejected(tmp_path):
    assert_original_handoff_is_currently_rejected(helper, 'law-serious-call', tmp_path / "original-stage")
