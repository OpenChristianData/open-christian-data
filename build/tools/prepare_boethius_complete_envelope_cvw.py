"""Bind the exact Boethius candidate to a full independent CVW validation record."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build.tei.boethius_complete_envelope_oracle import _oracle
from cvw_app.stage_candidate import stage_candidate
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "sources/structured-text/boethius-theological-tractates/complete-envelope-v4/source-manifest.json"
PACKAGE = Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-candidate-20260927-v4")
VALIDATION = Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-validation-20260927-v5.json")
DESTINATION = Path("D:/Library/Open Christian Data/candidate-reviews/boethius-complete-envelope-cvw-20260927-v5")


def main() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = CandidatePackage.load(PACKAGE)
    report = validate(source, candidate, _oracle)
    record = {"contract": "ocd-validation-report-v1", "status": report.status,
              "candidate_sha256": report.candidate_sha256,
              "source_manifest_sha256": report.source_manifest_sha256,
              "attestation": dict(report.attestation), "findings": list(report.findings)}
    record["report_sha256"] = report.sha256
    content = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if VALIDATION.exists():
        if VALIDATION.read_bytes() != content:
            raise FileExistsError(f"refusing to replace validation evidence: {VALIDATION}")
    else:
        VALIDATION.write_bytes(content)
    result = stage_candidate(package=PACKAGE, validation=VALIDATION,
                             destination=DESTINATION, repository_root=ROOT)
    result["validation_sidecar_sha256"] = hashlib.sha256(content).hexdigest()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
