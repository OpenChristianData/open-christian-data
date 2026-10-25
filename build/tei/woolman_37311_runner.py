"""Build and validate the current nonaccepted PG 37311 review candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate
from woolman_37311_oracle import _oracle
from woolman_37311_reconstruction import _convert


MANIFEST = ROOT / "sources/manifest-acquisitions/gutenberg-pg37311-woolman-v5/source-manifest.json"


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _thaw(value: Any) -> Any:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def build(destination: Path) -> dict[str, object]:
    destination = destination.resolve(strict=False)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError(f"candidate destination must be absent or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    package = reconstruct(source, destination / "package", _convert)
    report = validate(source, package, _oracle)
    report_record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": _thaw(report.attestation),
        "findings": list(report.findings),
        "report_sha256": report.sha256,
    }
    validation_path = destination / "validation.json"
    validation_path.write_bytes(_canonical(report_record))
    return {
        "candidate_root": str(destination),
        "package_sha256": package.sha256,
        "tei_sha256": _sha(package.member_bytes("content.tei.xml")),
        "validation_sha256": _sha(validation_path.read_bytes()),
        "validation_status": report.status,
        "findings": list(report.findings),
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: py -3 build/tei/woolman_37311_runner.py <empty-or-absent-candidate-root>")
    print(json.dumps(build(Path(sys.argv[1])), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
