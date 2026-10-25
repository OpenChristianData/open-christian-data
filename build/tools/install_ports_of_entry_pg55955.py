"""Read-only preflight or guarded install of the frozen PG55955 generation."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.ports_of_entry_pg55955_native import adapt, image_bindings, source_path
from build.tei.ports_of_entry_pg55955_oracle import check
from build.tools.stage_ports_of_entry_pg55955 import (
    ACQUISITION, ADAPTED_SHA256, DIRECT, DIRECT_SHA256, EDITION, EDITION_ID,
    EVIDENCE, ROOT, SOURCE, SOURCE_SHA256, STAGE_PARENT, WORK, WORK_ID,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


STAGE = STAGE_PARENT / "ports-of-entry-pg55955-stage-20260928-v1"
RECEIPT_SHA256 = "8db75a7dc1e3acd81aff9e078e4d37b3efc8042796435b6fab1c746b6677a2ad"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"PG55955 JSON object required: {path}")
    return result


def preflight() -> dict:
    stage = STAGE.resolve(strict=True)
    root = ROOT.resolve(strict=True)
    if (stage.parent != STAGE_PARENT.resolve(strict=True) or stage.name != STAGE.name
            or root in stage.parents or _sha(stage / "stage-receipt.json") != RECEIPT_SHA256):
        raise PipelineError("PG55955 frozen stage path or receipt differs")
    receipt = _read(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-ports-of-entry-pg55955-stage-v1"
            or receipt.get("work_id") != WORK_ID or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("direct_sha256") != DIRECT_SHA256
            or receipt.get("adapted_sha256") != ADAPTED_SHA256
            or receipt.get("native_rows") != 10):
        raise PipelineError("PG55955 frozen stage identity differs")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"] or len(before) != 4 or len(after) != 18:
        raise PipelineError("PG55955 current preimage or staged work generation differs")
    if _io_path(root / EDITION / "master.tei.xml").exists() or _io_path(root / EDITION / "acceptance.json").exists():
        raise PipelineError("PG55955 edition already accepted")
    for relative in before:
        if relative not in {"state.json", "work.json", "SOURCE_CREDIT.md",
                            (ACQUISITION.relative_to(WORK)).as_posix()} and after.get(relative) != before[relative]:
            raise PipelineError(f"PG55955 staged change exceeds source/support metadata: {relative}")
    original_work = _read(root / WORK / "work.json")
    expected_work = json.loads(json.dumps(original_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition.get("edition_id") != EDITION_ID or edition.get("category"):
        raise PipelineError("PG55955 acquired edition identity differs")
    edition["category"] = "prose"
    if _read(stage / WORK / "work.json") != expected_work:
        raise PipelineError("PG55955 staged metadata exceeds prose category")
    original_acquisition = validate_acquisition(root / ACQUISITION, root=root)
    staged_acquisition = validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    expected_acquisition = json.loads(json.dumps(original_acquisition))
    expected_acquisition["retained_files"].extend(image_bindings())
    if staged_acquisition != expected_acquisition or _sha(root / SOURCE) != SOURCE_SHA256:
        raise PipelineError("PG55955 text/image member set differs")
    current_credit = _io_path(root / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8").rstrip()
    stage_credit = _io_path(stage / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    if (not stage_credit.startswith(current_credit + "\n\n## Retained image support")
            or any(item["sha256"] not in stage_credit for item in receipt["image_support"])):
        raise PipelineError("PG55955 human-visible image source credit differs")
    for image in image_bindings():
        relative = Path(image["path"])
        if _sha(root / relative) != image["sha256"] or _sha(stage / relative) != image["sha256"]:
            raise PipelineError(f"PG55955 retained image changed: {relative}")
    original = _io_path(DIRECT / "candidate.tei.xml").read_bytes()
    adapted = adapt(original)
    if (sha256(original).hexdigest() != DIRECT_SHA256
            or sha256(adapted).hexdigest() != ADAPTED_SHA256
            or original != _io_path(stage / EVIDENCE / "inputs/direct-candidate.tei.xml").read_bytes()
            or adapted != _io_path(stage / EVIDENCE / "inputs/adapted-candidate.tei.xml").read_bytes()):
        raise PipelineError("PG55955 direct/adapted candidate differs")
    oracle = check(adapted, source=source_path())
    if oracle != receipt["oracle"] or oracle != _read(stage / EVIDENCE / "inputs/oracle.json"):
        raise PipelineError("PG55955 independent HTML/image oracle differs")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (sha256(master).hexdigest() != receipt["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("PG55955 accepted master changed selected HTML text")
    if errors := validate_file(_io_path(stage / EDITION / "master.tei.xml")):
        raise PipelineError(f"PG55955 accepted master fails P5: {errors[:3]}")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if validated["promotion"]["status"] != "promoted":
        raise PipelineError("PG55955 accepted stage is not promoted")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 10:
        raise PipelineError(f"PG55955 actual-master native rows differ: {errors[:3]}")
    return dict(status="ready-for-review", work_id=WORK_ID, stage=stage.as_posix(),
                receipt_sha256=RECEIPT_SHA256, source_sha256=SOURCE_SHA256,
                image_support_members=11, before_files=len(before), after_files=len(after),
                native_rows=10, installation="not-performed")


def install(*, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight()
    target = ROOT / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight()
        receipt = _read(STAGE / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("installed PG55955 work generation differs")
                acceptance = ROOT / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(ROOT))
                validate_state(_io_path(target / "state.json"), root=_io_path(ROOT))
                projected = project_accepted_document(_io_path(ROOT),
                    acceptance_path=_io_path(acceptance), category="prose")
                errors = verify_accepted_document(_io_path(ROOT), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != 10:
                    raise PipelineError(f"installed PG55955 native rows differ: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(ROOT, target, STAGE / WORK, work_id=WORK_ID,
                                  before=receipt["before"], after=receipt["after"],
                                  existed=True, replacement=False,
                                  operation_kind="pg55955-exact-html-image-support-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=checkpoint)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="explicitly install frozen PG55955 generation")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
