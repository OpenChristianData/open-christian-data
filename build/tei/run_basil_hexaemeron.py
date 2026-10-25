"""Supported fresh-process single-work package generation and validation."""
from __future__ import annotations
import argparse
from pathlib import Path
from build.tei.basil_hexaemeron_reconstruction import build_candidate,canonical
from build.tei.basil_hexaemeron_oracle import _oracle
from ocd_kernel.reconstruction.contract import SourceManifest,validate

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--destination",type=Path,required=True); args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    manifest=SourceManifest.load(root/"sources/manifest-acquisitions/basil-hexaemeron-npnf208/source-manifest.json",repository_root=root)
    args.destination.mkdir(parents=True,exist_ok=False)
    package=build_candidate(manifest,args.destination/"package")
    report=validate(manifest,package,_oracle)
    record=dict(contract="ocd-validation-report-v1",status=report.status,candidate_sha256=report.candidate_sha256,source_manifest_sha256=report.source_manifest_sha256,attestation=dict(report.attestation),findings=list(report.findings))
    (args.destination/"validation.json").write_bytes(canonical(record)); print(canonical(dict(status=report.status,candidate_sha256=package.sha256,findings=list(report.findings))).decode())
    return 0 if report.status=="pass" else 1

if __name__=="__main__":raise SystemExit(main())
