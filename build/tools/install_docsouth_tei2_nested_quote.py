"""Guarded nested-quote DocSouth installer; default operation is read-only preflight."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei import docsouth_tei2_nested_quote as source
from build.tei.docsouth_tei2_nested_quote_oracle import check
from build.tools import freeze_docsouth_tei2_nested_quote as freezing
from build.tools import stage_docsouth_tei2_nested_quote as staging
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
FREEZE_SHA = "1118e35e9c227a114e9c9939f93676de8d2f8cd6754036d70bf50425beff5dc4"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _frozen() -> dict:
    if _sha(freezing.FREEZE) != FREEZE_SHA:
        raise PipelineError("DocSouth reviewed freeze changed")
    frozen = _read(freezing.FREEZE)
    if (frozen.get("contract") != freezing.CONTRACT or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("canonical_install") != "not-performed" or frozen.get("selected_work_count") != 3
            or frozen.get("other_inventory_work_count") != 24 or len(frozen.get("works", [])) != 3
            or {item["work_id"] for item in frozen["works"]} != set(source.SELECTIONS)
            or frozen.get("direct_receipt_sha256") != staging.DIRECT_SHA
            or frozen.get("inventory_sha256") != source.INVENTORY_SHA):
        raise PipelineError("DocSouth freeze scope differs")
    if (Path(frozen["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True)
            or Path(frozen["stage_home"]).resolve(strict=True) != freezing.STAGE_HOME.resolve(strict=True)
            or Path(frozen["direct_receipt"]).resolve(strict=True) != (staging.DIRECT / "receipt.json").resolve(strict=True)):
        raise PipelineError("DocSouth frozen roots differ")
    if (_sha(ROOT / frozen["inventory_path"]) != source.INVENTORY_SHA
            or _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA):
        raise PipelineError("DocSouth inventory or direct receipt changed")
    return frozen


def _work_pin(frozen: dict, work_id: str) -> tuple[dict, Path, dict]:
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
            or record.get("source_entity_declarations") != 0
            or record.get("source_nested_text_count") != pin["source_nested_text_count"]
            or record.get("source_oracle") != pin["source_oracle"]
            or record.get("projection_rows") != pin["projection_rows"]):
        raise PipelineError("DocSouth stage receipt differs")
    return pin, stage, record


def preflight(work_id: str) -> dict:
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
            or entry["oracle"] != pin["source_oracle"]
            or entry["oracle"]["source_nested_text_count"] != pin["source_nested_text_count"]):
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
            or len(acquisition.get("retained_files", [])) != 1):
        raise PipelineError("DocSouth acquisition differs")
    candidate = _io_path(Path(entry["candidate_path"])).read_bytes()
    reproduced, producer = source.convert(work_id)
    if (sha256(candidate).hexdigest() != pin["direct_candidate_sha256"]
            or _sha(staging.REPRO / work_id / "candidate.tei.xml") != pin["direct_candidate_sha256"]
            or reproduced != candidate or producer != entry["producer"]):
        raise PipelineError("DocSouth candidate reproduction differs")
    if check(ROOT / entry["source_path"], pin["source_sha256"], candidate) != pin["source_oracle"]:
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
                source_sha256=pin["source_sha256"], source_entity_declarations=0, source_nested_text_count=pin["source_nested_text_count"],
                source_rights_text_sha256=pin["source_rights_text_sha256"],
                projection_rows=len(projected["rows"]), stage_receipt=(stage / "stage-receipt.json").as_posix(),
                installation="not-performed")


def install(work_id: str, *, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight(work_id)
    frozen = _frozen()
    pin, stage, record = _work_pin(frozen, work_id)
    work = Path("library/works") / work_id
    target = ROOT / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(stage / "stage-receipt.json") != pin["stage_receipt_sha256"]:
            raise PipelineError("DocSouth stage receipt changed under lock")
        preflight(work_id)
        return _commit_generation(ROOT, target, stage / work, work_id=work_id,
                                  before=record["before"], after=record["after"],
                                  existed=True, replacement=False,
                                  operation_kind="docsouth-tei2-nested-quote-initial-install",
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
