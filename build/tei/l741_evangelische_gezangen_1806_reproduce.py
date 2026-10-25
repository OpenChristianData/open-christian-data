"""Replay a sealed L741 candidate twice in fresh Python processes and compare all bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from ocd_kernel.reconstruction.contract import CandidatePackage


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


_CHILD = r'''
import hashlib,json,sys
from pathlib import Path
repo=Path(sys.argv[1]).resolve(strict=True)
manifest=repo/sys.argv[2]
route=Path(sys.argv[3]).resolve(strict=False)
sys.path.insert(0,str(repo))
from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct,validate
from build.tei.l741_evangelische_gezangen_1806 import _convert
from build.tei.l741_evangelische_gezangen_1806_oracle import _oracle
source=SourceManifest.load(manifest,repository_root=repo)
package=reconstruct(source,route/'package',_convert)
report=validate(source,package,_oracle)
record={'contract':'ocd-validation-report-v1','status':report.status,'candidate_sha256':report.candidate_sha256,'source_manifest_sha256':report.source_manifest_sha256,'attestation':dict(report.attestation),'findings':list(report.findings),'sha256':report.sha256}
report_record={'contract':'ocd-validation-report-v1','status':report.status,'candidate_sha256':report.candidate_sha256,'source_manifest_sha256':report.source_manifest_sha256,'attestation':dict(report.attestation),'findings':list(report.findings)}
report_bytes=(json.dumps(report_record,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
assert hashlib.sha256(report_bytes).hexdigest()==report.sha256
encoded=(json.dumps({**report_record,'report_sha256':report.sha256},ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
(route/'validation.json').write_bytes(encoded)
print(json.dumps({'pid':__import__('os').getpid(),'candidate_sha256':package.sha256,'validation_sha256':hashlib.sha256(encoded).hexdigest()},sort_keys=True))
'''


def _route_record(path: Path) -> dict[str, object]:
    package_path = path / "package"
    package = CandidatePackage.load(package_path)
    validation_path = path / "validation.json"
    validation_bytes = validation_path.read_bytes()
    validation = json.loads(validation_bytes)
    if validation.get("status") != "pass" or validation.get("candidate_sha256") != package.sha256:
        raise ValueError(f"validation sidecar does not bind passing candidate: {path}")
    return {
        "route": str(path.resolve(strict=True)),
        "candidate_sha256": package.sha256,
        "members": {
            name: {
                "bytes": len(content := package.member_bytes(name)),
                "sha256": _sha(content),
            }
            for name in package.member_names
        },
        "validation_bytes": len(validation_bytes),
        "validation_sha256": _sha(validation_bytes),
        "validation_status": validation["status"],
        "validation_findings": validation.get("findings"),
    }


def _require_outside(repo: Path, destination: Path) -> Path:
    resolved = destination.resolve(strict=False)
    try:
        resolved.relative_to(repo)
    except ValueError:
        return resolved
    raise ValueError("L741 replay destinations must be outside the repository")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--baseline", required=True, type=Path, help="external candidate route with package/ and validation.json")
    parser.add_argument("--replay-one", required=True, type=Path)
    parser.add_argument("--replay-two", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    repo = args.repository_root.resolve(strict=True)
    manifest = (repo / args.manifest).resolve(strict=True)
    manifest.relative_to(repo)
    baseline = _require_outside(repo, args.baseline)
    replay_routes = [_require_outside(repo, args.replay_one), _require_outside(repo, args.replay_two)]
    receipt_path = _require_outside(repo, args.receipt)
    if len(set(replay_routes)) != 2 or baseline in replay_routes:
        raise ValueError("L741 replay destinations must be distinct from one another and the baseline")
    baseline_record = _route_record(baseline)
    for route in replay_routes:
        if route.exists():
            raise ValueError(f"refusing existing L741 replay route: {route}")
        route.mkdir(parents=True)
    manifest_logical = manifest.relative_to(repo).as_posix()
    child_records = []
    for route in replay_routes:
        completed = subprocess.run(
            [sys.executable, "-c", _CHILD, str(repo), manifest_logical, str(route)],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        child_records.append(json.loads(completed.stdout.strip()))
    replay_records = [_route_record(route) for route in replay_routes]
    baseline_bytes = {
        name: (baseline / "package" / name).read_bytes()
        for name in CandidatePackage.load(baseline / "package").member_names
    }
    baseline_validation = (baseline / "validation.json").read_bytes()
    comparisons = []
    for route, record in zip(replay_routes, replay_records, strict=True):
        package_equal = all((route / "package" / name).read_bytes() == content for name, content in baseline_bytes.items())
        validation_equal = (route / "validation.json").read_bytes() == baseline_validation
        comparisons.append({"route": str(route), "all_six_candidate_member_bytes_equal": package_equal, "validation_sidecar_bytes_equal": validation_equal})
        if not package_equal or not validation_equal:
            raise ValueError(f"L741 fresh replay differs from baseline at {route}")
    if receipt_path.exists():
        raise ValueError(f"refusing existing L741 reproduction receipt: {receipt_path}")
    receipt = {
        "contract": "ocd-clean-process-reproduction-v1",
        "status": "pass",
        "ticket_id": "L741",
        "work_id": "evangelische-gezangen-1806",
        "source_manifest": {"path": manifest_logical},
        "baseline": baseline_record,
        "fresh_processes": child_records,
        "replays": replay_records,
        "comparisons": comparisons,
        "exact_member_and_validation_byte_comparison": True,
        "fresh_process_count": 2,
        "runner": {"path": "build/tei/l741_evangelische_gezangen_1806_reproduce.py", "sha256": _sha(Path(__file__).read_bytes())},
        "runtime": {"python": sys.version, "executable": str(Path(sys.executable).resolve(strict=True))},
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(_canonical(receipt))
    print(json.dumps({"status": "pass", "baseline": str(baseline), "replays": [str(item) for item in replay_routes], "receipt": str(receipt_path), "receipt_sha256": _sha(receipt_path.read_bytes())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
