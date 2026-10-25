"""Prepare one complete source-checked bsb00000830 flat-verse acceptance.

The historical inspection remains immutable. Each derived candidate is rebuilt
in a sparse fixture with the current oracle import closure, then accepted in an
isolated generation. A second staged rebind adds source-evidenced Latin and
renews the manifest/profile against the accepted work and acquisition bytes.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree

from build.tools import stage_openmgh_language_rebind as language
from build.tools import stage_openmgh_inspected_acceptance as stage
from build.tools.stage_openmgh_inspected_acceptance import (
    _files, _io_path, _put_json, prepare as prepare_acceptance, preflight,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import (
    project_accepted_prose, verify_accepted_prose,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/openmgh/bsb00000830/tei/bsb00000830.xml")
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
BATCH = Path("plans/2026-09-22-source-preflight/openmgh-bsb830-verse-inspected-20260927.json")
BATCH_SHA = "7068b354e8cb6d5e1b34b6a541d5070ecdca9020c59467598525b39400da8a29"
BATCH_750 = Path("plans/2026-09-22-source-preflight/openmgh-bsb00000750-child-batch-20260926.json")
BATCH_750_SHA = "e8ab12a76f25a23310824785ddd39513154a70c90d374d224f82e8f4eeae2954"
CATEGORY = "poetry"
IDS = {
    "verses-on-ring-staff-sword-and-crown": "Iam tot in ecclesias insurrexere procellae",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


def _copy(root: Path, fixture: Path, relative: Path) -> None:
    source, target = _io_path(root / relative), _io_path(fixture / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _closure(root: Path, policy: dict) -> str:
    entries = [
        {"path": p, "sha256": _sha(root / p)} for p in policy["closure_inputs"]
    ]
    data = (json.dumps(entries, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(data).hexdigest()


def prepare(root: Path, work_id: str, scratch: Path, receipt: Path) -> dict:
    if work_id not in IDS:
        raise PipelineError(f"work is outside this inspected tranche: {work_id}")
    root = root.resolve(strict=True)
    scratch, receipt = scratch.absolute(), receipt.absolute()
    if _io_path(scratch).exists() or _io_path(receipt).exists():
        raise PipelineError("scratch and receipt must be fresh")
    if root == scratch or root in scratch.parents or not _io_path(scratch.parent).is_dir():
        raise PipelineError("scratch must be outside the repository with an existing parent")
    if _sha(root / SOURCE) != SOURCE_SHA:
        raise PipelineError("extracted source XML changed")
    if _sha(root / BATCH) != BATCH_SHA:
        raise PipelineError("verse inspected batch receipt changed")
    batch = _read(root / BATCH)
    if batch.get("contract") == "ocd-openmgh-bsb00000750-child-batch-v1":
        if BATCH != BATCH_750 or _sha(root / BATCH) != BATCH_750_SHA:
            raise PipelineError("original 750 inspection receipt is not pinned")
        batch = copy.deepcopy(batch)
        batch["works"] = [stage._normalize_entry(batch, item) for item in batch["works"]]
        for item in batch["works"]:
            for legacy in ("boundary_path", "boundary_sha256", "candidate_digest",
                           "candidate_manifest_sha256", "source_work_div_n",
                           "source_work_div_ordinal"):
                item.pop(legacy, None)
    if batch.get("contract") in {
        "ocd-openmgh-bsb752-inspected-batch-v1",
        "ocd-openmgh-bsb752-remaining-six-v1",
        "ocd-openmgh-bsb828-inspected-batch-v1",
    }:
        if _sha(root / BATCH) != stage.PINNED_INSPECTED_BATCHES.get(BATCH):
            raise PipelineError("original inspection receipt is not pinned")
    selected = [w for w in batch["works"] if w.get("work_id") == work_id]
    if len(selected) != 1:
        raise PipelineError("inspected work entry is not unique")
    old = selected[0]
    work = Path("library/works") / work_id
    manifest_rel = Path("sources/openmgh-exclusive") / work_id / "source-manifest.json"
    declaration_rel = manifest_rel.parent / "acceptance-declaration.json"
    original_manifest = _read(root / manifest_rel)
    policy = _read(root / "sources/openmgh-exclusive/validation-policy.json")
    boundary = _read(root / manifest_rel.parent / "boundary-review.json")
    if boundary["review_status"] != "agent-inspected-source-boundary" or boundary["scope_assertion"] != "whole-work-div":
        raise PipelineError("source work boundary is not inspected")
    if _sha(root / Path(old["boundary_review_path"])) != old["boundary_review_sha256"]:
        raise PipelineError("inspected boundary hash changed")
    original_candidate = CandidatePackage.load(Path(old["candidate_root"]) / "package")
    if original_candidate.sha256 != old["candidate_sha256"]:
        raise PipelineError("inspected candidate hash changed")
    scratch.mkdir()
    fixture = scratch / "fixture"
    fixture.mkdir()
    shutil.copytree(_io_path(root / work), _io_path(fixture / work))
    dependencies = {SOURCE, BATCH, declaration_rel, manifest_rel,
                    Path("sources/openmgh-exclusive/validation-policy.json")}
    dependencies.update(Path(item["path"]) for item in original_manifest["authorities"])
    dependencies.update(Path(original_manifest[key]["implementation_path"])
                        for key in ("converter", "validator"))
    dependencies.add(Path(original_manifest["package_schema"]["path"]))
    dependencies.update(Path(p) for p in policy["closure_inputs"])
    acquisition = _read(root / Path(old["acquisition_path"]))
    dependencies.update(Path(item["path"]) for item in acquisition["retained_files"])
    dependencies.add(SOURCE.parent.parent / "acquisition-receipt.json")
    dependencies.update({Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"),
                         Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd")})
    for relative in sorted(dependencies):
        if not relative.is_relative_to(work):
            _copy(root, fixture, relative)
    refreshed_manifest = copy.deepcopy(original_manifest)
    old_closure = refreshed_manifest["validator"]["import_closure_sha256"]
    refreshed_manifest["validator"]["import_closure_sha256"] = _closure(fixture, policy)
    # New candidates may already bind the current oracle closure. The older
    # bsb830 tranches required a refresh; equality here is still exact proof.
    _put_json(fixture, manifest_rel, refreshed_manifest)
    manifest = SourceManifest.load(fixture / manifest_rel, repository_root=fixture)
    candidate = scratch / "refreshed-candidate"
    subprocess.run(
        [sys.executable, "-m", "build.tools.reconstruct_candidate", "--manifest",
         manifest_rel.as_posix(), "--destination", str(candidate),
         "--repository-root", str(fixture)], cwd=root, check=True,
        capture_output=True, text=True,
    )
    package = CandidatePackage.load(candidate / "package")
    validation = _read(candidate / "validation.json")
    if (validation.get("status") != "pass" or validation.get("findings") != []
            or validation.get("source_manifest_sha256") != manifest.sha256
            or package.member_bytes("content.tei.xml") != original_candidate.member_bytes("content.tei.xml")):
        raise PipelineError("refreshed source oracle or exact text conservation failed")
    derived = copy.deepcopy(batch)
    entry = next(w for w in derived["works"] if w["work_id"] == work_id)
    entry.update(manifest_sha256=manifest.sha256, candidate_sha256=package.sha256,
                 candidate_root=candidate.as_posix(),
                 validation_sha256=_sha(candidate / "validation.json"))
    derived_batch = BATCH.parent / f"{work_id}-derived-closure-batch.json"
    _put_json(fixture, derived_batch, derived)
    derived_pin = None
    if batch.get("contract") in {
        "ocd-openmgh-bsb752-inspected-batch-v1",
        "ocd-openmgh-bsb752-remaining-six-v1",
        "ocd-openmgh-bsb828-inspected-batch-v1",
    }:
        derived_pin = _sha(fixture / derived_batch)
    initial = scratch / "initial-acceptance"
    initial_receipt = scratch / "initial-acceptance-receipt.json"
    oracle_path = fixture / original_manifest["validator"]["implementation_path"]
    spec = importlib.util.spec_from_file_location("ocd_bsb830_fixture_oracle", oracle_path)
    if spec is None or spec.loader is None:
        raise PipelineError("cannot load fixture-local oracle")
    fixture_oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_oracle)
    original_oracle = stage._oracle
    try:
        stage._oracle = fixture_oracle._oracle
        if derived_pin is not None:
            stage.PINNED_INSPECTED_BATCHES[derived_batch] = derived_pin
        prepare_acceptance(fixture, declaration_rel, derived_batch, initial, initial_receipt)
        preflight(initial_receipt)
    finally:
        stage._oracle = original_oracle
        if derived_pin is not None:
            stage.PINNED_INSPECTED_BATCHES.pop(derived_batch, None)
    # The metadata rebind reads the original stage receipt and current closure
    # dependencies from its input root. They are copied without changing that
    # accepted generation's work or source bytes.
    language_receipt_name = f"{work_id}-derived-initial.json"
    language_receipt_rel = BATCH.parent / language_receipt_name
    _copy(fixture, initial, Path("ocd_kernel/reconstruction/contract.py"))
    for relative in sorted(dependencies):
        if not _io_path(initial / relative).is_file():
            _copy(fixture, initial, relative)
    target = _io_path(initial / language_receipt_rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(initial_receipt), target)
    language.SOURCE = SOURCE
    language.SOURCE_SHA = SOURCE_SHA
    language.IDS = (work_id,)
    language.PROSE_CLAUSES = {work_id: IDS[work_id]}
    language.STAGE_RECEIPTS = {work_id: language_receipt_name}
    final = scratch / "final-acceptance"
    final.mkdir()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    source_tree = etree.parse(str(_io_path(root / SOURCE)), parser)
    original_copy = language._copy
    def copy_current_volume(source_root: Path, target_root: Path, relative: Path) -> None:
        if relative == Path("raw/openmgh/bsb00000752/acquisition-receipt.json"):
            relative = SOURCE.parent.parent / "acquisition-receipt.json"
        original_copy(source_root, target_root, relative)
    try:
        language._copy = copy_current_volume
        language_result = language._prepare_one(initial, final, work_id, source_tree,
                                                category=CATEGORY)
    finally:
        language._copy = original_copy
    acceptance = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic" / "acceptance.json"
    accepted = validate_acceptance(final / acceptance, root=final)
    validate_state(final / work / "state.json", root=final)
    current_manifest = SourceManifest.load(final / manifest_rel, repository_root=final)
    if CATEGORY == "poetry":
        from ocd_kernel.projection.categories.poetry import (
            project_accepted_poetry, verify_accepted_poetry,
        )
        projected = project_accepted_poetry(_io_path(final),
                                            acceptance_path=_io_path(final / acceptance))
        verify_projection = verify_accepted_poetry
    else:
        projected = project_accepted_prose(_io_path(final),
                                           acceptance_path=_io_path(final / acceptance))
        verify_projection = verify_accepted_prose
    errors = verify_projection(_io_path(final), acceptance_path=_io_path(final / acceptance),
                               rows=projected["rows"], receipt=projected["receipt"])
    if errors or not projected["rows"]:
        raise PipelineError(f"actual-master projection failed: {errors[:3]}")
    before, after = _files(root / work), _files(final / work)
    result = {
        "contract": ("ocd-openmgh-gesta-derived-acceptance-stage-v1"
                     if work_id == "gesta-domni-lantberti" else
                     "ocd-openmgh-bsb828-next-prose-stage-v1"
                     if SOURCE == Path("raw/openmgh/bsb00000828/tei/bsb00000828.xml") else
                     "ocd-openmgh-bsb752-next-prose-stage-v1"
                     if SOURCE == Path("raw/openmgh/bsb00000752/tei/bsb00000752.xml") else
                     "ocd-openmgh-bsb750-next-prose-stage-v1"
                     if SOURCE == Path("raw/openmgh/bsb00000750/tei/bsb00000750.xml") else
                     "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1"
                     if CATEGORY == "poetry" else
                     "ocd-openmgh-bsb830-derived-acceptance-stage-v1"),
        "status": "staged-only", "work_id": work_id,
        "canonical_root": root.as_posix(), "stage_root": final.as_posix(),
        "original_inspection_receipt": BATCH.as_posix(),
        "original_inspection_receipt_sha256": _sha(root / BATCH),
        "original_candidate_sha256": old["candidate_sha256"],
        "original_candidate_tei_sha256": old["candidate_tei_sha256"],
        "source_path": SOURCE.as_posix(), "source_sha256": SOURCE_SHA,
        "historical_oracle_closure_sha256": old_closure,
        "current_oracle_closure_sha256": current_manifest.record["validator"]["import_closure_sha256"],
        "source_manifest_before_sha256": _sha(root / manifest_rel),
        "source_manifest_after_sha256": current_manifest.sha256,
        "manifest_path": manifest_rel.as_posix(),
        "profile_path": (manifest_rel.parent / "reconstruction-profile.json").as_posix(),
        "profile_before_sha256": _sha(root / manifest_rel.parent / "reconstruction-profile.json"),
        "profile_after_sha256": _sha(final / manifest_rel.parent / "reconstruction-profile.json"),
        "before": before, "after": after,
        "acceptance_sha256": _sha(final / acceptance),
        "accepted_master_sha256": accepted["promotion"]["master"]["sha256"],
        "language": "la", "category": CATEGORY, "projection_rows": len(projected["rows"]),
        "projection_status": "independent-check-pass",
        "language_rebind": language_result,
        "installation": "not-performed",
    }
    _io_path(receipt.parent).mkdir(parents=True, exist_ok=True)
    _put_json(receipt.parent, Path(receipt.name), result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(IDS))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.root, args.work_id, args.scratch, args.receipt)
    print(json.dumps({k: result[k] for k in ("work_id", "status", "accepted_master_sha256",
                                                "projection_rows", "projection_status")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
