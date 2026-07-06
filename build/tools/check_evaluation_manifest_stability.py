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
from build.lib.atomic_io import write_json_atomic


DEFAULT_MANIFEST_DIR = REPO_ROOT / "reports" / "promotion" / "eval_manifests"
REPORT_JSON = REPO_ROOT / "reports" / "promotion" / "evaluation_manifest_stability.json"
REPORT_MD = REPO_ROOT / "reports" / "promotion" / "evaluation_manifest_stability.md"
REPORT_SCHEMA = {
    "type": "object",
    "required": ["checked_at", "eval_manifest_id", "ok", "decision", "failures"],
    "properties": {
        "checked_at": {"type": "string"},
        "eval_manifest_id": {"type": "string"},
        "ok": {"type": "boolean"},
        "decision": {"type": "string"},
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
class StabilityFailure:
    code: str
    detail: str


@dataclass(frozen=True)
class StabilityResult:
    ok: bool
    decision: str
    failures: list[StabilityFailure]


def _canonical_bytes(manifest: dict) -> bytes:
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_manifest_id(manifest: dict) -> str:
    material = dict(manifest)
    material.pop("eval_manifest_id", None)
    return sha256(_canonical_bytes(material)).hexdigest()


def reproduce_promotion(manifest: dict) -> str:
    if manifest.get("pending") is True:
        return "defer"
    thresholds = manifest.get("thresholds", {})
    metrics = manifest.get("metrics", {})
    min_n = int(thresholds.get("min_n", 0))
    min_delta = float(thresholds.get("min_abs_acc_delta", 0))
    n_observed = int(metrics.get("n_observed", 0))
    abs_acc_delta = float(metrics.get("abs_acc_delta", 0))
    if n_observed >= min_n and abs_acc_delta >= min_delta:
        return "promote"
    return "hold"


def check_manifest_stability(
    manifest: dict, prior_manifest: dict | None = None, reuse_scope: dict | None = None
) -> StabilityResult:
    failures: list[StabilityFailure] = []
    expected_id = compute_manifest_id(manifest)
    actual_id = manifest.get("eval_manifest_id")
    if expected_id != actual_id:
        failures.append(
            StabilityFailure(
                "id_content_mismatch",
                "eval_manifest_id does not match canonical manifest content",
            )
        )

    if (
        prior_manifest is not None
        and manifest.get("thresholds") != prior_manifest.get("thresholds")
        and manifest.get("policy_version") == prior_manifest.get("policy_version")
    ):
        failures.append(
            StabilityFailure(
                "policy_version_unchanged",
                "thresholds changed without changing policy_version",
            )
        )

    if reuse_scope is not None and reuse_scope != manifest.get("scope"):
        approval = manifest.get("cross_scope_approval")
        approved_hash = approval.get("manifest_hash") if isinstance(approval, dict) else None
        if approved_hash != actual_id:
            failures.append(
                StabilityFailure(
                    "cross_scope_reuse_unapproved",
                    "cross-scope reuse lacks approval for this manifest hash",
                )
            )

    if not manifest.get("report_hash"):
        failures.append(
            StabilityFailure("missing_report_hash", "report_hash is required")
        )

    reproduced = reproduce_promotion(manifest)
    if reproduced != manifest.get("decision"):
        failures.append(
            StabilityFailure(
                "not_reproducible",
                f"manifest decision {manifest.get('decision')} recomputes as {reproduced}",
            )
        )

    if manifest.get("pending") is True and not failures:
        return StabilityResult(ok=True, decision="defer", failures=[])
    return StabilityResult(ok=not failures, decision="pass" if not failures else "fail", failures=failures)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_manifest(manifest: dict[str, Any], manifest_dir: Path) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_id = str(manifest["eval_manifest_id"])
    target = manifest_dir / f"{manifest_id}.json"
    write_json_atomic(target, manifest, {"type": "object"})
    return target


def _report_payload(manifest: dict, result: StabilityResult) -> dict[str, Any]:
    return {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "eval_manifest_id": str(manifest.get("eval_manifest_id", "")),
        "ok": result.ok,
        "decision": result.decision,
        "failures": [
            {"code": failure.code, "detail": failure.detail} for failure in result.failures
        ],
    }


def _write_reports(payload: dict[str, Any]) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(REPORT_JSON, payload, REPORT_SCHEMA)
    lines = [
        f"# Evaluation manifest stability: {payload['eval_manifest_id']}",
        "",
        f"Status: {payload['decision'].upper()}",
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
    parser = argparse.ArgumentParser(description="Check evaluation manifest stability.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--prior-manifest", type=Path)
    parser.add_argument("--reuse-scope", type=Path)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args(argv)

    manifest = _load_json(args.manifest)
    prior = _load_json(args.prior_manifest) if args.prior_manifest is not None else None
    reuse_scope = _load_json(args.reuse_scope) if args.reuse_scope is not None else None
    result = check_manifest_stability(manifest, prior_manifest=prior, reuse_scope=reuse_scope)
    if result.ok:
        _write_manifest(manifest, args.manifest_dir)
    _write_reports(_report_payload(manifest, result))
    return 0 if result.ok and result.decision == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
