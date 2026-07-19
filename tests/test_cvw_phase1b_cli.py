"""Public seam tests for the bounded ASV status CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cvw_phase1b import generate_bundle, generate_status, serialize_bundle, serialize_status
from cvw_phase1b.cli import main
from tests.test_cvw_phase1b_status import make_independent_repository


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_OWNERSHIP = REPO_ROOT / "cvw_phase1b" / "fixtures" / "asv_ownership.json"
LIVE_POLICY = REPO_ROOT / "cvw_phase1b" / "fixtures" / "asv_policy.json"
LIVE_SINGLE_FILE_OWNERSHIP = REPO_ROOT / "cvw_phase1b" / "fixtures" / "spurgeon_ownership.json"
LIVE_SINGLE_FILE_POLICY = REPO_ROOT / "cvw_phase1b" / "fixtures" / "spurgeon_policy.json"
LIVE_SINGLE_FILE_SOURCE = REPO_ROOT / "raw/ia/spurgeon_all_of_grace.txt"


@pytest.mark.requires_local_artifacts
def test_cli_json_is_the_public_deterministic_status_serializer(capsys) -> None:
    expected = generate_status(REPO_ROOT, LIVE_OWNERSHIP, LIVE_POLICY)

    result = main(
        [
            "--repository-root",
            str(REPO_ROOT),
            "--ownership",
            str(LIVE_OWNERSHIP),
            "--policy",
            str(LIVE_POLICY),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out.encode("utf-8") == serialize_status(expected)
    assert json.loads(captured.out)["comparison"]["state"] == "UNCOMPARED"


@pytest.mark.requires_local_artifacts
def test_cli_text_is_stable_and_discloses_bounded_status(capsys) -> None:
    result = main(
        [
            "--repository-root",
            str(REPO_ROOT),
            "--format",
            "text",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "state: UNCOMPARED",
        "scope: bounded (work=asv, rendering=asv:scrollmapper-json)",
        "counts: source_members=66 canonical_outputs=66 selected_source_members=3 selected_canonical_outputs=3",
        "publication: not_applicable",
        "changes: none",
    ]


@pytest.mark.skipif(
    not LIVE_SINGLE_FILE_SOURCE.is_file(),
    reason="ignored Spurgeon raw witness is unavailable",
)
def test_cli_json_projects_the_single_file_witness(capsys) -> None:
    result = main(
        [
            "--repository-root",
            str(REPO_ROOT),
            "--ownership",
            str(LIVE_SINGLE_FILE_OWNERSHIP),
            "--policy",
            str(LIVE_SINGLE_FILE_POLICY),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["scope"]["work_id"] == "spurgeon-all-of-grace"
    assert payload["counts"]["selected_anchors"] == {
        "source_members": 1,
        "canonical_outputs": 1,
    }
    assert payload["comparison"]["state"] == "UNCOMPARED"


def test_cli_stale_comparison_returns_one_and_invalid_input_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, ownership, policy = make_independent_repository(tmp_path)
    previous_path = root / "review/previous-bundle.json"
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    previous_path.write_bytes(serialize_bundle(generate_bundle(root, ownership, policy)))
    policy_payload = json.loads(policy.read_bytes())
    policy_payload["sample_size"] = 4
    policy.write_text(json.dumps(policy_payload, indent=2) + "\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    result = main(
        [
            "--repository-root",
            str(root),
            "--ownership",
            str(ownership),
            "--policy",
            str(policy),
            "--previous-bundle",
            str(previous_path),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == ""
    assert json.loads(captured.out)["comparison"]["state"] == "STALE"
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}

    previous_path.write_bytes(b'{"identity":"verification-bundle-v1","identity":"forged"}\n')
    result = main(
        [
            "--repository-root",
            str(root),
            "--ownership",
            str(ownership),
            "--policy",
            str(policy),
            "--previous-bundle",
            str(previous_path),
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "error:" in captured.err
