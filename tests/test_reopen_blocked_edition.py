from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path

import pytest

from ocd_kernel.lib.atomic_io import LockAcquireTimeout, acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import reopen_blocked_edition


@pytest.fixture
def blocked(tmp_path: Path):
    work = tmp_path / "library/works/example"
    edition = work / "forms/example-form/editions/example-edition"
    edition.mkdir(parents=True)
    (work / "work.json").write_text(json.dumps({
        "schema_version": "2.0", "work_id": "example", "title": "Example", "evidence": ["review.json"],
        "textual_forms": [{"textual_form_id": "example-form", "editions": [
            {"edition_id": "example-edition", "title": "Example edition"},
            {"edition_id": "other-edition", "title": "Other edition"},
        ]}],
    }), encoding="utf-8")
    state = {"schema_version": "2.0", "work_id": "example", "targets": [
        {"target_id": "example-edition", "target_type": "edition", "stage": "blocked",
         "updated_at": "2026-10-08T00:00:00Z", "reason": "Historical OS denial.", "evidence": ["work.json"]},
        {"target_id": "other-edition", "target_type": "edition", "stage": "acquired",
         "updated_at": "2026-10-08T00:00:00Z", "evidence": ["work.json"]},
    ]}
    path = work / "state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    (work / "review.json").write_text("{}", encoding="utf-8")
    return tmp_path, work, edition, path, state


def reopen(blocked, **overrides):
    root, _work, _edition, path, _state = blocked
    arguments = dict(work_id="example", edition_id="example-edition",
                     expected_state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                     reason="Reopened for a guarded attempt; OS cause remains unproved.",
                     evidence=["review.json"])
    arguments.update(overrides)
    return reopen_blocked_edition(root, **arguments)


def test_reopening_retains_blocker_evidence_and_other_targets(blocked):
    result = reopen(blocked)
    target = result["targets"][0]
    assert target["stage"] == "review"
    assert target["reason"].startswith(blocked[4]["targets"][0]["reason"] + "\n")
    assert target["evidence"] == ["work.json", "review.json"]
    assert result["targets"][1] == blocked[4]["targets"][1]
    assert target["updated_at"] != blocked[4]["targets"][0]["updated_at"]


@pytest.mark.parametrize("failure", ["stale", "stage", "master", "acceptance", "evidence", "schema"])
def test_reopening_rejects_unsafe_inputs_without_state_mutation(blocked, failure):
    _root, _work, edition, path, state = blocked
    overrides = {}
    if failure == "stale":
        overrides["expected_state_sha256"] = "0" * 64
    elif failure == "stage":
        state["targets"][0]["stage"] = "review"
        path.write_text(json.dumps(state), encoding="utf-8")
    elif failure in {"master", "acceptance"}:
        (edition / ("master.tei.xml" if failure == "master" else "acceptance.json")).write_text("{}", encoding="utf-8")
    elif failure == "evidence":
        overrides["evidence"] = ["missing.json"]
    else:
        state["targets"][0]["unexpected"] = True
        path.write_text(json.dumps(state), encoding="utf-8")
    before = path.read_bytes()
    messages = {"stale": "preimage", "stage": "blocked edition", "master": "installed master",
                "acceptance": "installed master", "evidence": "missing files", "schema": "unexpected"}
    with pytest.raises(PipelineError, match=messages[failure]):
        reopen(blocked, **overrides)
    assert path.read_bytes() == before


def test_reopening_honors_installer_work_lock(blocked, monkeypatch):
    import ocd_kernel.library.state as state_module
    monkeypatch.setattr(state_module, "acquire_jsonl_lock", lambda path: acquire_jsonl_lock(path, acquire_timeout=0.01))
    before = blocked[3].read_bytes()
    with acquire_jsonl_lock(blocked[1]):
        with pytest.raises(LockAcquireTimeout):
            reopen(blocked)
    assert blocked[3].read_bytes() == before


def test_reopening_atomic_failure_retains_previous_bytes(blocked, monkeypatch):
    import ocd_kernel.lib.atomic_io as atomic
    def denied(_source, _target):
        raise PermissionError("simulated atomic replacement denial")
    monkeypatch.setattr(atomic, "_replace_with_retry", denied)
    before = blocked[3].read_bytes()
    with pytest.raises(PermissionError, match="simulated"):
        reopen(blocked)
    assert blocked[3].read_bytes() == before
    assert not list(blocked[1].glob("state.json.tmp-*"))


def test_reopening_enables_existing_guard_without_weakening_it(blocked):
    from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON
    from ocd_kernel.tei.install_accepted import _validate_state_transition
    root, work, _edition, _path, initial = blocked
    source = root / "promoted"
    source.mkdir()
    bindings = {"example-edition": ("master.tei.xml", "acceptance.json")}
    accepted = copy.deepcopy(initial)
    accepted["targets"][0].update(stage="accepted", reason=PROMOTED_MASTER_REASON)
    accepted["targets"][0]["evidence"].extend(bindings["example-edition"])
    (source / "state.json").write_text(json.dumps(accepted), encoding="utf-8")
    with pytest.raises(PipelineError, match="existing state target"):
        _validate_state_transition(work, source, existed=True, replacement=False,
                                   accepted_evidence_by_edition=bindings)
    accepted = reopen(blocked)
    accepted["targets"][0].update(stage="accepted", reason=PROMOTED_MASTER_REASON)
    accepted["targets"][0]["evidence"].extend(bindings["example-edition"])
    (source / "state.json").write_text(json.dumps(accepted), encoding="utf-8")
    _validate_state_transition(work, source, existed=True, replacement=False,
                               accepted_evidence_by_edition=bindings)
