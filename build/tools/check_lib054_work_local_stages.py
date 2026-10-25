"""Reconcile exact LIB-054 child candidates, reproductions, and guarded stages."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build.tools.generate_lib054_work_manifests import manifest_bytes
from build.tools.install_lib054_full_witness_acceptance import preflight
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path(r"D:\Library\Open Christian Data")
FAMILY = Path("sources/structured-text/lib054-ccel-puritan")
REPORT = ROOT / "plans/2026-09-22-source-preflight/lib054-work-local-acceptance-stages-20260926.json"
STAGES = {
    "baxter-call-to-unconverted": "l54-baxter-call-v2",
    "baxter-reformed-pastor": "l54-baxter-pastor-v2",
    "baxter-saints-rest": "l54-baxter-saints-v2",
    "boston-crook-in-the-lot": "l54-boston-crook-v2",
    "bunyan-grace-abounding": "l54-bunyan-grace-v2",
    "bunyan-holy-war": "l54-bunyan-war-v2",
    "butler-analogy-of-religion": "l54-butler-analogy-v2",
    "edwards-freedom-of-the-will": "l54-edwards-will-v2",
}
EXTRACTS = {"edwards-distinguishing-marks", "edwards-history-of-redemption"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _files(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _sha(path.read_bytes()) for path in root.rglob("*") if path.is_file()}


def check() -> dict[str, object]:
    profile = json.loads((ROOT / FAMILY / "lib054.reconstruction-profile.json").read_bytes())
    if len(profile["works"]) != 10 or set(STAGES) | EXTRACTS != {row["work_id"] for row in profile["works"]}:
        raise ValueError("LIB-054 ten-work partition changed")
    works = []
    for row in profile["works"]:
        work_id = str(row["work_id"])
        source = ROOT / row["source_path"]
        content = source.read_bytes()
        if (len(content), _sha(content)) != (row["bytes"], row["sha256"]):
            raise ValueError(f"retained LIB-054 source changed: {work_id}")
        manifest_path = ROOT / FAMILY / "work-bindings" / work_id / "lib054-work.source-manifest.json"
        if manifest_path.read_bytes() != manifest_bytes(ROOT, work_id):
            raise ValueError(f"work-local LIB-054 manifest changed: {work_id}")
        manifest = SourceManifest.load(manifest_path, repository_root=ROOT)
        candidate_root = LIBRARY / "candidate-reviews" / f"lib054-work-{work_id}-20260926-v2"
        candidate = CandidatePackage.load(candidate_root / "package")
        candidate.verify_integrity()
        validation = json.loads((candidate_root / "validation.json").read_bytes())
        if validation.get("status") != "pass" or validation.get("candidate_sha256") != candidate.sha256 or validation.get("source_manifest_sha256") != manifest.sha256:
            raise ValueError(f"recorded LIB-054 validation changed: {work_id}")
        reproduction = LIBRARY / "candidate-reviews" / f"lib054-repro-{work_id}-20260926-v2"
        original_files, reproduced_files = _files(candidate_root), _files(reproduction)
        if len(original_files) != 7 or reproduced_files != original_files:
            raise ValueError(f"clean-process LIB-054 reproduction differs: {work_id}")
        result = {
            "work_id": work_id,
            "retained_source": {"path": row["source_path"], "bytes": len(content), "sha256": _sha(content)},
            "source_manifest": {"path": manifest_path.relative_to(ROOT).as_posix(), "sha256": manifest.sha256},
            "candidate_root": candidate_root.as_posix(),
            "candidate_package_sha256": candidate.sha256,
            "validation_sha256": _sha((candidate_root / "validation.json").read_bytes()),
            "candidate_file_hashes": original_files,
            "clean_process_reproduction_root": reproduction.as_posix(),
            "clean_process_file_matches": len(original_files),
        }
        if work_id in STAGES:
            stage = LIBRARY / STAGES[work_id]
            receipt_path = stage / "stage-receipt.json"
            receipt_sha = _sha(receipt_path.read_bytes())
            receipt = json.loads(receipt_path.read_bytes())
            guard = preflight(work_id, stage, receipt_sha)
            if guard["status"] != "pass-read-only" or guard["projection_independent_verifier_errors"] or guard["projection_rows"] != 1:
                raise ValueError(f"LIB-054 guarded stage changed: {work_id}")
            result["disposition"] = "staged-accepted-generation-not-installed"
            result["stage"] = {
                "root": stage.as_posix(), "receipt_sha256": receipt_sha,
                "acceptance_sha256": receipt["acceptance_sha256"],
                "master_sha256": receipt["master_sha256"],
                "before_work_files": guard["before"],
                "staged_work_files": guard["after"],
                "projection_category": "prose", "projection_rows": guard["projection_rows"],
                "projection_independent_verifier_errors": guard["projection_independent_verifier_errors"],
            }
        else:
            result["disposition"] = "nonaccepted-extracted-fragment"
            result["hold"] = "The retained local fragment has no ThML.head; exact extraction provenance and surrounding ownership in the enclosing works volume are not independently verified."
        works.append(result)
    output = {
        "contract": "ocd-lib054-work-local-stage-reconciliation-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "ten exact LIB-054 retained CCEL XML children; no canonical install, corpus refresh, or publication",
        "counts": {"source_checked_candidates": len(works), "clean_process_file_matches": sum(row["clean_process_file_matches"] for row in works), "guarded_staged_accepted_generations": len(STAGES), "extracted_fragment_holds": len(EXTRACTS), "canonical_installs": 0},
        "works": works,
        "shared_matter": "Each source's title, preface, index, notes, and nested divisions remain in source order inside that work; no neighboring retained XML is included.",
        "unassessed": ["print-edition collation", "close visual proofreading", "human acceptance", "public CCEL rights clearance", "publication"],
    }
    REPORT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    result = check()
    print(json.dumps({"report": REPORT.as_posix(), "counts": result["counts"]}, sort_keys=True))
