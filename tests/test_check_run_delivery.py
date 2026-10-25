from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from build.tools.check_run_delivery import main
from build.tools import check_run_delivery as delivery


def _write(path: Path, content: str = "fixture\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


@pytest.fixture
def delivery_fixture(tmp_path: Path) -> dict[str, Path | str]:
    repository = tmp_path / "repository"
    library = tmp_path / "library"
    repository.mkdir()
    for name in ("raw", "reports", "exports"):
        (library / name).mkdir(parents=True)
    (repository / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(library)}),
        encoding="utf-8",
    )
    ticket = repository / "plans" / "campaign" / "ticket.md"
    _write(ticket, "# Ticket\n")
    candidate = library / "candidate-reviews" / "run-1" / "candidate-1"
    for member in (
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    ):
        _write(candidate / "package" / member, "fixture\n")
    _write(candidate / "validation.json", "{}\n")
    evidence = library / "reports" / "runs" / "run-1"
    _write(evidence / "delivery.json", "{}\n")
    return {
        "repository": repository,
        "library": library,
        "ticket": "plans/campaign/ticket.md",
        "candidate": candidate,
        "evidence": "reports/runs/run-1",
    }


def _args(
    fixture: dict[str, Path | str],
    *,
    candidate: Path | None = None,
    evidence: str | None = None,
) -> list[str]:
    return [
        "--repository-root",
        str(fixture["repository"]),
        "--ticket",
        str(fixture["ticket"]),
        "--candidate-dir",
        str(candidate or fixture["candidate"]),
        "--evidence-dir",
        evidence or str(fixture["evidence"]),
    ]


def test_complete_delivery_is_reported_without_writes(
    delivery_fixture: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    before = _snapshot(delivery_fixture["repository"])
    before_library = _snapshot(delivery_fixture["library"])

    result = main(_args(delivery_fixture))
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload["contract"] == "ocd-run-delivery-check-v1"
    assert payload["status"] == "complete"
    assert payload["ticket"]["exists"] is True
    assert payload["candidate"]["shape"]["exact_outer_entries"] is True
    assert payload["candidate"]["package"]["exact_entries"] is True
    assert payload["candidate"]["package"]["flat"] is True
    assert payload["candidate"]["validation"] == {"exists": True, "file": True}
    assert payload["evidence"]["files"] == {"count": 1, "present": True}
    assert _snapshot(delivery_fixture["repository"]) == before
    assert _snapshot(delivery_fixture["library"]) == before_library


def test_missing_candidate_or_evidence_is_incomplete_without_creation(
    delivery_fixture: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    missing_candidate = delivery_fixture["library"] / "candidate-reviews" / "run-1" / "missing"
    missing_evidence = "reports/runs/missing"
    before = _snapshot(delivery_fixture["library"])

    result = main(
        _args(
            delivery_fixture,
            candidate=missing_candidate,
            evidence=missing_evidence,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert payload["status"] == "incomplete"
    assert payload["candidate"]["exists"] is False
    assert payload["evidence"]["exists"] is False
    assert not missing_candidate.exists()
    assert _snapshot(delivery_fixture["library"]) == before


def test_wrong_root_is_invalid_and_preserves_temporary_candidate(
    delivery_fixture: dict[str, Path | str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    temporary = tmp_path / "temporary-run" / "candidate"
    _write(temporary / "package" / "manifest.json", "{}\n")
    _write(temporary / "validation.json", "{}\n")
    before = _snapshot(tmp_path / "temporary-run")

    result = main(_args(delivery_fixture, candidate=temporary))
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["status"] == "invalid"
    assert "candidate-reviews" in payload["errors"][0]
    assert _snapshot(tmp_path / "temporary-run") == before


def test_candidate_shape_mismatch_is_invalid_without_repair(
    delivery_fixture: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    extra = delivery_fixture["candidate"] / "notes.md"
    _write(extra, "owned\n")
    before = _snapshot(delivery_fixture["candidate"])

    result = main(_args(delivery_fixture))
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["status"] == "invalid"
    assert payload["candidate"]["shape"]["exact_outer_entries"] is False
    assert extra.read_text(encoding="utf-8") == "owned\n"
    assert _snapshot(delivery_fixture["candidate"]) == before


def test_partial_package_is_invalid_without_repair(
    delivery_fixture: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    package = delivery_fixture["candidate"] / "package"
    (package / "content.tei.xml").unlink()
    before = _snapshot(delivery_fixture["candidate"])

    result = main(_args(delivery_fixture))
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["status"] == "invalid"
    assert payload["candidate"]["package"]["exact_entries"] is False
    assert _snapshot(delivery_fixture["candidate"]) == before


def test_direct_cli_reports_json_and_exit_code(
    delivery_fixture: dict[str, Path | str],
) -> None:
    tool = Path(__file__).parents[1] / "build" / "tools" / "check_run_delivery.py"
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(tool),
            *_args(delivery_fixture),
        ],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "complete"


def test_symlink_escape_is_invalid_when_supported(
    delivery_fixture: dict[str, Path | str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    outside = tmp_path / "outside-candidate"
    _write(outside / "package" / "manifest.json", "{}\n")
    _write(outside / "validation.json", "{}\n")
    escape = delivery_fixture["library"] / "candidate-reviews" / "run-1" / "escape"
    try:
        escape.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")
    before = _snapshot(outside)

    result = main(_args(delivery_fixture, candidate=escape))
    payload = json.loads(capsys.readouterr().out)

    assert result == 2
    assert payload["status"] == "invalid"
    assert _snapshot(outside) == before


def test_evidence_reparse_directory_is_rejected_before_descent(
    delivery_fixture: dict[str, Path | str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    alias = delivery_fixture["library"] / "reports" / "runs" / "run-1" / "alias"
    alias.mkdir()
    original_check = delivery._is_reparse_point
    original_iterdir = Path.iterdir

    def guarded_iterdir(path: Path):
        if path == alias:
            pytest.fail("delivery check descended into a reparse directory")
        return original_iterdir(path)

    monkeypatch.setattr(delivery, "_is_reparse_point", lambda path: path == alias or original_check(path))
    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)
    assert main(_args(delivery_fixture)) == 2
    assert json.loads(capsys.readouterr().out)["evidence"]["invalid_entries"] == ["alias"]


def test_repository_internal_library_is_not_external_delivery(
    delivery_fixture: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    repository = delivery_fixture["repository"]
    config = repository / ".ocd-storage.json"
    config.write_text(json.dumps({"library_root": str(repository / "internal-library")}), encoding="utf-8")
    before = _snapshot(repository)
    assert main(_args(delivery_fixture)) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"
    assert _snapshot(repository) == before


def test_required_member_directory_cannot_report_complete(
    delivery_fixture: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    member = delivery_fixture["candidate"] / "package" / "manifest.json"
    member.unlink()
    member.mkdir()
    assert main(_args(delivery_fixture)) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "invalid"
    assert result["candidate"]["package"]["invalid_entries"] == ["manifest.json"]
    assert member.is_dir()


def test_missing_storage_config_fails_closed(
    delivery_fixture: dict[str, Path | str], capsys: pytest.CaptureFixture[str]
) -> None:
    repository = delivery_fixture["repository"]
    (repository / ".ocd-storage.json").unlink()
    before = _snapshot(repository)
    assert main(_args(delivery_fixture)) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "invalid"
    assert "configured .ocd-storage.json is required" in result["errors"][0]
    assert _snapshot(repository) == before
