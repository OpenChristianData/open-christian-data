from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from ocd_kernel.lib.atomic_io import write_json_atomic


ALLOWED_STATUSES = {
    "recognised_from_page",
    "restored_from_reference",
    "human_confirmed",
    "unresolved",
}
PRIVATE_STATUSES = {"restored_from_reference", "unresolved"}
REPORT_JSON = REPO_ROOT / "reports" / "publish" / "provenance_verification.json"
REPORT_MD = REPO_ROOT / "reports" / "publish" / "provenance_verification.md"
REPORT_SCHEMA = {
    "type": "object",
    "required": ["checked_at", "release_id", "ok", "failures"],
    "properties": {
        "checked_at": {"type": "string"},
        "release_id": {"type": "string"},
        "ok": {"type": "boolean"},
        "failures": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "detail"],
                "properties": {
                    "code": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class ProvenanceFailure:
    code: str
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    failures: list[ProvenanceFailure]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _inside_root(candidate: Path, root: Path) -> bool:
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _artifact_path(release_root: Path, artifact: dict[str, Any]) -> Path:
    return (release_root / str(artifact.get("path", ""))).resolve()


def _check_artifacts(
    manifest: dict[str, Any],
    *,
    manifest_label: str,
    release_root: Path,
    failures: list[ProvenanceFailure],
) -> None:
    root = release_root.resolve()
    for artifact in manifest.get("pinned_artifacts", []):
        relative_path = str(artifact.get("path", ""))
        resolved = _artifact_path(release_root, artifact)
        if not resolved.is_relative_to(root):
            failures.append(
                ProvenanceFailure(
                    "path_escapes_root",
                    f"{manifest_label} artifact path escapes release root: {relative_path}",
                )
            )
            continue
        if manifest.get("config") == "slim" and artifact.get("audit_only") is True:
            failures.append(
                ProvenanceFailure(
                    "audit_only_in_slim",
                    f"slim manifest references audit-only artifact: {relative_path}",
                )
            )
        if not resolved.exists():
            failures.append(
                ProvenanceFailure(
                    "missing_artifact",
                    f"{manifest_label} artifact is missing: {relative_path}",
                )
            )
            continue
        actual = sha256(resolved.read_bytes()).hexdigest()
        expected = str(artifact.get("sha256", ""))
        if actual != expected:
            failures.append(
                ProvenanceFailure(
                    "hash_mismatch",
                    f"{manifest_label} artifact hash mismatch for {relative_path}",
                )
            )
        if artifact.get("role") == "matrix_snapshot":
            try:
                from build.lib.matrix_snapshot import SnapshotIntegrityError, load_snapshot

                load_snapshot(resolved)
            except SnapshotIntegrityError as exc:
                failures.append(
                    ProvenanceFailure(
                        "replay_not_byte_identical",
                        f"matrix snapshot replay failed for {relative_path}: {exc}",
                    )
                )


def _check_token_statuses(
    manifest: dict[str, Any], manifest_label: str, failures: list[ProvenanceFailure]
) -> None:
    for token in manifest.get("tokens", []):
        token_id = str(token.get("token_id", "<missing>"))
        for field in ("output_status", "published_as"):
            value = token.get(field)
            if value not in ALLOWED_STATUSES:
                failures.append(
                    ProvenanceFailure(
                        "unknown_output_status",
                        f"{manifest_label} token {token_id} has unknown {field}: {value}",
                    )
                )


def _load_audit_manifest(
    slim_manifest: dict[str, Any],
    audit_manifest_path: Path | None,
    release_root: Path,
    failures: list[ProvenanceFailure],
) -> dict[str, Any] | None:
    named = slim_manifest.get("audit_manifest_path")
    if not named:
        failures.append(
            ProvenanceFailure("audit_artifact_missing", "slim manifest does not name an audit manifest")
        )
        return None

    named_path = (release_root / str(named)).resolve()
    root = release_root.resolve()
    if not named_path.is_relative_to(root):
        failures.append(
            ProvenanceFailure("audit_artifact_missing", "audit manifest path escapes release root")
        )
        return None

    selected_path = Path(audit_manifest_path).resolve() if audit_manifest_path is not None else named_path
    if selected_path != named_path:
        failures.append(
            ProvenanceFailure(
                "audit_artifact_missing",
                "audit manifest argument does not match slim audit_manifest_path",
            )
        )
        return None
    if not selected_path.exists():
        failures.append(
            ProvenanceFailure("audit_artifact_missing", "audit manifest is missing")
        )
        return None
    try:
        return _load_json(selected_path)
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(
            ProvenanceFailure("audit_artifact_missing", f"audit manifest could not be loaded: {exc}")
        )
        return None


def _check_provenance_integrity(
    slim_manifest: dict[str, Any],
    audit_manifest: dict[str, Any],
    failures: list[ProvenanceFailure],
) -> None:
    # Build the audit index, rejecting tokens with no id and duplicate ids: a
    # missing/duplicate audit id would let the slim-to-audit join below silently
    # match the wrong token or none at all (Codex review finding 1).
    audit_by_id: dict[str, dict[str, Any]] = {}
    for token in audit_manifest.get("tokens", []):
        raw_id = token.get("token_id")
        if raw_id is None or str(raw_id) == "":
            failures.append(
                ProvenanceFailure("missing_token_id", "audit token has no token_id")
            )
            continue
        token_id = str(raw_id)
        if token_id in audit_by_id:
            failures.append(
                ProvenanceFailure(
                    "duplicate_audit_token_id",
                    f"audit token id repeated: {token_id}",
                )
            )
        audit_by_id[token_id] = token

    for slim_token in slim_manifest.get("tokens", []):
        raw_id = slim_token.get("token_id")
        if raw_id is None or str(raw_id) == "":
            failures.append(
                ProvenanceFailure("missing_token_id", "slim token has no token_id")
            )
            continue
        token_id = str(raw_id)
        audit_token = audit_by_id.get(token_id)
        # A slim token with no audit match has no provenance trail at all -- it
        # must not publish (worse than restored-marked-recognised, not better).
        if audit_token is None:
            failures.append(
                ProvenanceFailure(
                    "slim_token_not_in_audit",
                    f"slim token {token_id} has no matching audit provenance",
                )
            )
            continue
        if (
            audit_token.get("output_status") in PRIVATE_STATUSES
            and slim_token.get("published_as") == "recognised_from_page"
        ):
            failures.append(
                ProvenanceFailure(
                    "restored_marked_recognised",
                    f"token {token_id} hides private provenance as recognised_from_page",
                )
            )


def verify_release(
    slim_manifest_path: Path, audit_manifest_path: Path | None, release_root: Path
) -> VerificationResult:
    failures: list[ProvenanceFailure] = []
    slim_manifest = _load_json(Path(slim_manifest_path))
    audit_manifest = _load_audit_manifest(
        slim_manifest, audit_manifest_path, Path(release_root), failures
    )

    _check_artifacts(
        slim_manifest,
        manifest_label="slim",
        release_root=Path(release_root),
        failures=failures,
    )
    _check_token_statuses(slim_manifest, "slim", failures)

    if audit_manifest is not None:
        _check_artifacts(
            audit_manifest,
            manifest_label="audit",
            release_root=Path(release_root),
            failures=failures,
        )
        _check_token_statuses(audit_manifest, "audit", failures)
        _check_provenance_integrity(slim_manifest, audit_manifest, failures)

    return VerificationResult(ok=not failures, failures=failures)


def _report_payload(
    slim_manifest_path: Path, result: VerificationResult
) -> dict[str, Any]:
    try:
        release_id = str(_load_json(slim_manifest_path).get("release_id", "unknown"))
    except (OSError, json.JSONDecodeError):
        release_id = "unknown"
    return {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "release_id": release_id,
        "ok": result.ok,
        "failures": [
            {"code": failure.code, "detail": failure.detail} for failure in result.failures
        ],
    }


def _write_reports(payload: dict[str, Any]) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(REPORT_JSON, payload, REPORT_SCHEMA)
    lines = [
        f"# Provenance verification: {payload['release_id']}",
        "",
        f"Status: {'PASS' if payload['ok'] else 'FAIL'}",
        "",
    ]
    if payload["failures"]:
        lines.append("Failures:")
        for failure in payload["failures"]:
            lines.append(f"- {failure['code']}: {failure['detail']}")
    else:
        lines.append("Failures: none")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify publish provenance for a release.")
    parser.add_argument("--slim", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--release-root", type=Path, required=True)
    args = parser.parse_args(argv)

    release_root = args.release_root
    slim_path = args.slim if args.slim is not None else release_root / "manifests" / "slim.json"
    audit_path = args.audit if args.audit is not None else release_root / "manifests" / "audit.json"

    result = verify_release(slim_path, audit_path, release_root)
    _write_reports(_report_payload(slim_path, result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
