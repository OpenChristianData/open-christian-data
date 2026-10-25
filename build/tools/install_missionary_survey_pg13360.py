"""Read-only preflight or guarded install of the frozen PG13360 work generation."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.missionary_survey_pg13360_native import adapt, source_path
from build.tei.missionary_survey_pg13360_oracle import check
from build.tools.stage_missionary_survey_pg13360 import (
    ACQUISITION, ADAPTED_SHA256, DIRECT, EDITION, EDITION_ID, EVIDENCE,
    ORIGINAL_SHA256, ROOT, SOURCE, SOURCE_SHA256, STAGE_PARENT, WORK, WORK_ID,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


STAGE = STAGE_PARENT / "missionary-survey-pg13360-stage-20260928-v7"
RECEIPT_SHA256 = "a9cb9eef32871a6e580096a1e7dc249ed6c22632f2356473ef3b17d9e9899f02"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"PG13360 JSON object required: {path}")
    return value


def preflight() -> dict:
    stage = STAGE.resolve(strict=True)
    root = ROOT.resolve(strict=True)
    if (stage.parent != STAGE_PARENT.resolve(strict=True) or stage.name != STAGE.name
            or root in stage.parents or _sha(stage / "stage-receipt.json") != RECEIPT_SHA256):
        raise PipelineError("PG13360 frozen external stage location or receipt differs")
    receipt = _read(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-missionary-survey-pg13360-stage-v1"
            or receipt.get("work_id") != WORK_ID
            or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("direct_sha256") != ORIGINAL_SHA256
            or receipt.get("adapted_sha256") != ADAPTED_SHA256
            or receipt.get("native_rows") != 16):
        raise PipelineError("PG13360 frozen stage contract differs")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"] or len(before) != 4 or len(after) != 18:
        raise PipelineError("PG13360 canonical preimage or frozen work generation differs")
    for relative in before:
        if relative not in {"state.json", "work.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"PG13360 stage changes acquired authority: {relative}")
    if _io_path(root / EDITION / "master.tei.xml").exists() or _io_path(root / EDITION / "acceptance.json").exists():
        raise PipelineError("PG13360 edition already accepted")
    current_work = _read(root / WORK / "work.json")
    expected_work = json.loads(json.dumps(current_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition.get("category") or edition.get("edition_id") != EDITION_ID:
        raise PipelineError("PG13360 acquired identity differs")
    edition["category"] = "prose"
    if _read(stage / WORK / "work.json") != expected_work:
        raise PipelineError("PG13360 staged metadata exceeds source-bound category")
    source = source_path()
    if _sha(stage / SOURCE) != SOURCE_SHA256 or _sha(root / ACQUISITION) != _sha(stage / ACQUISITION):
        raise PipelineError("PG13360 source or acquisition dependency changed")
    original = _io_path(DIRECT / "candidate.tei.xml").read_bytes()
    adapted = adapt(original)
    if (sha256(original).hexdigest() != ORIGINAL_SHA256
            or sha256(adapted).hexdigest() != ADAPTED_SHA256
            or adapted != _io_path(stage / EVIDENCE / "inputs/adapted-candidate.tei.xml").read_bytes()
            or original != _io_path(stage / EVIDENCE / "inputs/direct-candidate.tei.xml").read_bytes()):
        raise PipelineError("PG13360 direct or adapted candidate differs")
    oracle = check(adapted, source=source)
    if oracle != _read(stage / EVIDENCE / "inputs/oracle.json") or oracle != receipt["oracle"]:
        raise PipelineError("PG13360 independent source oracle differs")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (sha256(master).hexdigest() != receipt["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("PG13360 accepted master changed selected book text")
    if errors := validate_file(_io_path(stage / EDITION / "master.tei.xml")):
        raise PipelineError(f"PG13360 accepted master fails P5: {errors[:3]}")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if validated["promotion"]["status"] != "promoted":
        raise PipelineError("PG13360 accepted stage is not promoted")
    projection = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projection["rows"], receipt=projection["receipt"], category="prose")
    if errors or len(projection["rows"]) != 16:
        raise PipelineError(f"PG13360 actual-master native projection differs: {errors[:3]}")
    return dict(status="ready-for-review", work_id=WORK_ID, stage=stage.as_posix(),
                receipt_sha256=RECEIPT_SHA256, source_sha256=SOURCE_SHA256,
                before_files=len(before), after_files=len(after), native_rows=16,
                installation="not-performed")


def install(*, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight()
    target = ROOT / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight()
        receipt = _read(STAGE / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("installed PG13360 work generation differs")
                acceptance = ROOT / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(ROOT))
                validate_state(_io_path(target / "state.json"), root=_io_path(ROOT))
                projected = project_accepted_document(_io_path(ROOT),
                    acceptance_path=_io_path(acceptance), category="prose")
                errors = verify_accepted_document(_io_path(ROOT), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != 16:
                    raise PipelineError(f"installed PG13360 native rows differ: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(ROOT, target, STAGE / WORK, work_id=WORK_ID,
                                  before=receipt["before"], after=receipt["after"],
                                  existed=True, replacement=False,
                                  operation_kind="pg13360-exact-txt-book-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=checkpoint)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="explicitly install the frozen work generation")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
