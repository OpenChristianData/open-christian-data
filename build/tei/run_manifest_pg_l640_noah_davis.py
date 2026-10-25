"""Build and validate one L640 Noah Davis candidate in a fresh process."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from build.tei.manifest_pg_l640_noah_davis import build_candidate
from build.tei.manifest_pg_l640_noah_davis_oracle import _oracle


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    repository = args.repository.resolve(strict=True)
    manifest_path = args.source_manifest if args.source_manifest.is_absolute() else repository / args.source_manifest
    manifest = SourceManifest.load(manifest_path, repository_root=repository)
    candidate = build_candidate(manifest, args.destination)
    report = validate(manifest, candidate, _oracle)
    record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": dict(report.attestation),
        "findings": list(report.findings),
    }
    payload = _canonical(record)
    if hashlib.sha256(payload).hexdigest() != report.sha256:
        raise ValueError("validation-report serialization differs from bound report")
    report_path = args.report.resolve(strict=False)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        raise FileExistsError(f"refusing to replace validation report: {report_path}")
    report_path.write_bytes(payload)
    print(json.dumps({
        "candidate": str(candidate.path),
        "candidate_sha256": candidate.sha256,
        "member_hashes": {entry["name"]: entry["sha256"] for entry in candidate.manifest["members"]},
        "report": str(report_path),
        "report_sha256": report.sha256,
        "status": report.status,
        "source_manifest_sha256": manifest.sha256,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
