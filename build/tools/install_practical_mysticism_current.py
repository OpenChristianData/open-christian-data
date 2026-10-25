"""Read-only preflight or guarded install of frozen Practical Mysticism."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_practical_mysticism_current import (
    ACQUISITION, DIRECT_SHA256, EDITION, EDITION_ID, EVIDENCE, MANIFEST_SHA256,
    MEMBER_SET, PACKAGE_SHA256, ROOT, SOURCE_SET_SHA256, STAGE_PARENT,
    SUPPORT, WORK, WORK_ID, source_check,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


STAGE = STAGE_PARENT / "practical-mysticism-stage-20260928-v1"
RECEIPT_SHA256 = "cf77f5ccce2f13e0427a36f4fa0810a7746c4b315ecb599313337016679e6059"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"Practical Mysticism JSON object required: {path}")
    return value


def preflight() -> dict:
    stage = STAGE.resolve(strict=True)
    root = ROOT.resolve(strict=True)
    if (stage.parent != STAGE_PARENT.resolve(strict=True) or stage.name != STAGE.name
            or root in stage.parents or _sha(stage / "stage-receipt.json") != RECEIPT_SHA256):
        raise PipelineError("Practical Mysticism frozen stage path or receipt differs")
    receipt = _read(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-practical-mysticism-current-stage-v1"
            or receipt.get("work_id") != WORK_ID or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_member_set_sha256") != SOURCE_SET_SHA256
            or receipt.get("source_manifest_sha256") != MANIFEST_SHA256
            or receipt.get("direct_package_sha256") != PACKAGE_SHA256
            or receipt.get("direct_tei_sha256") != DIRECT_SHA256
            or receipt.get("native_rows") != 18):
        raise PipelineError("Practical Mysticism frozen stage identity differs")
    for relative, digest in receipt["dependencies"].items():
        if (Path(relative).is_absolute() or ".." in Path(relative).parts
                or _sha(root / relative) != digest):
            raise PipelineError(f"Practical Mysticism frozen dependency changed: {relative}")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"] or len(before) != 6 or len(after) != 20:
        raise PipelineError("Practical Mysticism acquired preimage or staged generation differs")
    if (_io_path(root / EDITION / "master.tei.xml").exists()
            or _io_path(root / EDITION / "acceptance.json").exists()):
        raise PipelineError("Practical Mysticism edition already accepted")
    for relative in before:
        if relative not in {"state.json", "work.json"} and before[relative] != after.get(relative):
            raise PipelineError(f"Practical Mysticism staged acquired file changed: {relative}")
    expected_work = _read(root / WORK / "work.json")
    if (expected_work["work_id"] != WORK_ID or len(expected_work["textual_forms"]) != 1
            or len(expected_work["textual_forms"][0]["editions"]) != 1):
        raise PipelineError("Practical Mysticism canonical work identity differs")
    expected_work = json.loads(json.dumps(expected_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition["edition_id"] != EDITION_ID or edition.get("category"):
        raise PipelineError("Practical Mysticism acquired edition category differs")
    edition["category"] = "prose"
    if _read(stage / WORK / "work.json") != expected_work:
        raise PipelineError("Practical Mysticism staged metadata exceeds prose category")
    original_acquisition = validate_acquisition(root / ACQUISITION, root=root)
    staged_acquisition = validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    if (staged_acquisition != original_acquisition or _sha(root / MEMBER_SET) != SOURCE_SET_SHA256
            or _sha(stage / MEMBER_SET) != SOURCE_SET_SHA256
            or _io_path(root / SUPPORT).read_bytes() != _io_path(stage / SUPPORT).read_bytes()):
        raise PipelineError("Practical Mysticism member-set or support sidecar differs")
    direct, sidecars, oracle = source_check()
    if oracle != receipt["oracle"] or oracle != _read(stage / EVIDENCE / "inputs/oracle.json"):
        raise PipelineError("Practical Mysticism fresh independent source oracle differs")
    if (_io_path(stage / EVIDENCE / "inputs/direct-candidate.tei.xml").read_bytes() != direct
            or _sha(stage / EVIDENCE / "inputs/direct-candidate.tei.xml") != DIRECT_SHA256):
        raise PipelineError("Practical Mysticism staged direct candidate differs")
    if (receipt["text_members"] != sidecars["ordered_text_members"]
            or receipt["support_members"] != sidecars["support_members"]):
        raise PipelineError("Practical Mysticism OPF source/support inventory differs")
    for member in receipt["text_members"] + receipt["support_members"]:
        relative = Path(member["path"])
        if (relative.is_absolute() or ".." in relative.parts
                or _sha(root / relative) != member["sha256"]
                or _sha(stage / relative) != member["sha256"]
                or _io_path(stage / relative).stat().st_size != member["bytes"]):
            raise PipelineError(f"Practical Mysticism retained source/support member differs: {relative}")
    credit = _io_path(stage / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    notice = _io_path(stage / EVIDENCE / "future-public-notice-binding.md").read_text(encoding="utf-8")
    if ("18 retained XHTML text files" not in credit or "15 checkout files" not in credit
            or "7ee6f8c2f826797f8cb1f3922dc7378142454eec" not in credit
            or "public data-path release" not in notice or "No public notice is installed" not in notice):
        raise PipelineError("Practical Mysticism source credit or future public notice differs")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (sha256(master).hexdigest() != receipt["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != direct.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("Practical Mysticism accepted master changed source text")
    if errors := validate_file(_io_path(stage / EDITION / "master.tei.xml")):
        raise PipelineError(f"Practical Mysticism accepted master fails P5: {errors[:3]}")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if validated["promotion"]["status"] != "promoted":
        raise PipelineError("Practical Mysticism accepted stage is not promoted")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                          category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 18:
        raise PipelineError(f"Practical Mysticism actual-master native rows differ: {errors[:3]}")
    return dict(status="ready-for-review", work_id=WORK_ID, stage=stage.as_posix(),
                receipt_sha256=RECEIPT_SHA256, source_member_set_sha256=SOURCE_SET_SHA256,
                text_members=18, support_members=15, before_files=len(before),
                after_files=len(after), native_rows=18, installation="not-performed")


def install(*, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight()
    target = ROOT / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight()
        receipt = _read(STAGE / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("installed Practical Mysticism generation differs")
                acceptance = ROOT / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(ROOT))
                validate_state(_io_path(target / "state.json"), root=_io_path(ROOT))
                projected = project_accepted_document(_io_path(ROOT),
                    acceptance_path=_io_path(acceptance), category="prose")
                errors = verify_accepted_document(_io_path(ROOT), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != 18:
                    raise PipelineError(f"installed Practical Mysticism native rows differ: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(ROOT, target, STAGE / WORK, work_id=WORK_ID,
                                  before=receipt["before"], after=receipt["after"],
                                  existed=True, replacement=False,
                                  operation_kind="standard-ebooks-practical-mysticism-current-spine-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=checkpoint)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="explicitly install frozen Practical Mysticism generation")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
