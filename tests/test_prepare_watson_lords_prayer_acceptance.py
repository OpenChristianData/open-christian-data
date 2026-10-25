"""Focused exact-witness Watson Prayer acceptance checks."""

import hashlib
import json
from pathlib import Path
import shutil
import uuid

import pytest

from build.tools import prepare_watson_lords_prayer_acceptance as helper
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


@pytest.fixture(autouse=True)
def exact_historical_handoff_root(tmp_path, monkeypatch):
    original_root = helper.ROOT
    root = tmp_path / "watson-prayer-original-handoff"
    root.mkdir()
    (root / ".ocd-storage.json").write_bytes((original_root / ".ocd-storage.json").read_bytes())
    original_manifest = original_root / "tests/fixtures/reconstruction-runtime/authorities/watson-lords-prayer-acceptance-original.source-manifest.json"
    manifest_bytes = original_manifest.read_bytes()
    assert hashlib.sha256(manifest_bytes).hexdigest() == helper.MANIFEST_SHA
    manifest = json.loads(manifest_bytes)
    for relative in (helper.MANIFEST, helper.WORK / "work.json", helper.WORK / "state.json",
                     helper.ACQUISITION, helper.TICKET, helper.REPORT, helper.RECEIPT):
        if relative == helper.MANIFEST:
            content = manifest_bytes
        elif relative == helper.WORK / "work.json":
            content = (original_root / "tests/fixtures/reconstruction-runtime/authorities/watson-lords-prayer-original-bound-work.json").read_bytes()
        else:
            content = (original_root / relative).read_bytes()
        binding = next((item for item in manifest["authorities"] if item["path"] == relative.as_posix()), None)
        if binding is not None:
            assert hashlib.sha256(content).hexdigest() == binding["sha256"]
            assert len(content) == binding["bytes"]
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    monkeypatch.setattr(helper, "ROOT", root)
    yield



def test_prepare_and_promote_preserves_reviewed_text(tmp_path):
    short_root = Path("C:/tmp") if Path("C:/tmp").is_dir() else tmp_path
    owned = short_root / f"wlp-{uuid.uuid4().hex[:8]}"
    owned.mkdir()
    stage = owned / "s"
    try:
        acceptance = helper.prepare(helper.ROOT, stage)
        _assert_promoted(stage, acceptance, owned)
    finally:
        if owned.exists():
            assert owned.resolve().parent == short_root.resolve()
            assert not owned.is_symlink()
            shutil.rmtree(owned)


def _assert_promoted(stage, acceptance, owned):
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / helper.WORK / "integration/ccel-thml-agent-handoff"
    original = (evidence / "inputs/package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()
    account = json.loads((evidence / "source-accounting.json").read_bytes())
    review = json.loads((evidence / "review.json").read_bytes())

    assert hashlib.sha256(original).hexdigest() == helper.TEI_SHA
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert account["native_carriers"] == list(helper.NATIVE_IDS)
    assert set(review["capture_bindings"]) == {"opening", "middle", "ending"}
    assert record["promotion"]["status"] == "pending"
    assert record["decision"]["agent_assessment"]["status"] == "accepted"
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assert record["review"]["coverage"]["status"] == "partial"
    assert len(record["review"]["coverage"]["inspected"]) == 3

    promoted = promote_accepted_master(
        stage, acceptance_path=acceptance, destination=owned / "p"
    )
    promoted_record = validate_acceptance(
        promoted.acceptance_path, root=promoted.destination_root
    )
    validate_state(promoted.state_path, root=promoted.destination_root)
    assert promoted_record["promotion"]["status"] == "promoted"
    assert promoted_record["decision"]["human_decision"]["status"] == "not-recorded"
    assert promoted.master_path.read_bytes() == derived


def test_changed_review_frame_fails_before_staging(tmp_path, monkeypatch):
    original_read = helper._read

    def changed_frame(path, expected=None):
        if path.name == "frame.png" and path.parent.name == "opening":
            return original_read(path, "0" * 64)
        return original_read(path, expected)

    monkeypatch.setattr(helper, "_read", changed_frame)
    stage = tmp_path / "prayer-stage"
    with pytest.raises(PipelineError, match="SHA-256 mismatch"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()


def test_changed_source_envelope_fails_before_staging(tmp_path, monkeypatch):
    original_json = helper._json

    def changed_envelope(content, label):
        value = original_json(content, label)
        if label == "source accountability":
            value["source_envelope"] = value["source_envelope"][:-1]
        return value

    monkeypatch.setattr(helper, "_json", changed_envelope)
    stage = tmp_path / "prayer-stage"
    with pytest.raises(PipelineError, match="source envelope"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()


def test_changed_visual_source_identity_fails_before_staging(tmp_path, monkeypatch):
    original_json = helper._json

    def changed_compare(content, label):
        value = original_json(content, label)
        if label == "CVW compare opening":
            value["left"]["artifact"]["sha256"] = "0" * 64
        return value

    monkeypatch.setattr(helper, "_json", changed_compare)
    stage = tmp_path / "prayer-stage"
    with pytest.raises(PipelineError, match="visual compare differs from exact pair"):
        helper.prepare(helper.ROOT, stage)
    assert not stage.exists()


def test_historical_handoff_uses_exact_held_work_without_changing_current_metadata():
    original_root = Path(__file__).resolve().parents[1]
    held = original_root / "tests/fixtures/reconstruction-runtime/authorities/watson-lords-prayer-original-bound-work.json"
    held_raw = held.read_bytes()
    assert hashlib.sha256(held_raw).hexdigest() == "54b952e4f4b29056eba5e64a898e5609b9873adf9561468a22fa3c6024150ff8"
    assert (helper.ROOT / helper.WORK / "work.json").read_bytes() == held_raw
    assert (original_root / helper.WORK / "work.json").read_bytes() != held_raw
