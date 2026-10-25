"""Stage reviewed bsb829 electronic witnesses in isolated work generations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree

from build.tools import stage_openmgh_inspected_acceptance as acceptance
from build.tools import stage_openmgh_language_rebind as language
from build.tools.stage_openmgh_bsb829_inspected import BATCH, ROOT, SELECTED, SOURCE, SOURCE_SHA
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.poetry import project_accepted_poetry, verify_accepted_poetry
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance


BATCH_SHA = "6623a27ea9998fbd9fad1379eafa3fc6b58d887ad00b8b42b92f5441e86cf947"
CONTRACT = "ocd-openmgh-bsb829-next-stage-v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(acceptance._io_path(path).read_bytes()).hexdigest()


def _copy(root: Path, destination: Path, relative: Path) -> None:
    target = acceptance._io_path(destination / relative)
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(acceptance._io_path(root / relative), target)


def _normalized_batch_entry(batch: dict, item: dict) -> dict:
    # The shared normalizer operates on this shape. Preserve the bsb829 batch
    # contract and its independently pinned bytes outside this in-memory call.
    original = _normalized_batch_entry.original
    if batch.get("contract") == "ocd-openmgh-bsb829-inspected-batch-v1":
        return original({**batch, "contract": "ocd-openmgh-bsb828-inspected-batch-v1"}, item)
    return original(batch, item)


def prepare(root: Path, work_id: str, scratch: Path, receipt: Path) -> dict:
    if work_id not in SELECTED:
        raise PipelineError(f"work is outside the inspected bsb829 tranche: {work_id}")
    root = root.resolve(strict=True)
    scratch, receipt = scratch.absolute(), receipt.absolute()
    if (acceptance._io_path(receipt).exists() or root == scratch or root in scratch.parents):
        raise PipelineError("fresh receipt outside the repository is required")
    if _sha(root / SOURCE) != SOURCE_SHA or _sha(root / BATCH) != BATCH_SHA:
        raise PipelineError("pinned extracted XML or inspected batch changed")
    batch = json.loads(acceptance._io_path(root / BATCH).read_bytes())
    entries = [item for item in batch["works"] if item["work_id"] == work_id]
    if len(entries) != 1 or entries[0]["work_div_ordinal"] != SELECTED[work_id][0]:
        raise PipelineError("inspected work boundary changed")
    category = SELECTED[work_id][1]
    manifest_rel = Path(entries[0]["manifest_path"])
    manifest = json.loads(acceptance._io_path(root / manifest_rel).read_bytes())
    policy = json.loads(acceptance._io_path(root / "sources/openmgh-exclusive/validation-policy.json").read_bytes())
    scratch.mkdir(parents=True, exist_ok=True)
    initial = scratch / "initial"
    initial_receipt = scratch / "initial-receipt.json"
    declaration = Path("sources/openmgh-exclusive") / work_id / "acceptance-declaration.json"
    original_normalizer = acceptance._normalize_entry
    _normalized_batch_entry.original = original_normalizer
    try:
        acceptance._normalize_entry = _normalized_batch_entry
        if not acceptance._io_path(initial).exists() and not acceptance._io_path(initial_receipt).exists():
            acceptance.prepare(root, declaration, BATCH, initial, initial_receipt)
        if not acceptance._io_path(initial).is_dir() or not acceptance._io_path(initial_receipt).is_file():
            raise PipelineError("partial initial acceptance stage requires manual inspection")
        acceptance.preflight(initial_receipt)
    finally:
        acceptance._normalize_entry = original_normalizer
    dependencies = {SOURCE, BATCH, declaration, manifest_rel,
                    Path("sources/openmgh-exclusive/validation-policy.json"),
                    Path("ocd_kernel/reconstruction/contract.py"),
                    SOURCE.parent.parent / "acquisition-receipt.json",
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd")}
    dependencies.update(Path(item["path"]) for item in manifest["authorities"])
    dependencies.update(Path(manifest[key]["implementation_path"])
                        for key in ("converter", "validator"))
    dependencies.add(Path(manifest["package_schema"]["path"]))
    dependencies.update(Path(value) for value in policy["closure_inputs"])
    acquisition = json.loads(acceptance._io_path(root / entries[0]["acquisition_path"]).read_bytes())
    dependencies.update(Path(item["path"]) for item in acquisition["retained_files"])
    for relative in sorted(dependencies):
        _copy(root, initial, relative)
    original_receipt_rel = BATCH.parent / f"{work_id}-bsb829-initial.json"
    target = acceptance._io_path(initial / original_receipt_rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(acceptance._io_path(initial_receipt), target)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    source_tree = etree.parse(str(acceptance._io_path(root / SOURCE)), parser)
    volume = source_tree.getroot().find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body/{http://www.tei-c.org/ns/1.0}div")
    division = list(volume)[SELECTED[work_id][0] - 1]
    words = " ".join(" ".join(division.itertext()).split()).split()
    clause = " ".join(words[20:28])
    if len(clause) < 20:
        raise PipelineError("Latin source clause is too short")
    language.SOURCE = SOURCE
    language.SOURCE_SHA = SOURCE_SHA
    language.PROSE_CLAUSES = {work_id: clause}
    language.STAGE_RECEIPTS = {work_id: original_receipt_rel.name}
    original_copy = language._copy

    def copy_bsb829(source_root: Path, target_root: Path, relative: Path) -> None:
        if relative == Path("raw/openmgh/bsb00000752/acquisition-receipt.json"):
            relative = SOURCE.parent.parent / "acquisition-receipt.json"
        original_copy(source_root, target_root, relative)

    final = scratch / "final"
    final.mkdir()
    try:
        language._copy = copy_bsb829
        language_result = language._prepare_one(initial, final, work_id, source_tree,
                                                category=category)
    finally:
        language._copy = original_copy
    work = Path("library/works") / work_id
    edition = (work / "forms" / f"{work_id}-openmgh-retained" / "editions"
               / f"{work_id}-openmgh-electronic")
    accepted = validate_acceptance(final / edition / "acceptance.json", root=final)
    validate_state(final / work / "state.json", root=final)
    projector = project_accepted_poetry if category == "poetry" else project_accepted_prose
    checker = verify_accepted_poetry if category == "poetry" else verify_accepted_prose
    projected = projector(acceptance._io_path(final),
                          acceptance_path=acceptance._io_path(final / edition / "acceptance.json"))
    errors = checker(acceptance._io_path(final),
                     acceptance_path=acceptance._io_path(final / edition / "acceptance.json"),
                     rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"actual-master {category} projection failed: {errors[:3]}")
    result = {
        "contract": CONTRACT, "status": "staged-only", "work_id": work_id,
        "canonical_root": root.as_posix(), "stage_root": final.as_posix(),
        "original_inspection_receipt": BATCH.as_posix(),
        "original_inspection_receipt_sha256": BATCH_SHA,
        "original_candidate_sha256": entries[0]["candidate_sha256"],
        "original_candidate_tei_sha256": entries[0]["candidate_tei_sha256"],
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
        "source_manifest_before_sha256": _sha(root / manifest_rel),
        "source_manifest_after_sha256": _sha(final / manifest_rel),
        "manifest_path": manifest_rel.as_posix(),
        "profile_path": (manifest_rel.parent / "reconstruction-profile.json").as_posix(),
        "profile_before_sha256": _sha(root / manifest_rel.parent / "reconstruction-profile.json"),
        "profile_after_sha256": _sha(final / manifest_rel.parent / "reconstruction-profile.json"),
        "before": acceptance._files(root / work), "after": acceptance._files(final / work),
        "acceptance_sha256": _sha(final / edition / "acceptance.json"),
        "accepted_master_sha256": accepted["promotion"]["master"]["sha256"],
        "category": category, "language": "la", "projection_rows": 1,
        "projection_status": "independent-check-pass", "language_rebind": language_result,
        "installation": "not-performed",
    }
    acceptance._put_json(receipt.parent, Path(receipt.name), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(SELECTED))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.work_id, args.scratch, args.receipt)
    print(json.dumps({"work_id": result["work_id"], "master": result["accepted_master_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
