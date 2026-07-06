"""Tests for build/tools/update_review_state.py writer CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools import update_review_state as cli  # noqa: E402
from build.lib import review_state  # noqa: E402


def _write_record(record_path: Path, *, rid: str) -> None:
    record_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": {"id": rid}, "data": []}
    record_path.write_text(json.dumps(payload), encoding="utf-8")


def test_dismiss_creates_sidecar_and_audit(tmp_path: Path):
    repo = tmp_path / "repo"
    record = repo / "data" / "reference" / "schaff-herzog-encyclopedia.json"
    _write_record(record, rid="schaff-herzog-encyclopedia")

    rc = cli.main(
        [
            "--repo-root", str(repo),
            "dismiss",
            "--record", str(record),
            "--entry", "schaff-herzog.theotokos",
            "--producer", "ocr_scanner",
            "--code", "digit_in_letter",
            "--signature", "sig-1",
            "--reason", "false_positive",
            "--reviewer", "tester",
            "--parser-version", "build/parsers/ia_schaff_herzog.py@v1.0.0",
        ]
    )
    assert rc == 0

    sidecar_path = repo / "review" / "state" / "reference" / "schaff-herzog-encyclopedia.json"
    assert sidecar_path.exists()
    loaded = review_state.load_sidecar(sidecar_path)
    entry = loaded["entries"]["schaff-herzog.theotokos"]
    assert entry["warnings_dismissed"][0]["producer"] == "ocr_scanner"
    assert entry["warnings_dismissed"][0]["code"] == "digit_in_letter"
    assert entry["last_reviewer"] == "tester"

    audit_path = repo / "review" / "audit.jsonl"
    assert audit_path.exists()
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event_type"] == "dismiss"
    assert events[-1]["warning_signature"] == "sig-1"


def test_acknowledge_after_dismiss_moves_decision_bucket(tmp_path: Path):
    repo = tmp_path / "repo"
    record = repo / "data" / "reference" / "schaff-herzog-encyclopedia.json"
    _write_record(record, rid="schaff-herzog-encyclopedia")

    sub = [
        "--record", str(record),
        "--entry", "schaff-herzog.theotokos",
        "--producer", "ocr_scanner",
        "--code", "digit_in_letter",
        "--signature", "sig-1",
        "--reviewer", "tester",
        "--parser-version", "build/parsers/ia_schaff_herzog.py@v1.0.0",
    ]
    assert cli.main(["--repo-root", str(repo), "dismiss", *sub, "--reason", "false_positive"]) == 0
    assert cli.main(["--repo-root", str(repo), "acknowledge", *sub, "--reason", "confirmed"]) == 0

    sidecar = review_state.load_sidecar(
        repo / "review" / "state" / "reference" / "schaff-herzog-encyclopedia.json"
    )
    entry = sidecar["entries"]["schaff-herzog.theotokos"]
    assert entry["warnings_dismissed"] == []
    assert entry["warnings_acknowledged"][0]["reason"] == "confirmed"


def test_refuses_old_schema_sidecar(tmp_path: Path):
    repo = tmp_path / "repo"
    record = repo / "data" / "reference" / "schaff-herzog-encyclopedia.json"
    _write_record(record, rid="schaff-herzog-encyclopedia")
    sidecar_path = repo / "review" / "state" / "reference" / "schaff-herzog-encyclopedia.json"
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_type": "review_state",
                "schema_version": "0.9.0",  # older than current
                "record_path": "data/reference/schaff-herzog-encyclopedia.json",
                "record_resource_id": "schaff-herzog-encyclopedia",
                "record_checksum_sha256": "0" * 64,
                "parser_version_seen": "build/parsers/foo.py@v1.0.0",
                "confidence": {
                    "structural_fidelity": "unverified",
                    "text_fidelity": "unverified",
                    "edition_provenance": "unverified",
                },
                "entries": {},
                "dead_letter": [],
            }
        ),
        encoding="utf-8",
    )
    rc = cli.main(
        [
            "--repo-root", str(repo),
            "dismiss",
            "--record", str(record),
            "--entry", "x",
            "--producer", "p",
            "--code", "c",
            "--signature", "s",
            "--reason", "false_positive",
            "--reviewer", "tester",
        ]
    )
    assert rc == 3  # sidecar_schema_too_old


def test_set_confidence_axis_requires_promote_for_reference_grade(tmp_path: Path):
    repo = tmp_path / "repo"
    record = repo / "data" / "reference" / "schaff-herzog-encyclopedia.json"
    _write_record(record, rid="schaff-herzog-encyclopedia")
    head = ["--repo-root", str(repo), "set-confidence-axis"]
    sub = [
        "--record", str(record),
        "--axis", "text_fidelity",
        "--reviewer", "tester",
        "--parser-version", "build/parsers/ia_schaff_herzog.py@v1.0.0",
    ]
    assert cli.main([*head, *sub, "--tier", "human-reviewed"]) == 0
    # Without --promote: reference-grade refused.
    assert cli.main([*head, *sub, "--tier", "reference-grade"]) == 5
    # With --promote: accepted.
    assert cli.main([*head, *sub, "--tier", "reference-grade", "--promote"]) == 0
    sidecar = review_state.load_sidecar(
        repo / "review" / "state" / "reference" / "schaff-herzog-encyclopedia.json"
    )
    assert sidecar["confidence"]["text_fidelity"] == "reference-grade"


def test_dismiss_replaces_existing_decision_idempotently(tmp_path: Path):
    repo = tmp_path / "repo"
    record = repo / "data" / "reference" / "schaff-herzog-encyclopedia.json"
    _write_record(record, rid="schaff-herzog-encyclopedia")
    head = ["--repo-root", str(repo), "dismiss"]
    sub = [
        "--record", str(record),
        "--entry", "schaff-herzog.theotokos",
        "--producer", "ocr_scanner",
        "--code", "digit_in_letter",
        "--signature", "sig-1",
        "--reviewer", "tester",
        "--parser-version", "build/parsers/ia_schaff_herzog.py@v1.0.0",
    ]
    assert cli.main([*head, *sub, "--reason", "false_positive"]) == 0
    assert cli.main([*head, *sub, "--reason", "wont_fix"]) == 0
    sidecar = review_state.load_sidecar(
        repo / "review" / "state" / "reference" / "schaff-herzog-encyclopedia.json"
    )
    decisions = sidecar["entries"]["schaff-herzog.theotokos"]["warnings_dismissed"]
    assert len(decisions) == 1
    assert decisions[0]["reason"] == "wont_fix"
