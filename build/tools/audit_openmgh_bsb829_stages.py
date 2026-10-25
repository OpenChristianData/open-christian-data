"""Verify and freeze the exact staged bsb829 candidate generations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build.tools.preflight_openmgh_bsb829_next import preflight
from build.tools.stage_openmgh_bsb829_inspected import BATCH, ROOT, SELECTED, SOURCE, SOURCE_SHA
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path


HOME = ROOT / "plans/2026-09-22-source-preflight"
AUDIT = HOME / "openmgh-bsb829-staged-audit-20260926.json"
PINS = HOME / "openmgh-bsb829-frozen-pins-20260926.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _put(path: Path, value: dict) -> None:
    if _io_path(path).exists():
        raise ValueError(f"refusing existing frozen artifact: {path}")
    _io_path(path).write_bytes(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    )


def audit() -> dict:
    if _io_path(AUDIT).exists() or _io_path(PINS).exists():
        raise ValueError("audit and frozen pins must be fresh")
    batch = json.loads(_io_path(ROOT / BATCH).read_bytes())
    if (batch.get("contract") != "ocd-openmgh-bsb829-inspected-batch-v1"
            or len(batch["works"]) != len(SELECTED) or len(batch["holds"]) != 50
            or _sha(ROOT / SOURCE) != SOURCE_SHA):
        raise ValueError("bsb829 source or identity inventory changed")
    rows = []
    receipt_digests = {}
    checked = {"candidate": 0, "canonical": 0, "staged": 0, "source_sidecar": 0}
    for item in batch["works"]:
        work_id = item["work_id"]
        receipt_rel = Path("plans/2026-09-22-source-preflight") / f"{work_id}-openmgh-bsb829-stage-20260926.json"
        receipt = ROOT / receipt_rel
        result = preflight(receipt)
        if result["status"] != "ready-for-review":
            raise ValueError(f"stage did not pass: {work_id}")
        record = json.loads(_io_path(receipt).read_bytes())
        root = Path(record["canonical_root"])
        stage = Path(record["stage_root"])
        candidate = Path(item["candidate_root"])
        actual_candidate = _files(candidate)
        if actual_candidate != item["output_file_sha256"]:
            raise ValueError(f"inspected candidate files changed: {work_id}")
        for key in ("boundary_review_path", "manifest_path", "profile_path"):
            if _sha(ROOT / item[key]) != item[key.replace("_path", "_sha256")]:
                raise ValueError(f"source sidecar changed: {work_id}: {key}")
        declaration = ROOT / "sources/openmgh-exclusive" / work_id / "acceptance-declaration.json"
        if not _io_path(declaration).is_file():
            raise ValueError(f"missing work declaration: {work_id}")
        checked["candidate"] += len(actual_candidate)
        checked["canonical"] += len(_files(root / "library/works" / work_id))
        checked["staged"] += len(_files(stage / "library/works" / work_id))
        checked["source_sidecar"] += 4
        receipt_digests[work_id] = _sha(receipt)
        rows.append({"work_id": work_id, "source_div_ordinal": item["work_div_ordinal"],
                     "category": record["category"], "stage_receipt": receipt_rel.as_posix(),
                     "stage_receipt_sha256": receipt_digests[work_id],
                     "accepted_master_sha256": record["accepted_master_sha256"],
                     "projection_rows": result["projection_rows"],
                     "before_files": result["before_files"], "after_files": result["after_files"],
                     "installation": "not-performed"})
    report = {
        "contract": "ocd-openmgh-bsb829-independent-stage-audit-v1",
        "status": "pass", "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
        "inspection_receipt": BATCH.as_posix(), "inspection_receipt_sha256": _sha(ROOT / BATCH),
        "candidate_files_checked": checked["candidate"],
        "canonical_work_files_checked": checked["canonical"],
        "staged_work_files_checked": checked["staged"],
        "source_sidecars_checked": checked["source_sidecar"],
        "installation": "not-performed", "works": rows,
    }
    _put(AUDIT, report)
    files = {path.as_posix(): _sha(ROOT / path) for path in (
        SOURCE,
        SOURCE.parent.parent / "acquisition-receipt.json",
        BATCH,
        AUDIT.relative_to(ROOT),
        Path("build/tools/stage_openmgh_bsb829_inspected.py"),
        Path("build/tools/stage_openmgh_bsb829_next.py"),
        Path("build/tools/preflight_openmgh_bsb829_next.py"),
        Path("build/tools/audit_openmgh_bsb829_stages.py"),
        Path("tests/test_install_openmgh_bsb829_next.py"),
    )}
    for item in batch["works"]:
        work_id = item["work_id"]
        for name in ("boundary-review.json", "reconstruction-profile.json",
                     "source-manifest.json", "acceptance-declaration.json"):
            path = Path("sources/openmgh-exclusive") / work_id / name
            files[path.as_posix()] = _sha(ROOT / path)
        path = Path("plans/2026-09-22-source-preflight") / f"{work_id}-openmgh-bsb829-stage-20260926.json"
        files[path.as_posix()] = _sha(ROOT / path)
    pins = {
        "contract": "ocd-openmgh-bsb829-frozen-review-pins-v1",
        "status": "staged-only-ready-for-review",
        "source": "extracted-xml", "canonical_install": "not-performed",
        "corpus_view_refresh": "not-performed",
        "work_count": len(rows), "held_identity_count": len(batch["holds"]),
        "candidate_file_count": checked["candidate"],
        "staged_work_file_count": checked["staged"],
        "stage_receipts": receipt_digests,
        "files": files,
    }
    _put(PINS, pins)
    return report


def main() -> int:
    report = audit()
    print(json.dumps({"works": len(report["works"]),
                      "staged_work_files": report["staged_work_files_checked"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
