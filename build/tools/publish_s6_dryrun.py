from __future__ import annotations

import json, hashlib, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from datetime import datetime, timezone

from build.lib.atomic_io import write_json_atomic
from build.lib.publish_projection import (
    build_audit_artifact,
    build_slim_config,
    slim_leaks_audit_fields,
)
from build.lib.typography_snapshot import (
    TypographySnapshotIntegrityError,
    assert_admissible,
    load_typography_snapshot,
)

_JSON_OBJECT_SCHEMA = {"type": "object", "additionalProperties": True}


def _canonical_hash(obj: dict) -> str:
    blob = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _write_markdown_report(path: Path, report: dict) -> None:
    lines = [
        "# S6 dry-run report",
        "",
        f"- dry_run: {str(report['dry_run']).lower()}",
        f"- live_publish_performed: {str(report['live_publish_performed']).lower()}",
        f"- config: {report['config']}",
        f"- staging_dir: {report['staging_dir']}",
        "",
        "Live publish was not performed. It remains a separate maintainer-gated action.",
        "",
    ]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run S6 publish dry-run locally.")
    parser.add_argument("--records", required=True)
    parser.add_argument("--typography-envelope", required=True)
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    staging_dir = Path(args.staging_dir)

    try:
        records = json.loads(Path(args.records).read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise ValueError("records input must be a JSON list")
        typography_envelope = load_typography_snapshot(Path(args.typography_envelope))
        assert_admissible(typography_envelope)

        audit = build_audit_artifact(records)
        slim = build_slim_config(records)
        leaks = slim_leaks_audit_fields(slim)
        if leaks:
            raise ValueError(f"audit-only fields leaked into slim config: {leaks}")

        staging_dir.mkdir(parents=True, exist_ok=True)
        slim_path = staging_dir / "slim_config.json"
        audit_path = staging_dir / "audit_artifact.json"
        manifest_path = staging_dir / "dryrun_manifest.json"
        manifest = {
            "dry_run": True,
            "live_publish_performed": False,
            "live_publish_status": "not_performed_maintainer_gated",
            "config": "option-C-slim-public+audit-private",
            "created_at": _utc_now(),
            "typography_snapshot_id": typography_envelope["snapshot_id"],
            "typography_snapshot_payload_hash": typography_envelope[
                "snapshot_payload_hash"
            ],
            "slim_config_path": slim_path.name,
            "audit_artifact_path": audit_path.name,
            "slim_config_hash": _canonical_hash(slim),
            "audit_artifact_hash": _canonical_hash(audit),
        }
        write_json_atomic(slim_path, slim, _JSON_OBJECT_SCHEMA)
        write_json_atomic(audit_path, audit, _JSON_OBJECT_SCHEMA)
        write_json_atomic(manifest_path, manifest, _JSON_OBJECT_SCHEMA)

        report_dir = repo_root / "reports" / "publish"
        report_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "dry_run": True,
            "live_publish_performed": False,
            "live_publish_status": "not_performed_maintainer_gated",
            "config": "option-C-slim-public+audit-private",
            "created_at": manifest["created_at"],
            "staging_dir": "<staging-dir>",
            "manifest_path": "<staging-dir>/dryrun_manifest.json",
            "note": "Live publish is a separate maintainer-gated action.",
        }
        write_json_atomic(
            report_dir / "s6_dryrun_report.json", report, _JSON_OBJECT_SCHEMA
        )
        _write_markdown_report(report_dir / "s6_dryrun_report.md", report)
        return 0
    except (TypographySnapshotIntegrityError, ValueError, KeyError, json.JSONDecodeError) as exc:
        # Record the failure as an auditable report so every path -- including a
        # blocked dry-run -- affirms live publish was not performed (Codex review
        # finding 5). No publish can occur here: there is no network code at all.
        report_dir = repo_root / "reports" / "publish"
        report_dir.mkdir(parents=True, exist_ok=True)
        failure_report = {
            "dry_run": True,
            "live_publish_performed": False,
            "live_publish_status": "not_performed_dryrun_blocked",
            "config": "option-C-slim-public+audit-private",
            "created_at": _utc_now(),
            "staging_dir": "<staging-dir>",
            "error_code": type(exc).__name__,
            "note": "Dry-run blocked before staging. Live publish is a separate maintainer-gated action.",
        }
        write_json_atomic(
            report_dir / "s6_dryrun_report.json", failure_report, _JSON_OBJECT_SCHEMA
        )
        _write_markdown_report(report_dir / "s6_dryrun_report.md", failure_report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
