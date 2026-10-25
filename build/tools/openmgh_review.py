"""Shared operations for existing review commands."""

from __future__ import annotations

from ocd_kernel.tei.install_accepted import _files, _io_path

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.validate import validate_file
import json
from pathlib import Path


def load_bound_work(root: Path, work_id: str, *, PACKAGE, SOURCE, SOURCE_SHA256, _read) -> tuple[dict, dict, Path, Path]:
    work_path = Path("library/works") / work_id / "work.json"
    work = _read(root / work_path)
    if work.get("work_id") != work_id or len(work.get("textual_forms", [])) != 1:
        raise ValueError(f"work identity changed: {work_id}")
    form = work["textual_forms"][0]
    if len(form["editions"]) != 1:
        raise ValueError(f"edition identity ambiguous: {work_id}")
    edition = form["editions"][0]
    if len(edition["acquisition_ids"]) != 1:
        raise ValueError(f"acquisition identity ambiguous: {work_id}")
    acquisition_path = (work_path.parent / "forms" / form["textual_form_id"] / "editions"
                        / edition["edition_id"] / "acquisitions"
                        / f"{edition['acquisition_ids'][0]}.json")
    acquisition = _read(root / acquisition_path)
    if (acquisition.get("source_path") != SOURCE.as_posix()
            or acquisition.get("source_sha256") != SOURCE_SHA256
            or len(acquisition.get("retained_files", [])) != 2
            or acquisition["retained_files"][0].get("path") != PACKAGE.as_posix()
            or acquisition["retained_files"][1].get("path") != SOURCE.as_posix()):
        raise ValueError(f"extracted-XML text authority changed: {work_id}")
    return work, acquisition, work_path, acquisition_path


def preflight(work_id: str, *, ROOT, _frozen, _read, _sha, _work_pin, check, source, staging) -> dict:
    frozen = _frozen()
    pin, stage, record = _work_pin(frozen, work_id)
    if ROOT.resolve(strict=True) in stage.resolve(strict=True).parents:
        raise PipelineError("bsb830 stage overlaps checkout")
    work = Path("library/works") / work_id
    before, after = _files(ROOT / work), _files(stage / work)
    if before != record["before"] or after != record["after"] or len(before) != 3:
        raise PipelineError("bsb830 canonical or staged work generation changed")
    allowed = {"work.json", "state.json", "SOURCE_CREDIT.md"}
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if relative in allowed or relative.startswith("forms/") and relative.endswith(("/master.tei.xml", "/acceptance.json", "/README.source.md")):
            continue
        if relative.startswith("integration/" + staging.EVIDENCE + "/") and relative not in before:
            continue
        raise PipelineError(f"bsb830 unrelated work path differs: {relative}")
    old_work, new_work = _read(ROOT / work / "work.json"), _read(stage / work / "work.json")
    expected = json.loads(json.dumps(old_work))
    if len(expected.get("textual_forms", [])) != 1 or len(expected["textual_forms"][0].get("editions", [])) != 1:
        raise PipelineError("bsb830 work has ambiguous edition")
    edition_expected = expected["textual_forms"][0]["editions"][0]
    if edition_expected.get("language") or edition_expected.get("category"):
        raise PipelineError("bsb830 work category/language already assigned")
    edition_expected.update(language="la", category="prose")
    if expected != new_work:
        raise PipelineError("bsb830 work identity changed beyond native fields")
    validate_identity_update(old_work, new_work)
    load_work(_io_path(stage / work / "work.json"))
    acquisition_rel = next(Path(name) for name in before if name.endswith(".json") and name not in {"work.json", "state.json"})
    acquisition = _read(ROOT / work / acquisition_rel)
    if (_sha(stage / work / acquisition_rel) != before[acquisition_rel.as_posix()]
            or acquisition.get("source_path") != source.SOURCE.as_posix()
            or acquisition.get("source_sha256") != source.SOURCE_SHA
            or {item["path"] for item in acquisition.get("retained_files", [])} != {source.SOURCE.as_posix(), source.PACKAGE.as_posix()}):
        raise PipelineError("bsb830 staged acquisition/source authority differs")
    for relative, digest in ((source.SOURCE, source.SOURCE_SHA), (source.PACKAGE, source.PACKAGE_SHA),
                             (source.ACQUISITION_RECEIPT, source.ACQUISITION_RECEIPT_SHA)):
        if _sha(stage / relative) != digest:
            raise PipelineError("bsb830 staged source/package evidence differs")
    direct = _read(staging.DIRECT / "receipt.json")
    matches = [item for item in direct["selected_works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("bsb830 direct candidate identity differs")
    entry = matches[0]
    if (_sha(Path(entry["candidate_path"])) != entry["candidate_sha256"]
            or _sha(staging.REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
        raise PipelineError("bsb830 candidate reproduction differs")
    source_bytes, _, _ = source._source()
    index, ordinals = source.SELECTIONS[work_id]
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    oracle = check(source_bytes, candidate, old_work, acquisition)
    if (oracle != entry["oracle"] or oracle["source_part_c14n_sha256"] != pin["source_part_c14n_sha256"]
            or oracle["source_start_id"] != entry["oracle"]["source_start_id"] or oracle["source_end_id"] != entry["oracle"]["source_end_id"]):
        raise PipelineError("bsb830 source-part oracle or catalog locators differ")
    form = new_work["textual_forms"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / edition_expected["edition_id"]
    acceptance_path, master_path = edition / "acceptance.json", edition / "master.tei.xml"
    if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
        raise PipelineError("bsb830 canonical accepted master already exists")
    accepted = validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    master_bytes = _io_path(stage / master_path).read_bytes()
    if (_sha(stage / master_path) != pin["accepted_master_sha256"]
            or _sha(stage / acceptance_path) != pin["acceptance_sha256"]
            or accepted["promotion"]["master"]["sha256"] != pin["accepted_master_sha256"]
            or master_bytes.split(b"</teiHeader>", 1)[1] != candidate.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("bsb830 accepted master changed source body")
    if errors := validate_file(_io_path(stage / master_path)):
        raise PipelineError(f"bsb830 staged master XSD failed: {errors[:3]}")
    credit = _io_path(stage / work / "SOURCE_CREDIT.md").read_bytes()
    if (b"Monumenta Germaniae Historica" not in credit
            or _io_path(stage / edition / "README.source.md").read_bytes() != credit):
        raise PipelineError("bsb830 visible electronic source credit differs")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"bsb830 staged native row differs: {errors[:3]}")
    return dict(status="ready-for-review", work_id=work_id, source_work_div_index=index,
                source_part_indexes=list(ordinals), before_files=len(before), after_files=len(after),
                projection_rows=1, stage_receipt=(stage / "stage-receipt.json").as_posix(), installation="not-performed")


def work_pin(frozen: dict, work_id: str, *, _read, _sha, source, staging) -> tuple[dict, Path, dict]:
    matches = [item for item in frozen["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("bsb830 work absent or repeated in freeze")
    pin = matches[0]
    stage = Path(pin["stage_root"])
    receipt = stage / "stage-receipt.json"
    if _sha(receipt) != pin["stage_receipt_sha256"] or _files(stage) != pin["stage_files"]:
        raise PipelineError("bsb830 complete stage file set differs")
    record = _read(receipt)
    if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed" or record.get("work_id") != work_id
            or record.get("projection_rows") != 1 or record.get("direct_receipt_sha256") != staging.DIRECT_SHA
            or record.get("source_part_indexes") != list(source.SELECTIONS[work_id][1])):
        raise PipelineError("bsb830 staged work receipt differs")
    return pin, stage, record
