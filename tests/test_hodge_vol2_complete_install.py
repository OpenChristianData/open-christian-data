"""Focused scope and journaled rollback checks for the exact Volume II revision."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from build.tools import install_hodge_vol2_electronic_acceptance as installer
from ocd_kernel.library._common import PipelineError


def put(path, value):
    path = installer._io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value).encode() if not isinstance(value, bytes) else value)


def scope_fixture(tmp_path):
    root, staged = tmp_path / "root", tmp_path / "staged"
    acquisition = {"source_scope": "old parts", "retained_files": [{"scope": "old parts", "sha256": "retained"}], "provider": "CCEL"}
    state = {"targets": [{"target_id": installer.route.IDENTITY["edition_id"], "stage": "accepted", "reason": "old", "updated_at": "old", "evidence": ["unchanged"]}]}
    revised_acquisition = deepcopy(acquisition)
    revised_acquisition["source_scope"] = installer.complete_route.SCOPE
    revised_acquisition["retained_files"][0]["scope"] = installer.complete_route.SCOPE
    revised_state = deepcopy(state)
    revised_state["targets"][0].update(reason=installer.PROMOTED_MASTER_REASON, updated_at="new")
    for base, acq, target_state in ((root, acquisition, state), (staged, revised_acquisition, revised_state)):
        put(base / installer.ACQUISITION, acq)
        put(base / installer.WORK / "state.json", target_state)
    before = {installer.MASTER_REL.as_posix(): installer.OLD_MASTER_SHA,
              installer.ACCEPTANCE_REL.as_posix(): installer.OLD_ACCEPTANCE_SHA,
              installer.ACQUISITION_REL.as_posix(): "original-acquisition", "state.json": "old-state", "work.json": "unchanged"}
    after = dict(before)
    after.update({installer.MASTER_REL.as_posix(): installer.COMPLETE_MASTER_SHA, "state.json": "new-state",
                  installer.ACCEPTANCE_REL.as_posix(): "new-acceptance", installer.ACQUISITION_REL.as_posix(): "new-scope"})
    for name, digest in (("candidate.tei.xml", installer.COMPLETE_MASTER_SHA), ("previous-master.tei.xml", installer.OLD_MASTER_SHA),
                         ("previous-acceptance.json", installer.OLD_ACCEPTANCE_SHA), ("previous-acquisition.json", "original-acquisition")):
        after[(installer.COMPLETE_EVIDENCE / name).as_posix()] = digest
    return root, staged, before, after


def test_complete_scope_permits_only_the_frozen_volume_delta(tmp_path):
    root, staged, before, after = scope_fixture(tmp_path)
    installer.complete_scoped(root, staged, before, after)
    for path in ("work.json", "unrelated.txt"):
        altered = dict(after, **{path: "changed"})
        with pytest.raises(PipelineError, match="identity differs|unrelated authority"):
            installer.complete_scoped(root, staged, before, altered)
    changed = json.loads(installer._io_path(staged / installer.ACQUISITION).read_bytes())
    changed["provider"] = "invented provider"
    put(staged / installer.ACQUISITION, changed)
    with pytest.raises(PipelineError, match="two scope descriptions"):
        installer.complete_scoped(root, staged, before, after)


def test_stale_generation_is_rejected_before_mutation(tmp_path):
    root, pending, promoted = (tmp_path / name for name in ("root", "pending", "promoted"))
    for base in (root, pending, promoted):
        put(base / installer.WORK / "work.json", b"original")
    files = installer._files(root / installer.WORK)
    manifest = tmp_path / "receipt.json"
    put(manifest, {"contract": installer.COMPLETE_CONTRACT, "work_id": installer.route.WORK_ID,
        "canonical_root": str(root), "pending_root": str(pending), "promoted_root": str(promoted),
        "before": files, "pending": files, "after": files})
    put(root / installer.WORK / "work.json", b"changed after receipt")
    snapshot = installer._files(root / installer.WORK)
    with pytest.raises(PipelineError, match="receipt is stale"):
        installer.install(manifest)
    assert installer._files(root / installer.WORK) == snapshot
    assert not (root / "library/.sidecar-operations").exists()


@pytest.mark.parametrize("failure", ["after-copy", "after-old-rename", "after-new-rename", "after-validation", None])
def test_transaction_preserves_journal_and_exact_rollback(tmp_path, monkeypatch, failure):
    root, staged = tmp_path / "root", tmp_path / "staged"
    put(root / installer.WORK / "work.json", b"original generation")
    put(staged / installer.WORK / "work.json", b"new generation")
    put(staged / installer.WORK / installer.MASTER_REL, b"master")
    put(staged / installer.WORK / installer.ACCEPTANCE_REL, b"acceptance")
    before, after = installer._files(root / installer.WORK), installer._files(staged / installer.WORK)
    record = {"contract": installer.COMPLETE_CONTRACT, "before": before, "after": after, "external_dependencies": {}}
    manifest = tmp_path / "receipt.json"
    put(manifest, record)
    monkeypatch.setattr(installer, "preflight", lambda _: (record, root, staged))
    monkeypatch.setattr(installer, "outside_dependencies", lambda *args, **kwargs: {})
    monkeypatch.setattr(installer, "_validate_acceptance_for_work", lambda *args, **kwargs: None)
    monkeypatch.setattr(installer, "validate_state", lambda *args, **kwargs: None)

    def fail_at(phase):
        if phase == failure:
            raise RuntimeError("injected Volume II failure")

    if failure:
        with pytest.raises(RuntimeError, match="injected Volume II failure"):
            installer.install(manifest, fail_at=fail_at)
        assert installer._files(root / installer.WORK) == before
    else:
        result = installer.install(manifest)
        assert result["status"] == "installed-and-validated"
        assert installer._files(root / installer.WORK) == after
    journals = list((root / "library/.sidecar-operations").glob("h204-*/operation.json"))
    assert len(journals) == 1
    journal = json.loads(journals[0].read_bytes())
    assert journal["phase"] == ("complete" if failure is None else "failed-before-swap" if failure == "after-copy" else "rolled-back")
    assert journal["before"] == before and journal["after"] == after


def test_external_dependency_drift_is_rejected_under_lock(tmp_path, monkeypatch):
    root, staged = tmp_path / "root", tmp_path / "staged"
    put(root / installer.WORK / "work.json", b"original")
    put(staged / installer.WORK / "work.json", b"new")
    before = installer._files(root / installer.WORK)
    record = {"contract": installer.COMPLETE_CONTRACT, "before": before,
              "after": installer._files(staged / installer.WORK), "external_dependencies": {"source": "old"}}
    monkeypatch.setattr(installer, "preflight", lambda _: (record, root, staged))
    monkeypatch.setattr(installer, "outside_dependencies", lambda *args, **kwargs: {"source": "changed"})
    with pytest.raises(PipelineError, match="changed while acquiring lock"):
        installer.install(tmp_path / "receipt.json")
    assert installer._files(root / installer.WORK) == before
    assert not (root / "library/.sidecar-operations").exists()
