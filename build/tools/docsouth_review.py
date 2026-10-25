"""Shared operations for existing review commands."""

from __future__ import annotations

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.tei.validate import validate_file
import json
from hashlib import sha256
from pathlib import Path


def preflight(work_id: str, *, ROOT, _frozen, _read, _sha, _work_pin, check, direct_source, source, staging) -> dict:
    frozen = _frozen()
    pin, stage, record = _work_pin(frozen, work_id)
    if ROOT.resolve(strict=True) in stage.resolve(strict=True).parents:
        raise PipelineError("DocSouth stage overlaps checkout")
    work = Path("library/works") / work_id
    before, after = _files(ROOT / work), _files(stage / work)
    if before != record["before"] or after != record["after"] or len(before) != 3:
        raise PipelineError("DocSouth canonical or staged work generation changed")
    allowed = {"work.json", "state.json", "SOURCE_CREDIT.md"}
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if (relative in allowed or relative.startswith("forms/")
                and relative.endswith(("/master.tei.xml", "/acceptance.json", "/README.source.md"))):
            continue
        if relative.startswith("integration/" + staging.EVIDENCE + "/") and relative not in before:
            continue
        raise PipelineError(f"DocSouth unrelated work path differs: {relative}")
    old_work, new_work = _read(ROOT / work / "work.json"), _read(stage / work / "work.json")
    expected = json.loads(json.dumps(old_work))
    if len(expected.get("textual_forms", [])) != 1 or len(expected["textual_forms"][0].get("editions", [])) != 1:
        raise PipelineError("DocSouth work has ambiguous edition")
    edition_expected = expected["textual_forms"][0]["editions"][0]
    if edition_expected.get("language") or edition_expected.get("category"):
        raise PipelineError("DocSouth native fields already assigned")
    edition_expected.update(language="en", category="prose")
    if expected != new_work:
        raise PipelineError("DocSouth identity changed beyond native fields")
    validate_identity_update(old_work, new_work)
    load_work(_io_path(stage / work / "work.json"))
    direct = _read(staging.DIRECT / "receipt.json")
    matches = [item for item in direct["selected_works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("DocSouth direct source identity differs")
    entry = matches[0]
    if (entry["source_path"] != pin["source_path"] or entry["source_sha256"] != pin["source_sha256"]
            or entry["source_bytes"] != pin["source_bytes"]
            or entry["candidate_sha256"] != pin["direct_candidate_sha256"]
            or entry["producer"]["source_doctype"] != pin["source_doctype"]
            or entry["producer"]["source_rights_text_sha256"] != pin["source_rights_text_sha256"]
            or entry["producer"]["source_entity_declarations"] != pin["source_entity_declarations"]
            or entry["oracle"] != pin["source_oracle"]):
        raise PipelineError("DocSouth source/rights/entity pins differ")
    for rel, digest in ((entry["work_path"], entry["work_sha256"]),
                        (entry["state_path"], entry["state_sha256"]),
                        (entry["acquisition_path"], entry["acquisition_sha256"]),
                        (entry["acquisition_receipt_path"], pin["acquisition_receipt_sha256"]),
                        (entry["source_path"], pin["source_sha256"])):
        if _sha(ROOT / rel) != digest or _sha(stage / rel) != digest and rel not in (entry["work_path"], entry["state_path"]):
            raise PipelineError(f"DocSouth current/staged authority changed: {rel}")
    acquisition = _read(ROOT / entry["acquisition_path"])
    if (acquisition.get("source_path") != entry["source_path"]
            or acquisition.get("source_sha256") != entry["source_sha256"]
            or len(acquisition.get("retained_files", [])) != pin["source_entity_declarations"] + 1):
        raise PipelineError("DocSouth acquisition differs")
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    reproduced, producer = source.convert(work_id, selections=direct_source.SELECTIONS)
    if (sha256(candidate).hexdigest() != pin["direct_candidate_sha256"]
            or _sha(staging.REPRO / work_id / "candidate.tei.xml") != pin["direct_candidate_sha256"]
            or reproduced != candidate or producer != entry["producer"]):
        raise PipelineError("DocSouth candidate reproduction differs")
    if check(ROOT / entry["source_path"], pin["source_sha256"], candidate,
             ROOT / entry["acquisition_receipt_path"]) != pin["source_oracle"]:
        raise PipelineError("DocSouth independent source-tree/rights oracle differs")
    form = new_work["textual_forms"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / edition_expected["edition_id"]
    acceptance_path, master_path = edition / "acceptance.json", edition / "master.tei.xml"
    if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
        raise PipelineError("DocSouth canonical edition already accepted")
    accepted = validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    master = _io_path(stage / master_path).read_bytes()
    if (_sha(stage / master_path) != pin["accepted_master_sha256"]
            or _sha(stage / acceptance_path) != pin["acceptance_sha256"]
            or accepted["promotion"]["master"]["sha256"] != pin["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != candidate.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("DocSouth accepted master differs from source-bound body")
    if errors := validate_file(_io_path(stage / master_path)):
        raise PipelineError(f"DocSouth staged P5 XSD failed: {errors[:3]}")
    credit = _io_path(stage / work / "SOURCE_CREDIT.md").read_bytes()
    if (b"Documenting the American South" not in credit
            or _io_path(stage / edition / "README.source.md").read_bytes() != credit):
        raise PipelineError("DocSouth visible electronic source credit differs")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != pin["projection_rows"]:
        raise PipelineError(f"DocSouth actual-master native rows differ: {errors[:3]}")
    return dict(status="ready-for-review", work_id=work_id, before_files=len(before), after_files=len(after),
                source_sha256=pin["source_sha256"], source_entity_declarations=pin["source_entity_declarations"],
                source_rights_text_sha256=pin["source_rights_text_sha256"],
                projection_rows=len(projected["rows"]), stage_receipt=(stage / "stage-receipt.json").as_posix(),
                installation="not-performed")


def work_pin(frozen: dict, work_id: str, *, _read, _sha, staging) -> tuple[dict, Path, dict]:
    matches = [item for item in frozen["works"] if item["work_id"] == work_id]
    if len(matches) != 1:
        raise PipelineError("DocSouth work absent or repeated in freeze")
    pin = matches[0]
    stage = Path(frozen["stage_home"]) / work_id
    receipt = stage / "stage-receipt.json"
    if _sha(receipt) != pin["stage_receipt_sha256"] or _files(stage) != pin["stage_files"]:
        raise PipelineError("DocSouth complete stage differs")
    record = _read(receipt)
    if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed" or record.get("work_id") != work_id
            or record.get("source_sha256") != pin["source_sha256"]
            or record.get("source_rights_text_sha256") != pin["source_rights_text_sha256"]
            or record.get("source_entity_declarations") != pin["source_entity_declarations"]
            or record.get("source_oracle") != pin["source_oracle"]
            or record.get("projection_rows") != pin["projection_rows"]):
        raise PipelineError("DocSouth stage receipt differs")
    return pin, stage, record


def freeze(*, CONTRACT, FREEZE, ROOT, STAGE_HOME, _sha, direct_source, source, staging) -> None:
    if _io_path(FREEZE).exists():
        raise ValueError("DocSouth freeze already exists")
    if _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA:
        raise ValueError("DocSouth direct receipt differs")
    direct = json.loads(_io_path(staging.DIRECT / "receipt.json").read_bytes())
    entries = {item["work_id"]: item for item in direct["selected_works"]}
    if set(entries) != set(direct_source.SELECTIONS):
        raise ValueError("DocSouth selection differs")
    pins = []
    for work_id, entry in sorted(entries.items()):
        stage = STAGE_HOME / work_id
        receipt = stage / "stage-receipt.json"
        record = json.loads(_io_path(receipt).read_bytes())
        work = Path("library/works") / work_id
        if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
                or record.get("installation") != "not-performed" or record.get("work_id") != work_id
                or record.get("projection_rows") != entry["native_projection_rows"]
                or record.get("source_sha256") != entry["source_sha256"]
                or record.get("source_entity_declarations") != entry["producer"]["source_entity_declarations"]
                or record.get("source_rights_text_sha256") != entry["producer"]["source_rights_text_sha256"]
                or record.get("source_oracle") != entry["oracle"]
                or _files(ROOT / work) != record["before"] or _files(stage / work) != record["after"]
                or _sha(staging.REPRO / work_id / "candidate.tei.xml") != entry["candidate_sha256"]):
            raise ValueError(f"DocSouth stage or source differs: {work_id}")
        pins.append(dict(work_id=work_id, source_path=entry["source_path"],
                         source_sha256=entry["source_sha256"], source_bytes=entry["source_bytes"],
                         source_doctype=entry["producer"]["source_doctype"],
                         source_entity_declarations=entry["producer"]["source_entity_declarations"],
                         source_rights_text_sha256=entry["producer"]["source_rights_text_sha256"],
                         source_oracle=entry["oracle"],
                         acquisition_receipt_sha256=entry["acquisition_receipt_sha256"],
                         direct_candidate_sha256=entry["candidate_sha256"],
                         stage_receipt=f"{work_id}/stage-receipt.json", stage_receipt_sha256=_sha(receipt),
                         stage_files=_files(stage), accepted_master_sha256=record["accepted_master_sha256"],
                         acceptance_sha256=record["acceptance_sha256"],
                         projection_rows=entry["native_projection_rows"],
                         before_count=len(record["before"]), after_count=len(record["after"])))
    freeze = dict(contract=CONTRACT, status="review-ready-staged-only", canonical_root=ROOT.as_posix(),
                  stage_home=STAGE_HOME.as_posix(), inventory_path=source.INVENTORY.relative_to(ROOT).as_posix(),
                  inventory_sha256=_sha(source.INVENTORY),
                  direct_receipt=(staging.DIRECT / "receipt.json").as_posix(),
                  direct_receipt_sha256=staging.DIRECT_SHA, selected_work_count=1,
                  other_inventory_work_count=26, works=pins, canonical_install="not-performed")
    _io_path(FREEZE).write_bytes(json.dumps(freeze, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8") + b"\n")
    print(json.dumps(dict(freeze=FREEZE.as_posix(), freeze_sha256=_sha(FREEZE), works=len(pins)), sort_keys=True))
