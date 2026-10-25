"""Freeze source-inspected bsb750 prose editions without canonical installation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree

from build.tools import stage_openmgh_language_rebind as language
from build.tools import stage_openmgh_inspected_acceptance as acceptance
from build.tools.prepare_openmgh_bsb750_remaining import SOURCE, SOURCE_SHA
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb750-remaining-inspected-batch-20260926.json")
BATCH_SHA = "76211c0da1f612d016d8d58bc90a72da176f17fba3b7f572f30e53e7830f3d59"
STAGE_HOME = Path("D:/Library/Open Christian Data/acceptance-stages/openmgh-bsb750-remaining-20260926")
SCRATCH_HOME = Path("C:/Scratch/b7")
RECEIPT_HOME = ROOT / "plans/2026-09-22-source-preflight"
CONTRACT = "ocd-openmgh-bsb750-remaining-prose-stage-v1"
CLAUSES = {
    "miracula-post-mortem-martini-vertavensis": "De beati Martini Vertavensis vitae qualitate",
    "virtus-sancti-aniani-aurelianensis": "In temporae illo cum Chunorum exercitus",
    "vita-sancti-betharii": "Cum beatorum confessorum gesta religio christiana",
    "vita-sancti-caesarii-arelatis": "Quia, reverenda nobis virgo Caesaria",
    "vita-sancti-droctovei": "Priscorum permaxima semper cura fuit",
    "vita-sancti-fidoli": "Congrue igitur adgrediamur sancti praeconium",
    "vita-sancti-fridolini-baltheri": "Iam dudum vero, ut vos optime nostis",
    "vita-sancti-iohannis-reomaensis": "Anno centesimo post explicionem numeri sancti Victori",
    "vita-sancti-leonardi": "Beatus igitur Leonardus temporibus Anastasii",
    "vita-sancti-lucii-confessoris": "Diem festum celebrantes beatissimi Lucii",
    "vita-sancti-maximini-trevirensis": "Amicos honestis certare officiis seque invicem",
    "vita-sancti-nicetii-lugdunensis": "Quotiens sanctorum gesta virorum lectionis relatio",
    "vita-sancti-severini-acaunensis": "Sacram sane libelli seriem, quam Faustus",
    "vita-sancti-theudarii": "Patris vestri vitam, id est beati",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


def _copy_if_missing(root: Path, stage: Path, relative: Path) -> None:
    target = _io_path(stage / relative)
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(root / relative), target)


def receipt_path(work_id: str) -> Path:
    if work_id not in CLAUSES:
        raise PipelineError(f"work outside bsb750 remaining whole-division route: {work_id}")
    return RECEIPT_HOME / f"{work_id}-openmgh-bsb750-remaining-stage-20260926.json"


def prepare(work_id: str, *, root: Path = ROOT, scratch_home: Path = SCRATCH_HOME,
            stage_home: Path = STAGE_HOME, receipt: Path | None = None) -> dict:
    if work_id not in CLAUSES:
        raise PipelineError(f"work outside bsb750 remaining whole-division route: {work_id}")
    root = root.resolve(strict=True)
    receipt = receipt or receipt_path(work_id)
    if _sha(root / BATCH) != BATCH_SHA or _sha(root / SOURCE) != SOURCE_SHA:
        raise PipelineError("inspected batch or extracted source changed")
    batch = _read(root / BATCH)
    entries = [item for item in batch["works"] if item["work_id"] == work_id]
    if len(entries) != 1:
        raise PipelineError("inspected work entry is not unique")
    old = entries[0]
    scratch_home.mkdir(parents=True, exist_ok=True)
    stage_home.mkdir(parents=True, exist_ok=True)
    scratch = scratch_home / work_id
    initial = scratch / "initial"
    initial_receipt = scratch / "initial-receipt.json"
    final = stage_home / work_id
    if any(_io_path(path).exists() for path in (scratch, final, receipt)):
        raise PipelineError("scratch, durable stage, and receipt must be fresh")
    _io_path(scratch).mkdir(parents=True)
    declaration = Path("sources/openmgh-exclusive") / work_id / "acceptance-declaration.json"
    acceptance.prepare(root, declaration, BATCH, initial, initial_receipt)
    acceptance.preflight(initial_receipt)
    manifest_rel = Path(old["manifest_path"])
    manifest = _read(initial / manifest_rel)
    policy = _read(root / "sources/openmgh-exclusive/validation-policy.json")
    dependencies = {Path("ocd_kernel/reconstruction/contract.py"),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd")}
    dependencies.update(Path(item["path"]) for item in manifest["authorities"])
    dependencies.update(Path(manifest[key]["implementation_path"])
                        for key in ("converter", "validator"))
    dependencies.add(Path(manifest["package_schema"]["path"]))
    dependencies.update(Path(path) for path in policy["closure_inputs"])
    for relative in sorted(dependencies):
        _copy_if_missing(root, initial, relative)
    receipt_name = f"{work_id}-bsb750-remaining-initial.json"
    receipt_rel = Path("plans/2026-09-22-source-preflight") / receipt_name
    _io_path(initial / receipt_rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(initial_receipt), _io_path(initial / receipt_rel))
    language.SOURCE = SOURCE
    language.SOURCE_SHA = SOURCE_SHA
    language.IDS = (work_id,)
    language.PROSE_CLAUSES = {work_id: CLAUSES[work_id]}
    language.STAGE_RECEIPTS = {work_id: receipt_name}
    original_copy = language._copy

    def copy_volume(source_root: Path, target_root: Path, relative: Path) -> None:
        if relative == Path("raw/openmgh/bsb00000752/acquisition-receipt.json"):
            relative = SOURCE.parent.parent / "acquisition-receipt.json"
        original_copy(source_root, target_root, relative)

    try:
        language._copy = copy_volume
        source_tree = etree.parse(str(_io_path(root / SOURCE)), etree.XMLParser(
            resolve_entities=False, no_network=True, huge_tree=True))
        language_result = language._prepare_one(initial, final, work_id, source_tree)
    finally:
        language._copy = original_copy
    work = Path("library/works") / work_id
    edition = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic"
    accepted = validate_acceptance(final / edition / "acceptance.json", root=final)
    validate_state(final / work / "state.json", root=final)
    SourceManifest.load(final / manifest_rel, repository_root=final)
    projected = project_accepted_prose(_io_path(final),
        acceptance_path=_io_path(final / edition / "acceptance.json"))
    errors = verify_accepted_prose(_io_path(final),
        acceptance_path=_io_path(final / edition / "acceptance.json"),
        rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"actual-master prose projection failed: {errors[:3]}")
    original = CandidatePackage.load(Path(old["candidate_root"]) / "package")
    master = _io_path(final / edition / "master.tei.xml").read_bytes()
    if master.split(b"</teiHeader>", 1)[1] != original.member_bytes("content.tei.xml").split(b"</teiHeader>", 1)[1]:
        raise PipelineError("accepted master body differs from inspected candidate")
    profile_rel = Path(old["profile_path"])
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": work_id,
        "canonical_root": root.as_posix(), "stage_root": final.as_posix(),
        "original_inspection_receipt": BATCH.as_posix(),
        "original_inspection_receipt_sha256": BATCH_SHA,
        "original_candidate_sha256": old["candidate_sha256"],
        "original_candidate_tei_sha256": old["candidate_tei_sha256"],
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
        "manifest_path": manifest_rel.as_posix(),
        "profile_path": profile_rel.as_posix(),
        "source_manifest_before_sha256": _sha(root / manifest_rel),
        "source_manifest_after_sha256": _sha(final / manifest_rel),
        "profile_before_sha256": _sha(root / profile_rel),
        "profile_after_sha256": _sha(final / profile_rel),
        "before": acceptance._files(root / work),
        "after": acceptance._files(final / work),
        "acceptance_sha256": _sha(final / edition / "acceptance.json"),
        "accepted_master_sha256": accepted["promotion"]["master"]["sha256"],
        "language": "la", "category": "prose",
        "projection_rows": 1, "projection_status": "independent-check-pass",
        "language_rebind": language_result,
        "installation": "not-performed",
    }
    _io_path(receipt.parent).mkdir(parents=True, exist_ok=True)
    acceptance._put_json(receipt.parent, Path(receipt.name), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(CLAUSES))
    args = parser.parse_args()
    result = prepare(args.work_id)
    receipt = receipt_path(args.work_id)
    print(json.dumps({"work_id": args.work_id, "status": result["status"],
                      "receipt_sha256": _sha(receipt),
                      "accepted_master_sha256": result["accepted_master_sha256"],
                      "projection_rows": result["projection_rows"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
