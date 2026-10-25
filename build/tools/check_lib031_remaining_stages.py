"""Reconcile nine LIB-031 stages with fresh-process packages and exact receipts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build.tools.install_lib031_remaining_acceptance import preflight
from build.tools.stage_lib031_remaining_acceptance import LIBRARY, ROOT, _work_row

ROUTES = {
    "bounds-essentials-of-prayer": ("l31-ess3", "ess"),
    "bounds-necessity-of-prayer": ("l31-nec2", "nec"),
    "bounds-prayer-and-praying-men": ("l31-men1", "men"),
    "bounds-purpose-in-prayer": ("l31-pur1", "pur"),
    "bounds-reality-of-prayer": ("l31-real1", "real"),
    "bounds-weapon-of-prayer": ("l31-weap1", "weap"),
    "finney-lectures-on-revivals": ("l31-rev1", "rev"),
    "finney-systematic-theology": ("l31-theo1", "theo"),
    "pascal-pensees": ("l31-pas1", "pas"),
}
REPORT = ROOT / "plans/2026-09-22-source-preflight/lib031-remaining-acceptance-stages-20260926.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _sha(path) for path in root.rglob("*") if path.is_file()}


def check() -> dict[str, object]:
    works = []
    for work_id, (stage_name, reproduction_name) in ROUTES.items():
        row = _work_row(work_id)
        stage = LIBRARY / stage_name
        reproduction = LIBRARY / f"l31-repro-{reproduction_name}"
        original = LIBRARY / "candidate-reviews" / f"lib031-work-{work_id}-20260926-v6"
        expected = _files(original)
        actual = _files(reproduction)
        if len(expected) != 7 or expected != actual:
            raise ValueError(f"fresh-process package/validation bytes differ: {work_id}")
        stage_receipt = stage / "stage-receipt.json"
        receipt_hash = _sha(stage_receipt)
        receipt = json.loads(stage_receipt.read_bytes())
        gate = preflight(work_id, stage, receipt_hash)
        if gate["status"] != "pass-read-only" or gate["projection_independent_verifier_errors"]:
            raise ValueError(f"guarded preflight differs: {work_id}")
        works.append({
            "work_id": work_id,
            "source_path": row["source"]["path"],
            "source_sha256": row["source"]["sha256"],
            "source_body_nodes": row["source"]["body_nodes"],
            "candidate_package_sha256": row["standard_work_local_candidate"]["package_manifest_sha256"],
            "fresh_process_root": reproduction.as_posix(),
            "original_candidate_root": original.as_posix(),
            "fresh_process_compared_files": expected,
            "stage_root": stage.as_posix(),
            "stage_receipt_sha256": receipt_hash,
            "acceptance_sha256": receipt["acceptance_sha256"],
            "master_sha256": receipt["master_sha256"],
            "projection_canary_sha256": receipt["projection_canary_sha256"],
            "projection_structure_kinds": receipt["projection_structure_kinds"],
            "current_work_files": gate["current_work_files"],
            "staged_work_files": gate["staged_work_files"],
            "read_only_preflight_status": gate["status"],
        })
    result = {
        "contract": "ocd-lib031-remaining-stage-reconciliation-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "nine remaining LIB-031 exact electronic XML witnesses; no canonical apply or corpus refresh",
        "counts": {"works": len(works), "fresh_process_file_matches": sum(len(row["fresh_process_compared_files"]) for row in works),
                   "passed_read_only_preflights": len(works), "canonical_installs": 0},
        "works": works,
        "rights_clearance": "not-assessed",
        "human_review": "not-recorded",
        "publication": "not-authorized",
    }
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = check()
    print(json.dumps({"report": REPORT.as_posix(), "counts": result["counts"]}, sort_keys=True))
