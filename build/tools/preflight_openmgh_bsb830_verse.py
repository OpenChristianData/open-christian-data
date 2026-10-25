"""Independently preflight the complete bsb830 flat-verse work stage."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from lxml import etree

from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import (
    project_accepted_prose, verify_accepted_prose,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"JSON object required: {path}")
    return result


def _check_flat_verse(record: dict) -> None:
    """Corroborate the native verse carrier without inferring TEI lines."""
    if record.get("work_id") != "verses-on-ring-staff-sword-and-crown":
        raise PipelineError("flat-verse stage names a different work")
    source = Path(record["canonical_root"]) / record["source_path"]
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(_io_path(source).read_bytes(), parser=parser)
    tei = "{http://www.tei-c.org/ns/1.0}"
    body = root.find(f"{tei}text/{tei}body")
    if body is None or len(body) != 1 or len(body[0]) != 29:
        raise PipelineError("bsb830 native volume envelope differs")
    selected = body[0][27]
    if (selected.tag != f"{tei}div" or selected.get("type") != "work"
            or selected.get("n") != "De anulo baculo gladio et diademate versus"
            or len(selected) != 1 or selected[0].tag != f"{tei}ab"):
        raise PipelineError("verse is not its complete flat source division")
    counts = {name: len(selected.findall(f".//{tei}{name}")) for name in ("pb", "lb", "lg", "l")}
    if counts != {"pb": 3, "lb": 80, "lg": 0, "l": 0}:
        raise PipelineError("flat verse milestones or line grouping changed")
    digest = hashlib.sha256(etree.tostring(selected, method="c14n", with_comments=True)).hexdigest()
    if digest != "0da3901f59a99854c374d99c2e33188b119d4bb79b1ff00df0b3f57ae26af285":
        raise PipelineError("complete native verse division changed")
    words = " ".join(" ".join(selected.itertext()).split())
    if (not words.startswith("DE ANULO BACULO GLADIO DIADEMATE VERSUS.")
            or not words.endswith("Una sed potius vero sub amore ligantur.")):
        raise PipelineError("native verse opening or ending changed")


@cached_edition_lookups()
def preflight(receipt: Path) -> dict:
    record = _read(receipt.resolve(strict=True))
    if record.get("contract") not in {
        "ocd-openmgh-bsb830-derived-acceptance-stage-v1",
        "ocd-openmgh-gesta-derived-acceptance-stage-v1",
        "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1",
        "ocd-openmgh-bsb752-next-prose-stage-v1",
        "ocd-openmgh-bsb750-next-prose-stage-v1",
        "ocd-openmgh-bsb828-next-prose-stage-v1",
    } or record.get("status") != "staged-only":
        raise PipelineError("unrecognized stage receipt")
    if (record["contract"] == "ocd-openmgh-gesta-derived-acceptance-stage-v1"
            and record.get("work_id") != "gesta-domni-lantberti"):
        raise PipelineError("Gesta stage contract is work-specific")
    if record["contract"] == "ocd-openmgh-bsb752-next-prose-stage-v1":
        if (record.get("work_id") not in {
            "passio-sancti-germani-grandivallensis", "passio-sancti-praeiecti",
            "passio-sanctorum-kiliani-et-sociorum", "revelatio-beati-baronti",
            "transitus-sancti-condedi", "vita-beati-audoini",
            "vita-sanctae-sadalbergae", "vita-sancti-ermenlandi",
            "vita-sancti-frodoberti", "vita-sancti-memmii",
            "vita-sancti-menelei", "vita-sancti-wandregiseli",
        } or record.get("source_path") != "raw/openmgh/bsb00000752/tei/bsb00000752.xml"):
            raise PipelineError("752 next stage is outside the inspected family")
    if record["contract"] == "ocd-openmgh-bsb750-next-prose-stage-v1":
        if (record.get("work_id") not in {
            "passio-sancti-memorii", "passio-sancti-quirini-tegernseensis",
            "vita-sanctae-genovefae", "vita-sancti-apollinaris-valentinensis",
            "vita-sancti-aviti", "vita-sancti-carileffi", "vita-sancti-dalmatii",
            "vita-sancti-eptadii", "vita-sancti-gaugerici", "vita-sancti-iuniani",
            "vita-sancti-melanii", "vita-sancti-viviani-santonensis",
        } or record.get("source_path") != "raw/openmgh/bsb00000750/tei/bsb00000750.xml"
                or record.get("original_inspection_receipt") !=
                "plans/2026-09-22-source-preflight/openmgh-bsb00000750-child-batch-20260926.json"
                or record.get("original_inspection_receipt_sha256") !=
                "e8ab12a76f25a23310824785ddd39513154a70c90d374d224f82e8f4eeae2954"):
            raise PipelineError("750 next stage is outside the pinned inspected family")
    if record["contract"] == "ocd-openmgh-bsb828-next-prose-stage-v1":
        from build.tools.stage_openmgh_bsb828_next import BATCH, LATIN_CLAUSES, SOURCE
        from build.tools.stage_openmgh_inspected_acceptance import PINNED_INSPECTED_BATCHES
        if (record.get("work_id") not in LATIN_CLAUSES
                or record.get("source_path") != SOURCE.as_posix()
                or record.get("original_inspection_receipt") != BATCH.as_posix()
                or record.get("original_inspection_receipt_sha256") != PINNED_INSPECTED_BATCHES[BATCH]):
            raise PipelineError("828 next stage is outside the pinned inspected family")
    if record["contract"] == "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1":
        _check_flat_verse(record)
    root = Path(record["canonical_root"]).resolve(strict=True)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("stage overlaps canonical repository")
    work_id = record["work_id"]
    work = Path("library/works") / work_id
    if (_files(root / work) != record["before"] or
            _files(stage / work) != record["after"]):
        raise PipelineError("canonical or staged work generation changed")
    inspection = Path(record["original_inspection_receipt"])
    source = Path(record["source_path"])
    if (_sha(root / inspection) != record["original_inspection_receipt_sha256"]
            or _sha(root / source) != record["source_sha256"]
            or _sha(stage / source) != record["source_sha256"]):
        raise PipelineError("inspected receipt or retained extracted XML changed")
    original = _read(root / inspection)
    entries = [item for item in original["works"] if item["work_id"] == work_id]
    if record["contract"] == "ocd-openmgh-bsb750-next-prose-stage-v1":
        from build.tools.stage_openmgh_inspected_acceptance import _normalize_entry
        entries = [_normalize_entry(original, item) for item in entries]
    if len(entries) != 1 or entries[0]["candidate_sha256"] != record["original_candidate_sha256"]:
        raise PipelineError("inspected candidate identity changed")
    original_package = CandidatePackage.load(Path(entries[0]["candidate_root"]) / "package")
    if (original_package.sha256 != record["original_candidate_sha256"] or
            _sha(Path(entries[0]["candidate_root"]) / "package/content.tei.xml") != record["original_candidate_tei_sha256"]):
        raise PipelineError("inspected candidate bytes changed")
    manifest_rel = Path(record["manifest_path"])
    profile_rel = Path(record["profile_path"])
    if (_sha(root / manifest_rel) != record["source_manifest_before_sha256"]
            or _sha(stage / manifest_rel) != record["source_manifest_after_sha256"]):
        raise PipelineError("source manifest rebind changed")
    if (_sha(root / profile_rel) != record["profile_before_sha256"]
            or _sha(stage / profile_rel) != record["profile_after_sha256"]):
        raise PipelineError("source profile rebind changed")
    manifest = SourceManifest.load(stage / manifest_rel, repository_root=stage)
    profile = _read(stage / profile_rel)
    acquisition = work / "forms" / f"{work_id}-openmgh-retained" / "editions" / f"{work_id}-openmgh-electronic" / "acquisitions" / f"{work_id}-openmgh-acquired.json"
    if profile["acquisition_sha256"] != _sha(stage / acquisition):
        raise PipelineError("source profile is not bound to staged acquisition")
    acquired = _read(stage / acquisition)
    if acquired["source_path"] != source.as_posix() or acquired["source_sha256"] != record["source_sha256"]:
        raise PipelineError("archive package became source authority")
    oracle_path = stage / manifest.record["validator"]["implementation_path"]
    spec = importlib.util.spec_from_file_location("ocd_bsb830_preflight_oracle", oracle_path)
    if spec is None or spec.loader is None:
        raise PipelineError("staged oracle cannot be loaded")
    oracle_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oracle_module)
    integration = work / "integration/openmgh-language-rebind-v1"
    package = CandidatePackage.load(stage / integration / "package")
    oracle = validate(manifest, package, oracle_module._oracle)
    prior = _read(stage / integration / "oracle-validation.json")
    if oracle.status != "pass" or oracle.findings or prior["report_sha256"] != oracle.sha256:
        raise PipelineError("current independent source oracle changed")
    edition = acquisition.parent.parent
    acceptance = edition / "acceptance.json"
    master = edition / "master.tei.xml"
    accepted = validate_acceptance(stage / acceptance, root=stage)
    validate_state(stage / work / "state.json", root=stage)
    if (accepted["identity"]["work_id"] != work_id
            or accepted["promotion"]["master"]["sha256"] != record["accepted_master_sha256"]
            or _sha(stage / master) != record["accepted_master_sha256"]):
        raise PipelineError("promoted acceptance/master differs")
    original_text = original_package.member_bytes("content.tei.xml")
    master_text = _io_path(stage / master).read_bytes()
    if master_text.split(b"</teiHeader>", 1)[1] != original_text.split(b"</teiHeader>", 1)[1]:
        raise PipelineError("accepted master body differs from inspected TEI")
    work_record = _read(stage / work / "work.json")
    editions = [e for f in work_record["textual_forms"] for e in f["editions"]
                if e["edition_id"] == accepted["identity"]["edition_id"]]
    category = "poetry" if record["contract"] == "ocd-openmgh-bsb830-flat-ab-poetry-stage-v1" else "prose"
    if len(editions) != 1 or editions[0].get("language") != "la" or editions[0].get("category") != category:
        raise PipelineError("edition language or category differs")
    if category == "poetry":
        from ocd_kernel.projection.categories.poetry import (
            project_accepted_poetry, verify_accepted_poetry,
        )
        projected = project_accepted_poetry(_io_path(stage),
                                            acceptance_path=_io_path(stage / acceptance))
        verify_projection = verify_accepted_poetry
    else:
        projected = project_accepted_prose(_io_path(stage),
                                           acceptance_path=_io_path(stage / acceptance))
        verify_projection = verify_accepted_prose
    errors = verify_projection(_io_path(stage), acceptance_path=_io_path(stage / acceptance),
                               rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != record["projection_rows"]:
        raise PipelineError(f"actual-master projection changed: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": work_id,
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": len(projected["rows"]), "installation": "not-performed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    print(json.dumps(preflight(args.receipt), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
