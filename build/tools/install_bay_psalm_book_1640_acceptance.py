"""Preflight a frozen Bay Psalm Book stage; install only with explicit ``--apply``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_bay_psalm_book_1640_acceptance import (
    ACQUISITION,
    CONTRACT,
    EDITION,
    EDITION_ID,
    EVIDENCE,
    ROOT,
    SOURCE,
    SOURCE_SHA256,
    WORK,
    WORK_ID,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path
from ocd_kernel.tei.validate import validate_file


ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
NOTICE = EDITION / "README.source.md"
RECEIPT_NAME = "bay-psalm-book-1640-stage-receipt.json"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"Bay Psalm Book JSON object required: {path}")
    return value


def _check_scope(root: Path, stage: Path, before: dict[str, str], after: dict[str, str]) -> None:
    if set(before) != {
        "SOURCE_NOTICE.md",
        "state.json",
        "work.json",
        (
            "forms/bay-psalm-book-1640-tcp-retained/editions/"
            "bay-psalm-book-1640-tcp-electronic/acquisitions/"
            "bay-psalm-book-1640-tcp-acquired.json"
        ),
    }:
        raise PipelineError("Bay Psalm Book complete canonical preimage differs")
    allowed = {
        "SOURCE_NOTICE.md",
        "state.json",
        "work.json",
        ACQUISITION.relative_to(WORK).as_posix(),
        ACCEPTANCE.relative_to(WORK).as_posix(),
        MASTER.relative_to(WORK).as_posix(),
        NOTICE.relative_to(WORK).as_posix(),
    }
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if relative in allowed or (
            relative.startswith(evidence_prefix) and relative not in before and relative in after
        ):
            continue
        raise PipelineError(f"Bay Psalm Book staged change exceeds work scope: {relative}")

    old_work = _read(root / WORK / "work.json")
    expected_work = json.loads(json.dumps(old_work))
    form = expected_work["textual_forms"][0]
    edition = form["editions"][0]
    if form.get("language") is not None or any(
        edition.get(name) is not None for name in ("language", "category")
    ):
        raise PipelineError("Bay Psalm Book category/language preimage differs")
    form["language"] = "en"
    edition["language"] = "en"
    edition["category"] = "poetry"
    if _read(stage / WORK / "work.json") != expected_work:
        raise PipelineError("Bay Psalm Book staged identity differs beyond language/category")

    old_acquisition = validate_acquisition(root / ACQUISITION, root=root)
    staged_acquisition = validate_acquisition(_io_path(stage / ACQUISITION), root=_io_path(stage))
    if staged_acquisition != old_acquisition:
        raise PipelineError("Bay Psalm Book acquisition changed")
    if (
        old_acquisition.get("source_path") != SOURCE.as_posix()
        or old_acquisition.get("source_sha256") != SOURCE_SHA256
        or old_acquisition.get("source_bytes") != 938122
        or len(old_acquisition.get("retained_files", [])) != 1
    ):
        raise PipelineError("Bay Psalm Book source preimage differs")
    retained = old_acquisition["retained_files"][0]
    if (
        retained.get("path") != SOURCE.as_posix()
        or retained.get("sha256") != SOURCE_SHA256
        or retained.get("bytes") != 938122
        or retained.get("scope") != old_acquisition.get("source_scope")
    ):
        raise PipelineError("Bay Psalm Book retained member differs")

    old_state = _read(root / WORK / "state.json")
    new_state = _read(stage / WORK / "state.json")
    old_targets = {item["target_id"]: item for item in old_state["targets"]}
    new_targets = {item["target_id"]: item for item in new_state["targets"]}
    if old_targets.keys() != new_targets.keys():
        raise PipelineError("Bay Psalm Book target identities differ")
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id != EDITION_ID:
            if new != old:
                raise PipelineError("Bay Psalm Book acquisition state changed")
            continue
        additions = [MASTER.as_posix(), ACCEPTANCE.as_posix()]
        if (
            old.get("stage") != "review"
            or new.get("stage") != "accepted"
            or new.get("evidence") != old.get("evidence") + additions
            or any(
                old.get(key) != new.get(key)
                for key in old
                if key not in {"stage", "reason", "updated_at", "evidence"}
            )
        ):
            raise PipelineError("Bay Psalm Book edition state transition differs")

    source = _io_path(stage / SOURCE).read_bytes()
    master = _io_path(stage / MASTER).read_bytes()
    if _sha(stage / SOURCE) != SOURCE_SHA256 or master.split(b"</teiHeader>", 1)[1] != source.split(
        b"</teiHeader>", 1
    )[1]:
        raise PipelineError("Bay Psalm Book accepted master changed retained text")
    if errors := validate_file(_io_path(stage / MASTER)):
        raise PipelineError(f"Bay Psalm Book accepted master fails P5: {errors[:3]}")
    accepted = validate_acceptance(_io_path(stage / ACCEPTANCE), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if (
        accepted["identity"]["work_id"] != WORK_ID
        or accepted["promotion"]["status"] != "promoted"
        or accepted["decision"]["human_decision"]["status"] != "not-recorded"
        or accepted["promotion"]["master"]["sha256"] != after[MASTER.relative_to(WORK).as_posix()]
    ):
        raise PipelineError("Bay Psalm Book staged acceptance differs")
    if _io_path(stage / NOTICE).read_bytes() != _io_path(stage / WORK / "SOURCE_NOTICE.md").read_bytes():
        raise PipelineError("Bay Psalm Book staged human-visible source notice differs")


def _check_dependencies(stage: Path) -> None:
    prefix = WORK.as_posix() + "/"
    for relative, checksum in _files(stage).items():
        if relative.startswith(prefix) or relative.startswith("_c/") or relative == RECEIPT_NAME:
            continue
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise PipelineError(f"unsafe Bay Psalm Book staged dependency: {relative}")
        canonical = ROOT / path
        if not _io_path(canonical).is_file() or _sha(canonical) != checksum:
            raise PipelineError(f"Bay Psalm Book external dependency differs: {relative}")


def preflight(stage: Path, receipt_sha256: str, *, root_override: Path | None = None) -> dict:
    stage = stage.resolve(strict=True)
    root = ROOT.resolve(strict=True) if root_override is None else root_override.resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Bay Psalm Book install roots overlap")
    receipt_path = stage / RECEIPT_NAME
    if _sha(receipt_path) != receipt_sha256:
        raise PipelineError("Bay Psalm Book frozen stage receipt differs")
    receipt = _read(receipt_path)
    if (
        receipt.get("contract") != CONTRACT
        or receipt.get("status") != "staged-only-pending-review"
        or receipt.get("work_id") != WORK_ID
        or receipt.get("installation") != "not-performed"
        or Path(receipt.get("stage_root", "")).resolve(strict=True) != stage
        or Path(receipt.get("canonical_root", "")).resolve(strict=True) != ROOT.resolve(strict=True)
    ):
        raise PipelineError("Bay Psalm Book stage receipt contract or roots differ")
    before, after = _files(root / WORK), _files(stage / WORK)
    if before != receipt.get("before") or after != receipt.get("after"):
        raise PipelineError("Bay Psalm Book current preimage or frozen generation differs")
    _check_scope(root, stage, before, after)
    _check_dependencies(stage)
    if (
        receipt.get("source_sha256") != SOURCE_SHA256
        or receipt.get("accepted_master_sha256") != after[MASTER.relative_to(WORK).as_posix()]
        or receipt.get("rights") != "unassessed-source-notice-prepared"
        or receipt.get("human_visual_review") != "not-recorded"
    ):
        raise PipelineError("Bay Psalm Book frozen source/master/review pins differ")
    if (
        receipt.get("projection_status") != "blocked-shared-projector"
        or receipt.get("projection_rows") != 0
        or receipt.get("projection_error") != "unsupported native glyph reference or content"
    ):
        raise PipelineError("Bay Psalm Book frozen Step 3 projection hold differs")
    try:
        project_accepted_document(
            _io_path(stage), acceptance_path=_io_path(stage / ACCEPTANCE), category="poetry"
        )
    except PipelineError as exc:
        if str(exc) != receipt["projection_error"]:
            raise PipelineError("Bay Psalm Book Step 3 projector error changed") from exc
    else:
        raise PipelineError("Bay Psalm Book Step 3 projector hold no longer reproduces; refresh stage")
    return {
        "status": "ready-for-coordinator-review",
        "stage": stage.as_posix(),
        "receipt_sha256": receipt_sha256,
        "before_files": len(before),
        "after_files": len(after),
        "projection_rows": 0,
        "projection_status": receipt["projection_status"],
        "installation": "not-performed",
    }


def install(
    stage: Path,
    receipt_sha256: str,
    *,
    fail_at: Callable[[str], None] | None = None,
) -> dict:
    preflight(stage, receipt_sha256)
    target = ROOT / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        preflight(stage, receipt_sha256)
        receipt = _read(stage / RECEIPT_NAME)

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("installed Bay Psalm Book generation differs")
                validate_acceptance(_io_path(ROOT / ACCEPTANCE), root=_io_path(ROOT))
                validate_state(_io_path(target / "state.json"), root=_io_path(ROOT))
                try:
                    project_accepted_document(
                        _io_path(ROOT),
                        acceptance_path=_io_path(ROOT / ACCEPTANCE),
                        category="poetry",
                    )
                except PipelineError as exc:
                    if str(exc) != receipt["projection_error"]:
                        raise PipelineError(
                            "installed Bay Psalm Book Step 3 projector error changed"
                        ) from exc
                else:
                    raise PipelineError(
                        "installed Bay Psalm Book Step 3 hold unexpectedly resolved during install"
                    )
            if fail_at is not None:
                fail_at(point)

        return _commit_generation(
            ROOT,
            target,
            stage / WORK,
            work_id=WORK_ID,
            before=receipt["before"],
            after=receipt["after"],
            existed=True,
            replacement=False,
            operation_kind="bay-psalm-n00001-electronic-install",
            result_status="installed-and-validated",
            accepted_editions=1,
            fail_at=checkpoint,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = (
        install(args.stage, args.receipt_sha256)
        if args.apply
        else preflight(args.stage, args.receipt_sha256)
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
