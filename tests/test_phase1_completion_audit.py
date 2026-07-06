from __future__ import annotations

import json
import os
import subprocess as _real_subprocess
from pathlib import Path

import pytest


MANIFEST_TEST_PATHS = [
    "tests/test_adr0013_calibration_gate.py",
    "tests/test_reconcile_status.py",
    "tests/test_review_patch_round_trip.py",
    "tests/test_render_review_html.py",
]

# Epoch timestamps used in ordering tests to avoid same-second races.
_TS_EARLY = "2000-01-01T00:00:00+00:00"
_TS_LATE = "2000-01-02T00:00:00+00:00"


def _write_manifest(path: Path, test_paths: list[str], slot: int = 13) -> None:
    entries = "\n".join(f"  - path: {test_path}\n    slot: {slot}" for test_path in test_paths)
    path.write_text(f"version: 1\ngenerated_for_slot: 13\ntests:\n{entries}\n", encoding="utf-8")


def _build_repo(tmp_path: Path, commit_subjects: dict[str, str]) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _real_subprocess.run(["git", "init"], cwd=repo, check=True)
    _real_subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    _real_subprocess.run(["git", "config", "user.name", "Fixture Author"], cwd=repo, check=True)
    _real_subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)

    for test_path in MANIFEST_TEST_PATHS:
        file_path = repo / test_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("def test_fixture_placeholder():\n    assert True\n", encoding="utf-8")
        _real_subprocess.run(["git", "add", test_path], cwd=repo, check=True)
        _real_subprocess.run(
            ["git", "commit", "-m", commit_subjects.get(test_path, "test(audit): RED fixture")],
            cwd=repo,
            check=True,
        )

    manifest_path = tmp_path / "section-8-test-manifest.yaml"
    _write_manifest(manifest_path, MANIFEST_TEST_PATHS)
    return repo, manifest_path


def _stub_subprocess(pytest_returncode: int = 0, reviewer_clean: bool = True):
    def selective_stub(cmd: list[str], **kwargs: object) -> _real_subprocess.CompletedProcess[str]:
        if "-m" in cmd and "pytest" in cmd:
            return _real_subprocess.CompletedProcess(cmd, returncode=pytest_returncode)
        if any("reconcile_status.py" in str(part) for part in cmd):
            return _real_subprocess.CompletedProcess(
                cmd,
                returncode=0,
                stdout=json.dumps({"reviewer_clean": reviewer_clean}),
                stderr="",
            )
        return _real_subprocess.run(cmd, **kwargs)

    return selective_stub


def _load_last_json(captured_output: str) -> dict[str, object]:
    return json.loads(captured_output.strip().splitlines()[-1])


@pytest.mark.slow
def test_phase1_completion_audit_replays_both_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        from build.tools.phase1_completion_audit import main
    except ImportError as exc:
        pytest.fail(f"build.tools.phase1_completion_audit is not importable: {exc!r}")

    result = main(["--json"])
    assert isinstance(result, int)
    capsys.readouterr()

    pass_repo, pass_manifest_path = _build_repo(tmp_path / "pass_case", {})
    monkeypatch.chdir(pass_repo)
    monkeypatch.setattr("build.tools.phase1_completion_audit.subprocess.run", _stub_subprocess())

    result = main(["--json", "--manifest", str(pass_manifest_path)])
    output = _load_last_json(capsys.readouterr().out)

    assert result == 0
    assert output["tdd_conformance"] == "pass"
    assert output["adr0013_calibration"] == "pass"
    assert output["schaff_herzog_reviewer_clean"] == "pass"
    assert output["pass"] is True

    offending_path = MANIFEST_TEST_PATHS[1]
    fail_repo, fail_manifest_path = _build_repo(
        tmp_path / "fail_case",
        {offending_path: "feat(something): not RED"},
    )
    monkeypatch.chdir(fail_repo)
    monkeypatch.setattr("build.tools.phase1_completion_audit.subprocess.run", _stub_subprocess())

    result = main(["--json", "--manifest", str(fail_manifest_path)])
    output = _load_last_json(capsys.readouterr().out)

    assert result != 0
    assert output["tdd_conformance"] == "fail"
    assert output["pass"] is False
    assert isinstance(output["failing_paths"], list)
    assert offending_path in output["failing_paths"]

    result = main(["--json", "--manifest", str(tmp_path / "nonexistent.yaml")])
    assert result != 0
    capsys.readouterr()

    schaff_fail_repo, schaff_fail_manifest_path = _build_repo(tmp_path / "schaff_fail_case", {})
    monkeypatch.chdir(schaff_fail_repo)
    monkeypatch.setattr(
        "build.tools.phase1_completion_audit.subprocess.run",
        _stub_subprocess(reviewer_clean=False),
    )

    result = main(["--json", "--manifest", str(schaff_fail_manifest_path)])
    output = _load_last_json(capsys.readouterr().out)

    assert result != 0
    assert output["schaff_herzog_reviewer_clean"] == "fail"
    assert output["pass"] is False


def test_empty_manifest_tdd_gate_fails() -> None:
    """A1-D02: empty test_paths must return fail, not a vacuous pass."""
    from build.tools.phase1_completion_audit import _gate_tdd_conformance

    status, failing = _gate_tdd_conformance([])
    assert status == "fail"
    assert failing == []


def _init_repo(repo: Path) -> None:
    _real_subprocess.run(["git", "init"], cwd=repo, check=True)
    _real_subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    _real_subprocess.run(["git", "config", "user.name", "Fixture Author"], cwd=repo, check=True)
    _real_subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)


def _commit_file(repo: Path, rel_path: str, subject: str, timestamp: str) -> None:
    file_path = repo / rel_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("# fixture\n", encoding="utf-8")
    env = {**os.environ, "GIT_COMMITTER_DATE": timestamp, "GIT_AUTHOR_DATE": timestamp}
    _real_subprocess.run(["git", "add", rel_path], cwd=repo, check=True)
    _real_subprocess.run(["git", "commit", "-m", subject], cwd=repo, check=True, env=env)


def test_production_ordering_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1-D01: test committed before production file — ordering check passes."""
    from build.tools.phase1_completion_audit import _gate_tdd_conformance

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "tests/test_adr0013_calibration_gate.py", "test(slot-4): RED", _TS_EARLY)
    _commit_file(repo, "build/tools/calibration_report.py", "feat(slot-4): add calibration", _TS_LATE)

    monkeypatch.chdir(repo)
    slot_map = {"tests/test_adr0013_calibration_gate.py": 4}
    status, failing = _gate_tdd_conformance(
        ["tests/test_adr0013_calibration_gate.py"], slot_map=slot_map
    )
    assert status == "pass", f"Expected pass but got fail: {failing}"
    assert failing == []


def test_production_ordering_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1-D01: production committed before test file — ordering check fails."""
    from build.tools.phase1_completion_audit import _gate_tdd_conformance

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    # Production committed first — TDD violation
    _commit_file(repo, "build/tools/calibration_report.py", "feat(slot-4): add calibration", _TS_EARLY)
    _commit_file(repo, "tests/test_adr0013_calibration_gate.py", "test(slot-4): RED", _TS_LATE)

    monkeypatch.chdir(repo)
    slot_map = {"tests/test_adr0013_calibration_gate.py": 4}
    status, failing = _gate_tdd_conformance(
        ["tests/test_adr0013_calibration_gate.py"], slot_map=slot_map
    )
    assert status == "fail"
    assert "tests/test_adr0013_calibration_gate.py" in failing
