"""Freeze or read-only audit four exact nonaccepted JWBickel dictionary candidates."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from build.tei.bible_dictionaries_oracle import _oracle as dictionary_oracle
from build.tei.torreys_topical_textbook_oracle import _oracle as torrey_oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
REVIEW = Path("D:/Library/Open Christian Data/candidate-reviews/jwbickel-dictionaries-20260928-v1")
RECEIPT = ROOT / "plans/2026-09-22-source-preflight/jwbickel-dictionary-candidates-frozen-20260928.json"
SOURCES = {
    "eastons-bible-dictionary": ("eastons.jsonl", "978e09fdb66e9c6b722085f868c0cc84030df9e15c6188a06390f3822888082a", 3963, 7464),
    "hitchcocks-bible-names-dictionary": ("hitchcocks.jsonl", "e25b127cfc9c6f6f14eb9aa059ea0b3ed7ceaf97e2fd88c192d74387c3e904a5", 2622, 2622),
    "smiths-bible-dictionary": ("smiths.jsonl", "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d", 4560, 5362),
    "torreys-topical-textbook": ("torreys.jsonl", "8211c20290e951f60e21187e3bdaea639c8cf59343675b6518c6c17423906a1c", 623, 23549),
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _record(work_id: str) -> dict[str, object]:
    member, expected_source, records, definitions = SOURCES[work_id]
    source = ROOT / "raw/bible_dictionaries" / member
    if _sha(source) != expected_source:
        raise ValueError(f"retained source changed: {work_id}")
    manifest_path = ROOT / "sources" / work_id / f"{work_id}.source-manifest.json"
    manifest = SourceManifest.load(manifest_path, repository_root=ROOT)
    if manifest.record["work_id"] != work_id:
        raise ValueError(f"source manifest work identity changed: {work_id}")
    outer = REVIEW / work_id
    if outer.resolve(strict=True).parent != REVIEW.resolve(strict=True):
        raise ValueError(f"candidate review root changed: {work_id}")
    if {path.name for path in outer.iterdir()} != {"package", "validation.json"}:
        raise ValueError(f"candidate outer member set changed: {work_id}")
    candidate = CandidatePackage.load(outer / "package")
    if candidate.manifest["status"] != "nonaccepted" or candidate.manifest["source_id"] != manifest.record["source_id"]:
        raise ValueError(f"candidate source or status changed: {work_id}")
    oracle = torrey_oracle if work_id == "torreys-topical-textbook" else dictionary_oracle
    report = validate(manifest, candidate, oracle)
    sidecar = _read(outer / "validation.json")
    if (sidecar.get("contract") != "ocd-validation-report-v1"
            or sidecar.get("status") != "pass"
            or sidecar.get("findings") != []
            or sidecar.get("candidate_sha256") != candidate.sha256
            or sidecar.get("source_manifest_sha256") != manifest.sha256
            or sidecar.get("report_sha256") != report.sha256):
        raise ValueError(f"validation sidecar differs from fresh oracle: {work_id}")
    work = ROOT / "library/works" / work_id
    if any(path.name in {"acceptance.json", "master.tei.xml"} for path in work.rglob("*")):
        raise ValueError(f"work is already accepted: {work_id}")
    state = _read(work / "state.json")
    if state.get("work_id") != work_id or any(
        target.get("stage") != "acquired" for target in state.get("targets", [])
    ):
        raise ValueError(f"canonical work state changed: {work_id}")
    return {
        "source_member": member,
        "source_sha256": expected_source,
        "source_records": records,
        "source_definition_blocks": definitions,
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "tei_sha256": _sha(outer / "package/content.tei.xml"),
        "validation_report_sha256": report.sha256,
        "validation_sidecar_sha256": _sha(outer / "validation.json"),
        "canonical_before": _files(work),
    }


def audit(*, freeze: bool = False) -> dict[str, object]:
    if freeze and RECEIPT.exists():
        raise ValueError("frozen receipt already exists")
    observed = {work_id: _record(work_id) for work_id in SOURCES}
    expected = {
        "contract": "ocd-jwbickel-dictionary-nonaccepted-candidates-v1",
        "review_root": REVIEW.as_posix(),
        "status": "nonaccepted-ready-for-independent-review",
        "works": observed,
    }
    if freeze:
        RECEIPT.write_text(json.dumps(expected, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    elif _read(RECEIPT) != expected:
        raise ValueError("frozen dictionary candidate receipt or canonical preimage changed")
    return {
        "status": "ready-for-review",
        "installation": "not-performed",
        "works": len(observed),
        "source_records": sum(item[2] for item in SOURCES.values()),
        "source_definition_blocks": sum(item[3] for item in SOURCES.values()),
        "receipt_sha256": _sha(RECEIPT),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true", help="Write a new one-time frozen receipt")
    args = parser.parse_args()
    print(json.dumps(audit(freeze=args.freeze), sort_keys=True))


if __name__ == "__main__":
    main()
