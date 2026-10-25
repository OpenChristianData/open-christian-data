"""Read-only preflight or guarded install of frozen Project Gutenberg 16739."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.drummond_pg16739_native import adapt, direct_candidate
from build.tei.drummond_pg16739_native_oracle import check
from build.tools.stage_drummond_pg16739 import (
    ACQUISITION, ADAPTED_SHA256, EDITION, EDITION_ID, EVIDENCE,
    ROOT, SOURCE, SOURCE_SHA256, STAGE_PARENT, WORK, WORK_ID,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


STAGE = STAGE_PARENT / "drummond-pg16739-stage-20260928-v4"
RECEIPT_SHA256 = "ab51336ec13fa0c5309de98cebce674b654ae3576072de7afce43a0cd2b40cf3"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"PG16739 JSON object required: {path}")
    return value


def preflight() -> dict:
    stage = STAGE.resolve(strict=True)
    root = ROOT.resolve(strict=True)
    if (stage.parent != STAGE_PARENT.resolve(strict=True) or stage.name != STAGE.name
            or root in stage.parents or _sha(stage / "stage-receipt.json") != RECEIPT_SHA256):
        raise PipelineError("PG16739 frozen stage path or receipt differs")
    receipt = _read(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-drummond-pg16739-stage-v1"
            or receipt.get("work_id") != WORK_ID or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("adapted_sha256") != ADAPTED_SHA256
            or receipt.get("native_rows") != 1):
        raise PipelineError("PG16739 frozen stage identity differs")
    for relative, digest in receipt["dependencies"].items():
        if (Path(relative).is_absolute() or ".." in Path(relative).parts
                or _sha(root / relative) != digest):
            raise PipelineError(f"PG16739 frozen dependency changed: {relative}")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"] or len(before) != 3 or len(after) != 19:
        raise PipelineError("PG16739 current preimage or staged generation differs")
    if (_io_path(root / EDITION / "master.tei.xml").exists()
            or _io_path(root / EDITION / "acceptance.json").exists()):
        raise PipelineError("PG16739 edition is already accepted")
    for relative in before:
        if relative not in {"state.json", "work.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"PG16739 staged acquisition change exceeds scope: {relative}")
    expected_work = _read(root / WORK / "work.json")
    if (expected_work["work_id"] != WORK_ID
            or len(expected_work["textual_forms"]) != 1
            or len(expected_work["textual_forms"][0]["editions"]) != 1):
        raise PipelineError("PG16739 canonical work identity differs")
    expected_work = json.loads(json.dumps(expected_work))
    form = expected_work["textual_forms"][0]
    edition = form["editions"][0]
    if edition["edition_id"] != EDITION_ID or edition.get("category") or edition.get("language") or form.get("language"):
        raise PipelineError("PG16739 acquired edition metadata differs")
    form["language"] = "en"
    edition["language"] = "en"
    edition["category"] = "prose"
    if _read(stage / WORK / "work.json") != expected_work:
        raise PipelineError("PG16739 staged identity change exceeds scope")
    original_acquisition = validate_acquisition(root / ACQUISITION, root=root)
    staged_acquisition = validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    retained = original_acquisition["retained_files"]
    if (staged_acquisition != original_acquisition or len(retained) != 1
            or retained[0]["path"] != SOURCE.as_posix()
            or retained[0]["sha256"] != SOURCE_SHA256
            or retained[0]["bytes"] != 204970
            or _sha(root / SOURCE) != SOURCE_SHA256
            or _sha(stage / SOURCE) != SOURCE_SHA256):
        raise PipelineError("PG16739 retained plain-text authority differs")
    if _io_path(root / WORK / "SOURCE_CREDIT.md").exists():
        raise PipelineError("PG16739 canonical source credit preimage differs")
    credit = _io_path(stage / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    if (SOURCE_SHA256 not in credit or SOURCE.as_posix() not in credit
            or "David Garcia, Jeannie Howse" not in credit
            or "electronic collection" not in credit):
        raise PipelineError("PG16739 human-visible source credit differs")
    direct = direct_candidate()
    adapted, counts = adapt(direct)
    if (_sha(stage / EVIDENCE / "inputs/direct-candidate.tei.xml") != receipt["direct_sha256"]
            or _io_path(stage / EVIDENCE / "inputs/direct-candidate.tei.xml").read_bytes() != direct
            or _sha(stage / EVIDENCE / "inputs/adapted-candidate.tei.xml") != ADAPTED_SHA256
            or _io_path(stage / EVIDENCE / "inputs/adapted-candidate.tei.xml").read_bytes() != adapted):
        raise PipelineError("PG16739 direct/adapted candidate differs")
    oracle = check(adapted)
    if (oracle != receipt["oracle"] or oracle != _read(stage / EVIDENCE / "inputs/oracle.json")
            or counts != {"space": 665, "c": 362, "located-head": 18, "attached-title": 3}):
        raise PipelineError("PG16739 independent source oracle or carrier counts differ")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (sha256(master).hexdigest() != receipt["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("PG16739 accepted master changed the complete source body")
    if errors := validate_file(_io_path(stage / EDITION / "master.tei.xml")):
        raise PipelineError(f"PG16739 accepted master fails P5: {errors[:3]}")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if validated["promotion"]["status"] != "promoted":
        raise PipelineError("PG16739 accepted stage is not promoted")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"PG16739 actual-master native row differs: {errors[:3]}")
    return dict(status="ready-for-review", work_id=WORK_ID, stage=stage.as_posix(),
                receipt_sha256=RECEIPT_SHA256, source_sha256=SOURCE_SHA256,
                before_files=len(before), after_files=len(after), native_rows=1,
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
                    raise PipelineError("installed PG16739 generation differs")
                acceptance = ROOT / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(ROOT))
                validate_state(_io_path(target / "state.json"), root=_io_path(ROOT))
                projected = project_accepted_document(_io_path(ROOT),
                    acceptance_path=_io_path(acceptance), category="prose")
                errors = verify_accepted_document(_io_path(ROOT), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != 1:
                    raise PipelineError(f"installed PG16739 native row differs: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(ROOT, target, STAGE / WORK, work_id=WORK_ID,
                                  before=receipt["before"], after=receipt["after"],
                                  existed=True, replacement=False,
                                  operation_kind="pg16739-exact-plain-text-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=checkpoint)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="explicitly install frozen PG16739 generation")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
