"""Read-only preflight or explicit guarded install of Newman PG22088.

The default command changes nothing. ``--apply`` commits exactly one complete
work generation through the shared lock, durable journal, and rollback route.
It does not refresh a corpus, clear rights, or publish anything.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
import json
from pathlib import Path

from build.tei.newman_apologia_pg22088_native_oracle import check_partition
from build.tools.check_newman_apologia_pg22088_stage import check as check_stage
from build.tools.stage_newman_apologia_pg22088 import ACQUISITION, EDITION, EVIDENCE, ROOT, WORK, WORK_ID
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_accepted_document, verify_accepted_document
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/na-s5")
RECEIPT_SHA256 = "17d025383146e9ed7d99d6f90dc23a1afd4a2e5bf0483d3fd67ca9466069e24d"


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"PG22088 JSON object required: {path}")
    return value


def _project(root: Path, acceptance: Path) -> None:
    projected = project_accepted_document(_io_path(root), acceptance_path=_io_path(acceptance),
                                          category="prose")
    errors = verify_accepted_document(_io_path(root), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category="prose")
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"PG22088 accepted-master native projection differs: {errors[:3]}")


def preflight(expected_receipt_sha256: str) -> dict:
    if expected_receipt_sha256 != RECEIPT_SHA256:
        raise PipelineError("PG22088 installer requires the exact frozen na-s5 receipt pin")
    root = ROOT.resolve(strict=True)
    stage = STAGE.resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("PG22088 stage and canonical roots overlap")
    check_stage(stage, expected_receipt_sha256)
    receipt = _read(stage / "stage-receipt.json")
    before, after = receipt["before"], receipt["after"]
    if (_files(root / WORK) != before or _files(stage / WORK) != after
            or set(before) != {"work.json", "state.json", ACQUISITION.relative_to(WORK).as_posix()}
            or len(after) != 23 or receipt["native_rows"] != 1):
        raise PipelineError("PG22088 complete work generation differs")
    for relative in before:
        if relative not in {"work.json", "state.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"PG22088 staged existing source authority changed: {relative}")
    original_work = _read(root / WORK / "work.json")
    revised_work = _read(stage / WORK / "work.json")
    expected_work = json.loads(json.dumps(original_work))
    form = expected_work["textual_forms"][0]
    edition = form["editions"][0]
    if (len(expected_work["textual_forms"]) != 1 or len(form["editions"]) != 1
            or edition.get("category") is not None):
        raise PipelineError("PG22088 original work metadata differs")
    edition["category"] = "prose"
    if revised_work != expected_work:
        raise PipelineError("PG22088 staged metadata exceeds prose-category change")
    original_state = _read(root / WORK / "state.json")
    revised_state = _read(stage / WORK / "state.json")
    old_targets = original_state["targets"]
    new_targets = revised_state["targets"]
    if len(old_targets) != 2 or len(new_targets) != 2 or old_targets[0] != new_targets[0]:
        raise PipelineError("PG22088 acquired source state changed")
    expected_edition = dict(old_targets[1])
    if (expected_edition.get("target_id") != EDITION.name
            or expected_edition.get("stage") != "acquired"):
        raise PipelineError("PG22088 acquired edition state differs")
    expected_edition.update(stage="accepted", reason=PROMOTED_MASTER_REASON,
                            updated_at=new_targets[1].get("updated_at"),
                            evidence=expected_edition["evidence"] + [
                                (EDITION / "master.tei.xml").as_posix(),
                                (EDITION / "acceptance.json").as_posix(),
                            ])
    if (new_targets[1] != expected_edition
            or {key: value for key, value in original_state.items() if key != "targets"}
            != {key: value for key, value in revised_state.items() if key != "targets"}):
        raise PipelineError("PG22088 staged state exceeds one edition transition")
    inputs = stage / EVIDENCE / "inputs"
    report = check_partition(
        _io_path(inputs / "adapted-candidate.tei.xml").read_bytes(),
        _io_path(inputs / "work-text.tei.xml").read_bytes(),
        _io_path(inputs / "provider-header.tei.xml").read_bytes(),
        _io_path(inputs / "provider-license.tei.xml").read_bytes(),
    )
    if report != receipt["oracle"]:
        raise PipelineError("PG22088 fresh independent source/partition oracle differs")
    account = _read(stage / EVIDENCE / "source-accounting.json")
    if (account.get("represented_work_lines") != 13790
            or account.get("evidence_only_provider_lines") != 384
            or account.get("omitted_lines") != 0 or account.get("duplicate_lines") != 0
            or len(account.get("included_members", [])) != 1
            or account.get("excluded_members") != []):
        raise PipelineError("PG22088 work/provider line accounting differs")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if (validated["promotion"]["status"] != "promoted"
            or validated["identity"]["work_id"] != WORK_ID
            or validated["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError("PG22088 staged acceptance authority differs")
    if errors := validate_file(_io_path(stage / EDITION / "master.tei.xml")):
        raise PipelineError(f"PG22088 staged master fails P5: {errors[:3]}")
    _project(stage, acceptance)
    return dict(status="ready-for-review", installation="not-performed", work_id=WORK_ID,
                receipt_sha256=RECEIPT_SHA256, before_files=len(before),
                after_files=len(after), native_rows=1,
                represented_work_lines=13790, evidence_only_provider_lines=384)


def install(expected_receipt_sha256: str,
            *, fail_at: Callable[[str], None] | None = None) -> dict:
    root = ROOT.resolve(strict=True)
    stage = STAGE.resolve(strict=True)
    target, source = root / WORK, stage / WORK
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(expected_receipt_sha256)
        receipt = _read(stage / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("PG22088 installed work generation differs")
                acceptance = root / EDITION / "acceptance.json"
                validate_acceptance(_io_path(acceptance), root=_io_path(root))
                validate_state(_io_path(root / WORK / "state.json"), root=_io_path(root))
                _project(root, acceptance)
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(
            root, target, source, work_id=WORK_ID, before=receipt["before"],
            after=receipt["after"], existed=True, replacement=False,
            operation_kind="newman-apologia-pg22088-work-text-technical-acceptance-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.expected_receipt_sha256) if args.apply else preflight(args.expected_receipt_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
