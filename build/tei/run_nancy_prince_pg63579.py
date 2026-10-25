"""Fresh-process candidate generation and independent validation for PG63579."""
from __future__ import annotations

import argparse
from pathlib import Path
import json

from build.tei.nancy_prince_pg63579_reconstruction import build_candidate
from build.tei.nancy_prince_pg63579_oracle import _oracle
from ocd_kernel.reconstruction.contract import SourceManifest, validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    manifest = SourceManifest.load(root / "sources/manifest-acquisitions/nancy-prince-pg63579/source-manifest.json", repository_root=root)
    args.destination.mkdir(parents=True, exist_ok=False)
    package = build_candidate(manifest, args.destination / "package")
    report = validate(manifest, package, _oracle)
    record = dict(contract="ocd-validation-report-v1", status=report.status,
                  candidate_sha256=report.candidate_sha256, source_manifest_sha256=report.source_manifest_sha256,
                  attestation=dict(report.attestation), findings=list(report.findings))
    (args.destination / "validation.json").write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=report.status, candidate_sha256=package.sha256, findings=list(report.findings))))
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
