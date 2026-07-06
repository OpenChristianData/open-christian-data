from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import build.tools.verify_publish_provenance as provenance
from build.lib.matrix_snapshot import build_envelope, build_payload, write_snapshot
from build.tools.verify_publish_provenance import main, verify_release


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def make_release(
    tmp_path: Path,
    *,
    slim_token: dict | None = None,
    audit_token: dict | None = None,
    slim_artifacts: list[dict] | None = None,
    audit_artifacts: list[dict] | None = None,
) -> tuple[Path, Path, Path]:
    release_root = tmp_path / "release"
    artifact_path = release_root / "artifacts" / "reconciled-v1.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text('{"tokens":["alpha"]}', encoding="utf-8")

    base_artifact = {
        "path": "artifacts/reconciled-v1.json",
        "sha256": _sha256(artifact_path),
        "role": "reconciled",
        "audit_only": False,
    }
    slim_manifest = {
        "release_id": "schaff-vol01-r1",
        "config": "slim",
        "pinned_artifacts": slim_artifacts if slim_artifacts is not None else [base_artifact],
        "tokens": [
            slim_token
            if slim_token is not None
            else {
                "token_id": "t1",
                "output_status": "recognised_from_page",
                "published_as": "recognised_from_page",
            }
        ],
        "audit_manifest_path": "manifests/audit.json",
    }
    audit_manifest = {
        "release_id": "schaff-vol01-r1",
        "config": "audit",
        "pinned_artifacts": audit_artifacts if audit_artifacts is not None else [base_artifact],
        "tokens": [
            audit_token
            if audit_token is not None
            else {
                "token_id": "t1",
                "output_status": "recognised_from_page",
                "published_as": "recognised_from_page",
            }
        ],
    }

    slim_path = release_root / "manifests" / "slim.json"
    audit_path = release_root / "manifests" / "audit.json"
    _write_json(slim_path, slim_manifest)
    _write_json(audit_path, audit_manifest)
    return release_root, slim_path, audit_path


def _codes(result) -> set[str]:
    return {failure.code for failure in result.failures}


def _redirect_reports(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        provenance,
        "REPORT_JSON",
        tmp_path / "reports" / "publish" / "provenance_verification.json",
    )
    monkeypatch.setattr(
        provenance,
        "REPORT_MD",
        tmp_path / "reports" / "publish" / "provenance_verification.md",
    )


def test_happy_path_passes(tmp_path, monkeypatch):
    _redirect_reports(monkeypatch, tmp_path)
    release_root, slim_path, audit_path = make_release(tmp_path)

    result = verify_release(slim_path, audit_path, release_root)

    assert result.ok is True
    assert main(["--slim", str(slim_path), "--audit", str(audit_path), "--release-root", str(release_root)]) == 0


def test_missing_pinned_artifact_fails(tmp_path, monkeypatch):
    _redirect_reports(monkeypatch, tmp_path)
    release_root, slim_path, audit_path = make_release(tmp_path)
    (release_root / "artifacts" / "reconciled-v1.json").unlink()

    result = verify_release(slim_path, audit_path, release_root)

    assert "missing_artifact" in _codes(result)
    assert main(["--slim", str(slim_path), "--audit", str(audit_path), "--release-root", str(release_root)]) == 1


def test_hash_mismatch_fails(tmp_path):
    release_root, slim_path, audit_path = make_release(tmp_path)
    (release_root / "artifacts" / "reconciled-v1.json").write_text(
        '{"tokens":["corrupt"]}', encoding="utf-8"
    )

    result = verify_release(slim_path, audit_path, release_root)

    assert "hash_mismatch" in _codes(result)


def test_slim_referencing_audit_only_artifact_fails(tmp_path):
    release_root, slim_path, audit_path = make_release(tmp_path)
    slim_manifest = json.loads(slim_path.read_text(encoding="utf-8"))
    slim_manifest["pinned_artifacts"].append(
        {
            "path": "artifacts/reconciled-v1.json",
            "sha256": _sha256(release_root / "artifacts" / "reconciled-v1.json"),
            "role": "decisions",
            "audit_only": True,
        }
    )
    _write_json(slim_path, slim_manifest)

    result = verify_release(slim_path, audit_path, release_root)

    assert "audit_only_in_slim" in _codes(result)


def test_restored_text_marked_read_from_page_fails(tmp_path):
    release_root, slim_path, audit_path = make_release(
        tmp_path,
        audit_token={
            "token_id": "t1",
            "output_status": "restored_from_reference",
            "published_as": "restored_from_reference",
        },
    )

    result = verify_release(slim_path, audit_path, release_root)

    assert "restored_marked_recognised" in _codes(result)


def test_slim_token_without_audit_match_fails(tmp_path):
    # A slim token with no matching audit token has no provenance trail and must
    # not publish (Codex review finding 1).
    release_root, slim_path, audit_path = make_release(
        tmp_path,
        slim_token={
            "token_id": "t-orphan",
            "output_status": "recognised_from_page",
            "published_as": "recognised_from_page",
        },
        audit_token={
            "token_id": "t1",
            "output_status": "recognised_from_page",
            "published_as": "recognised_from_page",
        },
    )

    result = verify_release(slim_path, audit_path, release_root)

    assert "slim_token_not_in_audit" in _codes(result)


def test_audit_artifact_missing_for_slim_release_fails(tmp_path):
    release_root, slim_path, audit_path = make_release(tmp_path)
    audit_path.unlink()

    result = verify_release(slim_path, audit_path, release_root)

    assert "audit_artifact_missing" in _codes(result)


def test_relative_paths_canonicalize_inside_root(tmp_path):
    release_root, slim_path, audit_path = make_release(tmp_path)
    escape_path = release_root.parent / "escape.json"
    escape_path.write_text('{"outside":true}', encoding="utf-8")
    slim_manifest = json.loads(slim_path.read_text(encoding="utf-8"))
    slim_manifest["pinned_artifacts"][0] = {
        "path": "../escape.json",
        "sha256": _sha256(escape_path),
        "role": "reconciled",
        "audit_only": False,
    }
    _write_json(slim_path, slim_manifest)

    result = verify_release(slim_path, audit_path, release_root)

    assert "path_escapes_root" in _codes(result)


def test_tampered_matrix_snapshot_replay_fails(tmp_path):
    release_root, slim_path, audit_path = make_release(tmp_path)
    payload = build_payload(
        cells=[],
        ledger_tail_hash="tail",
        matrix_policy_version="weight-matrix-policy-v1",
        namespace={"work_id": "schaff_herzog"},
    )
    envelope = build_envelope(
        payload,
        created_at="2026-05-29T00:00:00Z",
        created_by="b17-test",
        events_covered_first="a",
        events_covered_last="b",
    )
    payload_path, envelope_path = write_snapshot(release_root, payload, envelope)
    payload_path.write_text('{"tampered":true}', encoding="utf-8")

    artifact = {
        "path": envelope_path.relative_to(release_root).as_posix(),
        "sha256": _sha256(envelope_path),
        "role": "matrix_snapshot",
        "audit_only": False,
    }
    slim_manifest = json.loads(slim_path.read_text(encoding="utf-8"))
    audit_manifest = json.loads(audit_path.read_text(encoding="utf-8"))
    slim_manifest["pinned_artifacts"] = [artifact]
    audit_manifest["pinned_artifacts"] = [artifact]
    _write_json(slim_path, slim_manifest)
    _write_json(audit_path, audit_manifest)

    result = verify_release(slim_path, audit_path, release_root)

    assert "replay_not_byte_identical" in _codes(result)
