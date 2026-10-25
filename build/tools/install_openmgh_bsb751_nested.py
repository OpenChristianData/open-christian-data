"""Guarded bsb751 nested-part installer; default action is read-only preflight."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tools import prepare_openmgh_bsb751_nested as source
from build.tools import stage_openmgh_bsb751_nested as staging
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb751-nested-freeze-20260927.json"
FREEZE_SHA = "f528de9ce4a38a6b731e3e6eff2eb8400a8590547956e4aeb09898b89f54fd3f"
CONTRACT = "ocd-openmgh-bsb751-nested-freeze-v1"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _frozen() -> dict:
    if _sha(FREEZE) != FREEZE_SHA:
        raise PipelineError("bsb751 reviewed freeze changed")
    frozen = _read(FREEZE)
    if (frozen.get("contract") != CONTRACT or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("canonical_install") != "not-performed" or len(frozen.get("works", [])) != 10
            or {item["work_id"] for item in frozen["works"]} != set(source.SELECTIONS)
            or frozen.get("selected_parts") != 13 or len(frozen.get("held_parts", [])) != 3
            or len(frozen.get("other_source_divisions", [])) != 14
            or frozen.get("source_sha256") != source.SOURCE_SHA
            or frozen.get("package_sha256") != source.PACKAGE_SHA):
        raise PipelineError("bsb751 freeze scope or authority differs")
    if (Path(frozen["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True)
            or Path(frozen["stage_home"]).resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb751-nested-stages-20260927-v2").resolve(strict=True)):
        raise PipelineError("bsb751 frozen roots differ")
    for path, digest in ((source.SOURCE, source.SOURCE_SHA), (source.PACKAGE, source.PACKAGE_SHA),
                         (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)):
        if _sha(ROOT / path) != digest:
            raise PipelineError(f"bsb751 retained source/package/receipt differs: {path}")
    if _sha(Path(frozen["direct_receipt"])) != staging.DIRECT_SHA:
        raise PipelineError("bsb751 direct candidate receipt differs")
    return frozen


def _work_pin(frozen: dict, work_id: str) -> tuple[dict, Path, dict]:
    matches = [item for item in frozen["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("bsb751 work absent or repeated in freeze")
    pin = matches[0]
    stage = Path(frozen["stage_home"]) / work_id
    receipt = stage / "stage-receipt.json"
    if _sha(receipt) != pin["stage_receipt_sha256"] or _files(stage) != pin["stage_files"]:
        raise PipelineError("bsb751 complete stage file set differs")
    record = _read(receipt)
    if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed" or record.get("work_id") != work_id
            or record.get("projection_rows") != 1 or record.get("direct_receipt_sha256") != staging.DIRECT_SHA
            or record.get("source_part_indexes") != list(source.SELECTIONS[work_id][1])):
        raise PipelineError("bsb751 staged work receipt differs")
    return pin, stage, record


def preflight(work_id: str) -> dict:
    frozen = _frozen()
    pin, stage, record = _work_pin(frozen, work_id)
    if ROOT.resolve(strict=True) in stage.resolve(strict=True).parents:
        raise PipelineError("bsb751 stage overlaps checkout")
    work = Path("library/works") / work_id
    before, after = _files(ROOT / work), _files(stage / work)
    if before != record["before"] or after != record["after"] or len(before) != 3:
        raise PipelineError("bsb751 canonical or staged work generation changed")
    allowed = {"work.json", "state.json", "SOURCE_CREDIT.md"}
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if relative in allowed or relative.startswith("forms/") and relative.endswith(("/master.tei.xml", "/acceptance.json", "/README.source.md")):
            continue
        if relative.startswith("integration/" + staging.EVIDENCE + "/") and relative not in before:
            continue
        raise PipelineError(f"bsb751 unrelated work path differs: {relative}")
    old_work, new_work = _read(ROOT / work / "work.json"), _read(stage / work / "work.json")
    expected = json.loads(json.dumps(old_work))
    if len(expected.get("textual_forms", [])) != 1 or len(expected["textual_forms"][0].get("editions", [])) != 1:
        raise PipelineError("bsb751 work has ambiguous edition")
    edition_expected = expected["textual_forms"][0]["editions"][0]
    if edition_expected.get("language") or edition_expected.get("category"):
        raise PipelineError("bsb751 work category/language already assigned")
    edition_expected.update(language="la", category="prose")
    if expected != new_work:
        raise PipelineError("bsb751 work identity changed beyond native fields")
    validate_identity_update(old_work, new_work)
    load_work(_io_path(stage / work / "work.json"))
    acquisition_rel = next(Path(name) for name in before if name.endswith(".json") and name not in {"work.json", "state.json"})
    acquisition = _read(ROOT / work / acquisition_rel)
    if (_sha(stage / work / acquisition_rel) != before[acquisition_rel.as_posix()]
            or acquisition.get("source_path") != source.SOURCE.as_posix()
            or acquisition.get("source_sha256") != source.SOURCE_SHA
            or {item["path"] for item in acquisition.get("retained_files", [])} != {source.SOURCE.as_posix(), source.PACKAGE.as_posix()}):
        raise PipelineError("bsb751 staged acquisition/source authority differs")
    for relative, digest in ((source.SOURCE, source.SOURCE_SHA), (source.PACKAGE, source.PACKAGE_SHA),
                             (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)):
        if _sha(stage / relative) != digest:
            raise PipelineError("bsb751 staged source/package evidence differs")
    direct = _read(staging.DIRECT / "receipt.json")
    matches = [item for item in direct["selected_works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("bsb751 direct candidate identity differs")
    entry = matches[0]
    if (_sha(Path(entry["candidate_path"])) != entry["candidate_sha256"]
            or _sha(staging.REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
        raise PipelineError("bsb751 candidate reproduction differs")
    _, _, source_works = source._source()
    index, ordinals = source.SELECTIONS[work_id]
    original = [source_works[index][j] for j in ordinals]
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    oracle = source._check(original, candidate, source._locators(old_work, source.SOURCE))
    if (oracle != entry["oracle"] or oracle["source_part_c14n_sha256"] != pin["source_part_c14n_sha256"]
            or oracle["start_xml_id"] != pin["start_xml_id"] or oracle["end_xml_id"] != pin["end_xml_id"]):
        raise PipelineError("bsb751 source-part oracle or catalog locators differ")
    if (entry["catalog_locator_ids"] != pin["catalog_locator_ids"]
            or entry["ordered_source_locator_ids"] != pin["ordered_source_locator_ids"]
            or entry["locator_order_disposition"] != pin["locator_order_disposition"]):
        raise PipelineError("bsb751 literal or source-ordered catalog locator evidence differs")
    form = new_work["textual_forms"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / edition_expected["edition_id"]
    acceptance_path, master_path = edition / "acceptance.json", edition / "master.tei.xml"
    if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
        raise PipelineError("bsb751 canonical accepted master already exists")
    accepted = validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    master_bytes = _io_path(stage / master_path).read_bytes()
    if (_sha(stage / master_path) != pin["accepted_master_sha256"]
            or _sha(stage / acceptance_path) != pin["acceptance_sha256"]
            or accepted["promotion"]["master"]["sha256"] != pin["accepted_master_sha256"]
            or master_bytes.split(b"</teiHeader>", 1)[1] != candidate.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("bsb751 accepted master changed source body")
    if errors := validate_file(_io_path(stage / master_path)):
        raise PipelineError(f"bsb751 staged master XSD failed: {errors[:3]}")
    credit = _io_path(stage / work / "SOURCE_CREDIT.md").read_bytes()
    if (b"Monumenta Germaniae Historica" not in credit
            or _io_path(stage / edition / "README.source.md").read_bytes() != credit):
        raise PipelineError("bsb751 visible electronic source credit differs")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"bsb751 staged native row differs: {errors[:3]}")
    return dict(status="ready-for-review", work_id=work_id, source_work_div_index=index,
                source_part_indexes=list(ordinals), before_files=len(before), after_files=len(after),
                projection_rows=1, stage_receipt=(stage / "stage-receipt.json").as_posix(), installation="not-performed")


def install(work_id: str, *, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight(work_id)
    frozen = _frozen()
    pin, stage, record = _work_pin(frozen, work_id)
    work = Path("library/works") / work_id
    target = ROOT / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(stage / "stage-receipt.json") != pin["stage_receipt_sha256"]:
            raise PipelineError("bsb751 stage receipt changed under lock")
        preflight(work_id)
        return _commit_generation(ROOT, target, stage / work, work_id=work_id,
                                  before=record["before"], after=record["after"],
                                  existed=True, replacement=False,
                                  operation_kind="openmgh-bsb751-nested-initial-install",
                                  result_status="installed-and-validated", accepted_editions=1, fail_at=fail_at)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_id", choices=sorted(source.SELECTIONS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.work_id) if args.apply else preflight(args.work_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
