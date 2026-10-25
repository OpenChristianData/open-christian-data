"""Independently preflight one exact staged bsb829 electronic witness."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from build.tools.stage_openmgh_bsb829_inspected import BATCH, ROOT, SELECTED, SOURCE, SOURCE_SHA
from build.tools.stage_openmgh_bsb829_next import BATCH_SHA, CONTRACT
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.poetry import project_accepted_poetry, verify_accepted_poetry
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.validate import validate_file


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def preflight(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    work_id = record.get("work_id")
    if (record.get("contract") != CONTRACT or record.get("status") != "staged-only"
            or work_id not in SELECTED or record.get("category") != SELECTED[work_id][1]
            or record.get("language") != "la"):
        raise PipelineError("unrecognized bsb829 stage or work category")
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root != ROOT.resolve(strict=True) and not (root / BATCH).is_file():
        raise PipelineError("fixture has no bound inspection receipt")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage overlaps canonical root")
    if (record.get("original_inspection_receipt") != BATCH.as_posix()
            or record.get("original_inspection_receipt_sha256") != BATCH_SHA
            or record.get("source_path") != SOURCE.as_posix()
            or record.get("source_sha256") != SOURCE_SHA
            or _sha(root / BATCH) != BATCH_SHA
            or _sha(root / SOURCE) != SOURCE_SHA
            or _sha(stage / SOURCE) != SOURCE_SHA):
        raise PipelineError("pinned extracted XML or inspection receipt changed")
    work = Path("library/works") / work_id
    if _files(root / work) != record["before"] or _files(stage / work) != record["after"]:
        raise PipelineError("canonical or staged work generation changed")
    batch = _read(root / BATCH)
    entries = [row for row in batch["works"] if row.get("work_id") == work_id]
    if len(entries) != 1 or entries[0]["work_div_ordinal"] != SELECTED[work_id][0]:
        raise PipelineError("inspected work entry is absent or ambiguous")
    inspected = entries[0]
    original = CandidatePackage.load(Path(inspected["candidate_root"]) / "package")
    if (original.sha256 != record["original_candidate_sha256"]
            or _sha(Path(inspected["candidate_root"]) / "package/content.tei.xml")
            != record["original_candidate_tei_sha256"]):
        raise PipelineError("inspected candidate bytes changed")
    manifest_rel = Path(record["manifest_path"])
    profile_rel = Path(record["profile_path"])
    if (manifest_rel != Path(inspected["manifest_path"])
            or profile_rel != Path(inspected["profile_path"])
            or _sha(root / manifest_rel) != record["source_manifest_before_sha256"]
            or _sha(stage / manifest_rel) != record["source_manifest_after_sha256"]
            or _sha(root / profile_rel) != record["profile_before_sha256"]
            or _sha(stage / profile_rel) != record["profile_after_sha256"]):
        raise PipelineError("source manifest/profile generation changed")
    manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    profile = _read(stage / profile_rel)
    edition = (work / "forms" / f"{work_id}-openmgh-retained" / "editions"
               / f"{work_id}-openmgh-electronic")
    acquisition = edition / "acquisitions" / f"{work_id}-openmgh-acquired.json"
    if (profile["acquisition_sha256"] != _sha(stage / acquisition)
            or _read(stage / acquisition).get("source_path") != SOURCE.as_posix()):
        raise PipelineError("staged acquisition does not bind the extracted XML")
    oracle_path = stage / manifest.record["validator"]["implementation_path"]
    spec = importlib.util.spec_from_file_location("ocd_bsb829_preflight_oracle", oracle_path)
    if spec is None or spec.loader is None:
        raise PipelineError("staged oracle cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    integration = work / "integration/openmgh-language-rebind-v1"
    package = CandidatePackage.load(stage / integration / "package")
    oracle = validate(manifest, package, module._oracle)
    prior = _read(stage / integration / "oracle-validation.json")
    if oracle.status != "pass" or oracle.findings or prior["report_sha256"] != oracle.sha256:
        raise PipelineError("current independent source oracle changed")
    acceptance = validate_acceptance(stage / edition / "acceptance.json", root=stage)
    validate_state(stage / work / "state.json", root=stage)
    master = stage / edition / "master.tei.xml"
    master_bytes = _io_path(master).read_bytes()
    original_bytes = original.member_bytes("content.tei.xml")
    if (acceptance["identity"]["work_id"] != work_id
            or acceptance["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or _sha(master) != record["accepted_master_sha256"]
            or master_bytes.split(b"</teiHeader>", 1)[1]
            != original_bytes.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("actual master differs from inspected source work body")
    if errors := validate_file(_io_path(master)):
        raise PipelineError(f"actual master TEI P5 XSD failed: {errors[:3]}")
    work_record = _read(stage / work / "work.json")
    editions = [item for form in work_record["textual_forms"] for item in form["editions"]
                if item["edition_id"] == acceptance["identity"]["edition_id"]]
    if (len(editions) != 1 or editions[0].get("language") != "la"
            or editions[0].get("category") != record["category"]):
        raise PipelineError("staged language/category differs")
    projector = project_accepted_poetry if record["category"] == "poetry" else project_accepted_prose
    checker = verify_accepted_poetry if record["category"] == "poetry" else verify_accepted_prose
    projected = projector(_io_path(stage), acceptance_path=_io_path(stage / edition / "acceptance.json"))
    errors = checker(_io_path(stage), acceptance_path=_io_path(stage / edition / "acceptance.json"),
                     rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != record["projection_rows"] or len(projected["rows"]) != 1:
        raise PipelineError(f"actual-master projection changed: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": work_id,
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": 1, "installation": "not-performed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    print(json.dumps(preflight(args.receipt), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
