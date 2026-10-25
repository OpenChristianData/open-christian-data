"""Read-only preflight or guarded install of frozen PG53809 acceptance."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.stephens_pg53809_native import adapt, source_bindings
from build.tei.stephens_pg53809_oracle import check
from build.tools.stage_stephens_pg53809 import (
    ACQUISITION, ADAPTED_SHA256, DIRECT, DIRECT_SHA256, EDITION, EDITION_ID,
    EVIDENCE, ROOT, SOURCE_SHA256, STAGE_PARENT, WORK, WORK_ID,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


STAGE = STAGE_PARENT / "stephens-pg53809-stage-20260928-v2"
RECEIPT_SHA256 = "d78a350ef2a6c37dd57f944e4c96d114dac47d92e67dba3294fcaaf5b20adc5c"
DEPENDENCIES = {
    "build/tei/stephens_pg53809_native.py": "a4f10887d53fc8a74d3ad2be46e83961117750e36e01614d0623d760d02781a8",
    "build/tei/stephens_pg53809_oracle.py": "dd237cc912f75d6cfd9f74113628d9bf27ca9465c4b350c92f37fdc22ed62e45",
    "build/tools/stage_stephens_pg53809.py": "d552cc84bcfd0c026e5fa5bac041ae79bff8f903dc50ec3063ff7fdd4c6e936f",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd": "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f",
    "schemas/v2/native-content.schema.json": "519ae5e0847976f5f2142de189a37a23b4496c5e1efb788529b2de7319e0d9f2",
    "ocd_kernel/projection/native_content.py": "38ca5ef163564a214b72d862830bc727467df41f65de5520e3841211b30056f0",
    "ocd_kernel/projection/native_content_check.py": "b24561e6174da99563182e9c75301814088c0f7aeffcae086bf95aae1b3b919e",
}


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    result = json.loads(_io_path(path).read_bytes())
    if not isinstance(result, dict):
        raise PipelineError(f"PG53809 JSON object required: {path}")
    return result


def preflight() -> dict:
    stage = STAGE.resolve(strict=True)
    root = ROOT.resolve(strict=True)
    for relative, digest in DEPENDENCIES.items():
        if _sha(root / relative) != digest:
            raise PipelineError(f"PG53809 frozen dependency changed: {relative}")
    if (stage.parent != STAGE_PARENT.resolve(strict=True) or stage.name != STAGE.name
            or root in stage.parents or _sha(stage / "stage-receipt.json") != RECEIPT_SHA256):
        raise PipelineError("PG53809 frozen stage path or receipt differs")
    receipt = _read(stage / "stage-receipt.json")
    if (receipt.get("contract") != "ocd-stephens-pg53809-stage-v2"
            or receipt.get("work_id") != WORK_ID or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA256
            or receipt.get("direct_sha256") != DIRECT_SHA256
            or receipt.get("adapted_sha256") != ADAPTED_SHA256
            or receipt.get("native_rows") != 1):
        raise PipelineError("PG53809 frozen stage identity differs")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"] or len(before) != 3 or len(after) != 18:
        raise PipelineError("PG53809 current preimage or staged generation differs")
    if _io_path(root / EDITION / "master.tei.xml").exists() or _io_path(root / EDITION / "acceptance.json").exists():
        raise PipelineError("PG53809 edition is already accepted")
    for relative in before:
        if relative not in {"state.json", "work.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"PG53809 staged mutation exceeds acceptance metadata: {relative}")
    expected_work = _read(root / WORK / "work.json")
    expected_work = json.loads(json.dumps(expected_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition.get("edition_id") != EDITION_ID or edition.get("category") or edition.get("language") != "en":
        raise PipelineError("PG53809 canonical work identity differs")
    edition["category"] = "prose"
    if _read(stage / WORK / "work.json") != expected_work:
        raise PipelineError("PG53809 staged metadata exceeds prose binding")
    original_acquisition = validate_acquisition(root / ACQUISITION, root=root)
    staged_acquisition = validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    support = source_bindings()
    if (staged_acquisition != original_acquisition or
            [item["sha256"] for item in original_acquisition["retained_files"]]
            != [item["sha256"] for item in support]):
        raise PipelineError("PG53809 source/package/image acquisition differs")
    if _io_path(root / WORK / "SOURCE_CREDIT.md").exists():
        raise PipelineError("PG53809 canonical source-credit preimage differs")
    credit = _io_path(stage / WORK / "SOURCE_CREDIT.md").read_text(encoding="utf-8")
    if (not credit.startswith("# Source and credit — Saint John Chrysostom")
            or any(item["sha256"] not in credit or item["path"] not in credit for item in support)
            or "W. R. W. Stephens" not in credit or "John Murray, 1880" not in credit
            or "Turgut Dincer and the Online Distributed Proofreading Team" not in credit
            or "unreferenced" not in credit.lower()):
        raise PipelineError("PG53809 human-visible source credit differs")
    for item in support:
        relative = Path(item["path"])
        if _sha(root / relative) != item["sha256"] or _sha(stage / relative) != item["sha256"]:
            raise PipelineError(f"PG53809 retained real/package file changed: {relative}")
    direct = _io_path(DIRECT).read_bytes()
    adapted = adapt(direct)
    if (sha256(direct).hexdigest() != DIRECT_SHA256 or sha256(adapted).hexdigest() != ADAPTED_SHA256
            or direct != _io_path(stage / EVIDENCE / "inputs/direct-candidate.tei.xml").read_bytes()
            or adapted != _io_path(stage / EVIDENCE / "inputs/adapted-candidate.tei.xml").read_bytes()):
        raise PipelineError("PG53809 direct/adapted candidate differs")
    oracle = check(adapted)
    if check(adapted, source_root=stage) != oracle or oracle != receipt["oracle"] or oracle != _read(stage / EVIDENCE / "inputs/oracle.json"):
        raise PipelineError("PG53809 independent real-HTML oracle differs")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (sha256(master).hexdigest() != receipt["accepted_master_sha256"]
            or master.split(b"</teiHeader>", 1)[1] != adapted.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("PG53809 accepted master changed source body")
    if errors := validate_file(_io_path(stage / EDITION / "master.tei.xml")):
        raise PipelineError(f"PG53809 accepted master fails P5: {errors[:3]}")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if validated["promotion"]["status"] != "promoted":
        raise PipelineError("PG53809 stage is not promoted")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"PG53809 actual-master native row differs: {errors[:3]}")
    return dict(status="ready-for-review", work_id=WORK_ID, stage=stage.as_posix(),
                receipt_sha256=RECEIPT_SHA256, source_sha256=SOURCE_SHA256,
                image_support_members=2, package_support_members=1,
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
                    raise PipelineError("installed PG53809 generation differs")
                acceptance = ROOT / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(ROOT))
                validate_state(_io_path(target / "state.json"), root=_io_path(ROOT))
                projected = project_accepted_document(_io_path(ROOT),
                    acceptance_path=_io_path(acceptance), category="prose")
                errors = verify_accepted_document(_io_path(ROOT), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != 1:
                    raise PipelineError(f"installed PG53809 native row differs: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(ROOT, target, STAGE / WORK, work_id=WORK_ID,
                                  before=receipt["before"], after=receipt["after"],
                                  existed=True, replacement=False,
                                  operation_kind="pg53809-exact-extracted-html-images-install",
                                  result_status="installed-and-validated", accepted_editions=1,
                                  fail_at=checkpoint)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="explicitly install frozen PG53809 generation")
    args = parser.parse_args()
    print(json.dumps(install() if args.apply else preflight(), sort_keys=True))


if __name__ == "__main__":
    main()
