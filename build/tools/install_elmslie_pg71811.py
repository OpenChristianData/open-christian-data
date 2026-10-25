"""Read-only preflight or guarded install of frozen Elmslie PG71811 stage."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.elmslie_pg71811_native import reconstruct
from build.tei.elmslie_pg71811_oracle import check
from build.tools.stage_elmslie_pg71811 import (
    ACQUISITION, DEPENDENCIES, EDITION, EDITION_ID, EVIDENCE, ROOT, SOURCE,
    SOURCE_SHA256, STAGE_PARENT, WORK, WORK_ID, retained_bindings,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    ELMSLIE_CHOICE_PROFILE, project_accepted_document, verify_accepted_document,
)
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


STAGE = STAGE_PARENT / "elmslie-pg71811-stage-20260928-v2"
RECEIPT_SHA256 = "fd1c01394afd604fcc8d78a296940771dc29559ba5a386615a8f9c2d5e71b083"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"PG71811 JSON object required: {path}")
    return value


def preflight() -> dict:
    stage = STAGE.resolve(strict=True)
    root = ROOT.resolve(strict=True)
    if (stage.parent != STAGE_PARENT.resolve(strict=True) or stage.name != STAGE.name
            or root in stage.parents or _sha(stage / "stage-receipt.json") != RECEIPT_SHA256):
        raise PipelineError("PG71811 frozen stage path or receipt differs")
    receipt = _read(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-elmslie-pg71811-stage-v1"
            or receipt.get("work_id") != WORK_ID
            or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("source_bytes") != 1799715
            or receipt.get("native_rows") != 1):
        raise PipelineError("PG71811 frozen stage identity differs")
    dependency_sha256 = {item.as_posix(): _sha(root / item) for item in DEPENDENCIES}
    if receipt.get("dependency_sha256") != dependency_sha256:
        raise PipelineError("PG71811 mapper, oracle, native contract or schema changed after freeze")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"] or len(before) != 3 or len(after) != 18:
        raise PipelineError("PG71811 live preimage or staged work generation differs")
    if (_io_path(root / EDITION / "master.tei.xml").exists()
            or _io_path(root / EDITION / "acceptance.json").exists()):
        raise PipelineError("PG71811 edition already accepted")
    for relative in before:
        if relative not in {"work.json", "state.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"PG71811 stage changed acquired metadata: {relative}")
    original_work = _read(root / WORK / "work.json")
    expected_work = json.loads(json.dumps(original_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition.get("edition_id") != EDITION_ID or edition.get("category"):
        raise PipelineError("PG71811 acquired edition identity differs")
    edition["category"] = "prose"
    if _read(stage / WORK / "work.json") != expected_work:
        raise PipelineError("PG71811 stage metadata exceeds prose category")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    retained = retained_bindings(acquisition)
    if (validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage)) != acquisition
            or receipt.get("support") != retained or _sha(root / SOURCE) != SOURCE_SHA256):
        raise PipelineError("PG71811 acquired source/support members differ")
    for item in retained:
        path = Path(item["path"])
        if _sha(root / path) != item["sha256"] or _sha(stage / path) != item["sha256"]:
            raise PipelineError(f"PG71811 real member or package changed: {path}")
    if _io_path(root / WORK / "SOURCE_CREDIT.md").exists():
        raise PipelineError("PG71811 canonical source credit preimage differs")
    credit = _io_path(stage / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    if (not credit.startswith("# Source and credit — Elmslie, The Books of Chronicles")
            or "two map captions explicitly say 'Copyright Cambridge University Press,'" not in credit
            or "publication review" not in credit
            or any(item["path"] not in credit or item["sha256"] not in credit for item in retained)):
        raise PipelineError("PG71811 source credit or map-caption rights notice differs")
    notice = _io_path(stage / EVIDENCE / "future-public-notice-binding.md").read_text(encoding="utf-8")
    if "Cambridge map-caption rights hold" not in notice or "No public data-path notice is installed" not in notice:
        raise PipelineError("PG71811 future public notice binding differs")
    direct, _ = reconstruct()
    if (sha256(direct).hexdigest() != receipt["direct_sha256"]
            or direct != _io_path(stage / EVIDENCE / "inputs/direct-candidate.tei.xml").read_bytes()):
        raise PipelineError("PG71811 direct source reconstruction changed")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (sha256(master).hexdigest() != receipt["accepted_master_sha256"]
            or master != _io_path(stage / EVIDENCE / "candidate.tei.xml").read_bytes()
            or master.split(b"</teiHeader>", 1)[1] != direct.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("PG71811 accepted master changed reviewed body")
    oracle = check(master)
    if oracle != receipt["oracle"] or oracle != _read(stage / EVIDENCE / "inputs/oracle.json"):
        raise PipelineError("PG71811 independent HTML oracle differs")
    if errors := validate_file(_io_path(stage / EDITION / "master.tei.xml")):
        raise PipelineError(f"PG71811 accepted master fails P5: {errors[:3]}")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if validated["promotion"]["status"] != "promoted":
        raise PipelineError("PG71811 staged master is not promoted")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                          category="prose", projection_profile=ELMSLIE_CHOICE_PROFILE)
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category="prose", projection_profile=ELMSLIE_CHOICE_PROFILE)
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"PG71811 actual-master native row differs: {errors[:3]}")
    return dict(status="ready-for-review", stage=stage.as_posix(), work_id=WORK_ID,
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
                    raise PipelineError("installed PG71811 work generation differs")
                acceptance = ROOT / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(ROOT))
                validate_state(_io_path(target / "state.json"), root=_io_path(ROOT))
                projected = project_accepted_document(_io_path(ROOT), acceptance_path=_io_path(acceptance),
                                                      category="prose", projection_profile=ELMSLIE_CHOICE_PROFILE)
                errors = verify_accepted_document(_io_path(ROOT), acceptance_path=_io_path(acceptance),
                                                  rows=projected["rows"], receipt=projected["receipt"],
                                                  category="prose", projection_profile=ELMSLIE_CHOICE_PROFILE)
                if errors or len(projected["rows"]) != 1:
                    raise PipelineError(f"installed PG71811 native row differs: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(ROOT, target, STAGE / WORK, work_id=WORK_ID,
                                  before=receipt["before"], after=receipt["after"],
                                  existed=True, replacement=False,
                                  operation_kind="pg71811-exact-real-html-six-jpegs-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=checkpoint)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="explicitly install frozen PG71811 generation")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
