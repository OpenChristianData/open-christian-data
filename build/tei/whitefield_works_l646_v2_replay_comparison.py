"""Verify exact candidate-package and validation replay identity for L646."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

EXPECTED_MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _load_output(
    label: str, output_root: Path
) -> tuple[dict[str, object], dict[str, bytes]]:
    package_path = output_root / "package"
    package = CandidatePackage.load(str(package_path))
    member_paths = sorted(path for path in package_path.iterdir() if path.is_file())
    member_bytes = {path.name: path.read_bytes() for path in member_paths}
    if set(member_bytes) != EXPECTED_MEMBERS:
        raise ValueError(f"{label}: candidate member set changed")

    validation_path = output_root / "validation.json"
    validation_bytes = validation_path.read_bytes()
    validation = json.loads(validation_bytes)
    if validation.get("status") != "pass":
        raise ValueError(f"{label}: validation status is not pass")
    if validation.get("candidate_sha256") != package.sha256:
        raise ValueError(f"{label}: validation candidate digest mismatch")
    report = dict(validation)
    report_sha256 = report.pop("report_sha256", None)
    if report_sha256 != _sha(_canonical(report)):
        raise ValueError(f"{label}: validation report digest mismatch")
    attestation = validation.get("attestation")
    if not isinstance(attestation, dict):
        raise ValueError(f"{label}: missing independent oracle attestation")
    if attestation.get("candidate_sha256") != package.sha256:
        raise ValueError(f"{label}: oracle attestation candidate digest mismatch")

    record: dict[str, object] = {
        "output_root": str(output_root.resolve()),
        "package_path": str(package_path.resolve()),
        "candidate_sha256": package.sha256,
        "candidate_member_sha256": {
            name: _sha(content) for name, content in sorted(member_bytes.items())
        },
        "validation_path": str(validation_path.resolve()),
        "validation_report_sha256": report_sha256,
        "validation_sidecar_sha256": _sha(validation_bytes),
        "validation_status": validation["status"],
        "oracle_result_sha256": attestation.get("result_sha256"),
    }
    return record, {**member_bytes, "validation.json": validation_bytes}


def run(
    *,
    manifest_path: str,
    repository_root: str,
    candidate_root: str,
    replay_a_root: str,
    replay_b_root: str,
) -> dict[str, object]:
    root = Path(repository_root).resolve(strict=True)
    manifest = SourceManifest.load(root / manifest_path, repository_root=root)
    outputs = {
        "candidate": Path(candidate_root),
        "replay_a": Path(replay_a_root),
        "replay_b": Path(replay_b_root),
    }
    records: dict[str, dict[str, object]] = {}
    contents: dict[str, dict[str, bytes]] = {}
    for label, output_root in outputs.items():
        records[label], contents[label] = _load_output(label, output_root)

    reference = contents["candidate"]
    byte_identical = {
        label: all(reference[name] == output[name] for name in reference)
        for label, output in contents.items()
    }
    if not all(byte_identical.values()):
        raise ValueError("candidate package or validation bytes differ across replays")
    if any(
        record["candidate_sha256"] != records["candidate"]["candidate_sha256"]
        for record in records.values()
    ):
        raise ValueError("candidate package digests differ across replays")
    if any(
        record["validation_report_sha256"]
        != records["candidate"]["validation_report_sha256"]
        for record in records.values()
    ):
        raise ValueError("validation report digests differ across replays")
    if any(
        record["oracle_result_sha256"] != records["candidate"]["oracle_result_sha256"]
        for record in records.values()
    ):
        raise ValueError("oracle result digests differ across replays")

    return {
        "contract": "ocd-l646-clean-replay-comparison-v2",
        "status": "pass",
        "source_manifest_path": Path(manifest_path).as_posix(),
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": records["candidate"]["candidate_sha256"],
        "validation_report_sha256": records["candidate"]["validation_report_sha256"],
        "validation_sidecar_sha256": records["candidate"]["validation_sidecar_sha256"],
        "oracle_result_sha256": records["candidate"]["oracle_result_sha256"],
        "expected_members": sorted(EXPECTED_MEMBERS),
        "byte_identical": byte_identical,
        "outputs": records,
        "candidate_and_source_files_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--replay-a-root", required=True)
    parser.add_argument("--replay-b-root", required=True)
    parser.add_argument("--output")
    arguments = parser.parse_args()
    result = _canonical(
        run(
            manifest_path=arguments.manifest,
            repository_root=arguments.repository_root,
            candidate_root=arguments.candidate_root,
            replay_a_root=arguments.replay_a_root,
            replay_b_root=arguments.replay_b_root,
        )
    )
    if arguments.output:
        Path(arguments.output).write_bytes(result)
    print(result.decode("utf-8"), end="")


if __name__ == "__main__":
    main()
