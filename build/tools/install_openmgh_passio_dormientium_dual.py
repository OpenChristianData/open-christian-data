"""Guarded Passio Dormientium two-edition installer; default operation is read-only preflight."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei import openmgh_passio_dormientium_dual as source
from build.tei.openmgh_passio_dormientium_dual_oracle import check
from build.tools import freeze_openmgh_passio_dormientium_dual as freezing
from build.tools import stage_openmgh_passio_dormientium_dual as staging
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


ROOT = source.ROOT
FREEZE_SHA = "b9a2d49e1672eee240883e31a558fb23a5574f361f57cf1732e43f28e44916ae"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _frozen() -> tuple[dict, dict]:
    if _sha(freezing.FREEZE) != FREEZE_SHA:
        raise PipelineError("Passio Dormientium reviewed freeze changed")
    frozen = _read(freezing.FREEZE)
    if (frozen.get("contract") != freezing.CONTRACT
            or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("work_id") != source.WORK_ID
            or frozen.get("canonical_install") != "not-performed"
            or frozen.get("selected_edition_count") != 2
            or frozen.get("total_sibling_work_divisions") != 24
            or {e["code"] for e in frozen.get("editions", [])} != set(source.WITNESSES)
            or frozen.get("direct_receipt_sha256") != staging.DIRECT_SHA
            or Path(frozen["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True)
            or Path(frozen["stage_root"]).resolve(strict=True) != freezing.STAGE.resolve(strict=True)):
        raise PipelineError("Passio Dormientium freeze authority or edition scope differs")
    if (_sha(freezing.STAGE / "stage-receipt.json") != frozen["stage_receipt_sha256"]
            or _files(freezing.STAGE) != frozen["stage_files"]
            or _sha(staging.DIRECT / "receipt.json") != staging.DIRECT_SHA):
        raise PipelineError("Passio Dormientium complete stage or direct receipt changed")
    record = _read(freezing.STAGE / "stage-receipt.json")
    if (record.get("contract") != staging.CONTRACT or record.get("status") != "staged-only"
            or record.get("installation") != "not-performed"
            or record.get("before") != frozen["before"] or record.get("after") != frozen["after"]
            or record.get("editions") != frozen["editions"] or record.get("projection_rows") != 2):
        raise PipelineError("Passio Dormientium stage receipt differs from freeze")
    return frozen, record


def preflight() -> dict:
    frozen, record = _frozen()
    stage = freezing.STAGE
    if ROOT.resolve(strict=True) in stage.resolve(strict=True).parents:
        raise PipelineError("Passio Dormientium stage overlaps canonical checkout")
    work = Path("library/works") / source.WORK_ID
    before, after = _files(ROOT / work), _files(stage / work)
    if before != record["before"] or after != record["after"] or len(before) != 4:
        raise PipelineError("Passio Dormientium canonical or staged work generation changed")
    allowed = {"work.json", "state.json", "SOURCE_CREDIT.md"}
    for rel in set(before) | set(after):
        if before.get(rel) == after.get(rel):
            continue
        if rel in allowed or rel.startswith("forms/") and rel.endswith(("/master.tei.xml", "/acceptance.json", "/README.source.md")):
            continue
        if rel.startswith("integration/" + staging.EVIDENCE + "/") and rel not in before:
            continue
        raise PipelineError(f"Passio Dormientium unrelated work path differs: {rel}")
    original = _read(ROOT / work / "work.json")
    revised = _read(stage / work / "work.json")
    expected = json.loads(json.dumps(original))
    if len(expected.get("textual_forms", [])) != 1 or len(expected["textual_forms"][0].get("editions", [])) != 2:
        raise PipelineError("Passio Dormientium canonical edition count changed")
    for edition in expected["textual_forms"][0]["editions"]:
        if edition.get("language") or edition.get("category"):
            raise PipelineError("Passio Dormientium native fields are already assigned")
        edition.update(language="la", category="prose")
    if expected != revised:
        raise PipelineError("Passio Dormientium identity changed beyond native fields")
    validate_identity_update(original, revised)
    load_work(_io_path(stage / work / "work.json"))
    direct = _read(staging.DIRECT / "receipt.json")
    if {item["code"] for item in direct.get("sources", [])} != set(source.WITNESSES):
        raise PipelineError("Passio Dormientium direct candidate set changed")
    for item in frozen["editions"]:
        code = item["code"]
        spec = source.WITNESSES[code]
        direct_item = next(x for x in direct["sources"] if x["code"] == code)
        source_path, package_path, receipt_path = source.paths(code)
        for rel, digest in ((source_path, spec["source_sha256"]), (package_path, spec["package_sha256"]),
                            (receipt_path, spec["receipt_sha256"])):
            if _sha(ROOT / rel) != digest or _sha(stage / rel) != digest:
                raise PipelineError(f"{code} current/staged retained dependency changed: {rel}")
        old_edition = next(e for e in original["textual_forms"][0]["editions"]
                           if e["edition_id"] == item["edition_id"])
        edition = work / "forms" / original["textual_forms"][0]["textual_form_id"] / "editions" / old_edition["edition_id"]
        acquisition = edition / "acquisitions" / (old_edition["acquisition_ids"][0] + ".json")
        if _sha(ROOT / acquisition) != before[acquisition.relative_to(work).as_posix()]:
            raise PipelineError(f"{code} canonical acquisition changed")
        candidate, producer = source.convert(code)
        oracle = check(code, candidate)
        if (candidate != _io_path(Path(direct_item["candidate_path"])).read_bytes()
                or _sha(staging.REPRO / code / "candidate.tei.xml") != item["direct_candidate_sha256"]
                or sha256(candidate).hexdigest() != item["direct_candidate_sha256"]
                or producer != direct_item["producer"] or oracle != item["oracle"]):
            raise PipelineError(f"{code} source candidate, clean reproduction, or independent oracle changed")
        acceptance_path, master_path = edition / "acceptance.json", edition / "master.tei.xml"
        if _io_path(ROOT / acceptance_path).exists() or _io_path(ROOT / master_path).exists():
            raise PipelineError(f"{code} canonical edition already accepted")
        accepted = validate_acceptance(_io_path(stage / acceptance_path), root=_io_path(stage))
        master = _io_path(stage / master_path).read_bytes()
        if (_sha(stage / master_path) != item["accepted_master_sha256"]
                or _sha(stage / acceptance_path) != item["acceptance_sha256"]
                or accepted["promotion"]["master"]["sha256"] != item["accepted_master_sha256"]
                or master.split(b"</teiHeader>", 1)[1] != candidate.split(b"</teiHeader>", 1)[1]):
            raise PipelineError(f"{code} accepted master does not retain exact candidate body")
        if errors := validate_file(_io_path(stage / master_path)):
            raise PipelineError(f"{code} staged P5 XSD failed: {errors[:3]}")
        credit = _io_path(stage / edition / "README.source.md").read_bytes()
        if b"Monumenta Germaniae Historica" not in credit or b"Bavarian State Library, Munich" not in credit:
            raise PipelineError(f"{code} visible MGH/BSB source credit missing")
        projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path), category="prose")
        errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(stage / acceptance_path),
                                          rows=projected["rows"], receipt=projected["receipt"], category="prose")
        if errors or len(projected["rows"]) != 1:
            raise PipelineError(f"{code} actual-master native prose differs: {errors[:3]}")
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    if b"Monumenta Germaniae Historica" not in _io_path(stage / work / "SOURCE_CREDIT.md").read_bytes():
        raise PipelineError("Passio Dormientium work-level source credit missing")
    return dict(status="ready-for-review", work_id=source.WORK_ID,
                before_files=len(before), after_files=len(after), accepted_editions=2,
                projection_rows=2, stage_receipt=(stage / "stage-receipt.json").as_posix(),
                installation="not-performed")


def install(*, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight()
    frozen, record = _frozen()
    work = Path("library/works") / source.WORK_ID
    target = ROOT / work
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(freezing.STAGE / "stage-receipt.json") != frozen["stage_receipt_sha256"]:
            raise PipelineError("Passio Dormientium stage receipt changed under work lock")
        preflight()
        return _commit_generation(ROOT, target, freezing.STAGE / work, work_id=source.WORK_ID,
                                  before=record["before"], after=record["after"], existed=True,
                                  replacement=False, operation_kind="openmgh-passio-dormientium-dual-initial-install",
                                  result_status="installed-and-validated", accepted_editions=2, fail_at=fail_at)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="explicitly install both accepted editions")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
