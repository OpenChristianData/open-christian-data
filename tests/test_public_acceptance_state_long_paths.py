"""Public validator regressions for deep Windows work and evidence paths."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library import state as state_module
from ocd_kernel.tei import acceptance as acceptance_module

ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "bernald-avoiding-communion-with-excommunicates"
WORK_ROOT = ROOT / "library" / "works" / WORK_ID
EDITION_ID = "bernald-avoiding-communion-with-excommunicates-openmgh-electronic"
ACCEPTANCE = (
    WORK_ROOT
    / "forms/bernald-avoiding-communion-with-excommunicates-openmgh-retained"
    / "editions"
    / EDITION_ID
    / "acceptance.json"
)
STATE = WORK_ROOT / "state.json"
AUGUSTINE_WORK_ID = "augustine-confessions"
AUGUSTINE_ACCEPTANCE = (
    ROOT
    / "library/works/augustine-confessions/forms/augustine-confessions-ccel-npnf101-retained-en"
    / "editions/augustine-confessions-ccel-npnf101-electronic/acceptance.json"
)


def test_installed_bernald_public_acceptance_and_state_with_ordinary_paths() -> None:
    assert io_path(ACCEPTANCE).is_file()
    assert acceptance_module.validate_acceptance(ACCEPTANCE, root=ROOT)["identity"]["work_id"] == WORK_ID
    assert state_module.validate_state(STATE, root=ROOT)["work_id"] == WORK_ID


@pytest.mark.parametrize("mutation", ["wrong-hash", "missing-file"])
def test_public_acceptance_rejects_changed_candidate_binding(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    original = acceptance_module.load_acceptance(ACCEPTANCE)
    changed = deepcopy(original)
    candidate = changed["technical"]["candidate"]
    if mutation == "wrong-hash":
        candidate["sha256"] = "0" * 64
        expected = "technical.candidate sha256 mismatch"
    else:
        candidate["path"] = candidate["path"] + ".missing"
        expected = "technical.candidate does not resolve to a file"
    monkeypatch.setattr(acceptance_module, "load_acceptance", lambda _path: changed)
    with pytest.raises(PipelineError, match=expected):
        acceptance_module.validate_acceptance(ACCEPTANCE, root=ROOT)


def test_installed_augustine_public_acceptance_binds_retained_source() -> None:
    record = acceptance_module.validate_acceptance(AUGUSTINE_ACCEPTANCE, root=ROOT)
    assert record["identity"]["work_id"] == AUGUSTINE_WORK_ID
    assert record["source"]["source_path"] == "raw/ccel/npnf1/npnf101.xml"


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("source_path", "acceptance source source_path does not bind acquisition"),
        ("source_sha256", "acceptance source source_sha256 does not bind acquisition"),
        ("source_bytes", "acceptance source source_bytes does not bind acquisition"),
        ("source_scope", "acceptance source source_scope does not bind acquisition"),
        ("manifest_sha256", "source.source_manifest sha256 mismatch"),
        ("manifest_path", "acceptance source manifest path does not bind acquisition"),
    ],
)
def test_public_acceptance_rejects_augustine_source_mapping_mutations(
    monkeypatch: pytest.MonkeyPatch, mutation: str, expected: str
) -> None:
    changed = deepcopy(acceptance_module.load_acceptance(AUGUSTINE_ACCEPTANCE))
    source = changed["source"]
    if mutation == "source_path":
        source["source_path"] += ".missing"
    elif mutation == "source_sha256":
        source["source_sha256"] = "0" * 64
    elif mutation == "source_bytes":
        source["source_bytes"] += 1
    elif mutation == "source_scope":
        source["source_scope"] += " Changed scope."
    elif mutation == "manifest_sha256":
        source["source_manifest"]["sha256"] = "0" * 64
    else:
        source["source_manifest"]["path"] += ".missing"
    monkeypatch.setattr(acceptance_module, "load_acceptance", lambda _path: changed)
    with pytest.raises(PipelineError, match=expected):
        acceptance_module.validate_acceptance(AUGUSTINE_ACCEPTANCE, root=ROOT)


def test_public_state_rejects_missing_master_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    original = state_module.load_state(STATE)
    changed = deepcopy(original)
    target = next(item for item in changed["targets"] if item["target_id"] == EDITION_ID)
    target["evidence"] = [reference for reference in target["evidence"] if not reference.endswith("master.tei.xml")]
    monkeypatch.setattr(state_module, "load_state", lambda _path: changed)
    with pytest.raises(PipelineError, match="evidence does not bind its master"):
        state_module.validate_state(STATE, root=ROOT)


def test_deep_fixture_file_binding_and_mutations(tmp_path: Path) -> None:
    directory = tmp_path / ("a" * 75) / ("b" * 75) / ("c" * 75)
    path = directory / "candidate.tei.xml"
    assert len(str(path)) > 260
    io_path(directory).mkdir(parents=True)
    io_path(path).write_bytes(b"candidate")
    reference = path.relative_to(tmp_path).as_posix()
    binding = {"path": reference, "bytes": 9, "sha256": hashlib.sha256(b"candidate").hexdigest()}
    assert acceptance_module._binding(tmp_path, binding, field="technical.candidate", fixture_only=True) == path.resolve()
    with pytest.raises(PipelineError, match="technical.candidate sha256 mismatch"):
        acceptance_module._binding(tmp_path, {**binding, "sha256": "0" * 64}, field="technical.candidate", fixture_only=True)
    with pytest.raises(PipelineError, match="technical.candidate does not resolve to a file"):
        acceptance_module._binding(tmp_path, {**binding, "path": reference + ".missing"}, field="technical.candidate", fixture_only=True)
    with pytest.raises(PipelineError, match="must be a relative path"):
        acceptance_module._binding(tmp_path, {**binding, "path": "../outside.txt"}, field="technical.candidate", fixture_only=True)
    outside = tmp_path.parent / "outside.txt"
    outside.write_bytes(b"candidate")
    alias = tmp_path / "outside-alias.txt"
    try:
        alias.symlink_to(outside)
    except (OSError, NotImplementedError):
        pass  # Some Windows hosts prohibit creating test symlinks.
    else:
        with pytest.raises(PipelineError, match="escapes fixture root"):
            acceptance_module._binding(tmp_path, {**binding, "path": alias.name}, field="technical.candidate", fixture_only=True)
