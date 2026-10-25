"""Read-only preflight or guardedly install Gregory Select Letters NPNF2-07.

Default execution does not write canonical files. ``--apply`` is for the
independent reviewer after auditing the frozen stage and source boundary.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import uuid

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from ocd_kernel.tei.validate import validate_file

from build.tei.npnf2_lib046_gregory_select_letters_oracle import _oracle
from build.tools.stage_gregory_select_letters_npnf207_acceptance import (
    CONTRACT, MANIFEST, MANIFEST_SHA, PACKAGE, PACKAGE_SHA, ROOT, ROOT_TITLE,
    SOURCE, SOURCE_SHA, WORK_ID,
)


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/gregory-select-letters-npnf207-acceptance-stage-20260928-v2")
RECEIPT = STAGE / "stage-receipt.json"
RECEIPT_SHA = "4ef340e831848baadf3e4c4fce6a08d1677612e42074f5c65a8fb1953b165436"
WORK = Path("library/works") / WORK_ID
EDITION = (Path("forms") / f"{WORK_ID}-english" / "editions" /
           f"{WORK_ID}-retained-electronic-witness")
ACQUISITION = (EDITION / "acquisitions" / f"{WORK_ID}-retained-source.json").as_posix()
ACCEPTANCE = (EDITION / "acceptance.json").as_posix()
MASTER = (EDITION / "master.tei.xml").as_posix()
EVIDENCE = "integration/gregory-select-letters-npnf207-selected-v1/"
FIXTURE_MARKER = ".ocd-gregory-select-letters-npnf207-fixture"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(_io_path(path).read_bytes())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dependencies(expected: dict[str, str]) -> None:
    actual = {key: value for key, value in _files(STAGE).items()
              if not key.startswith(WORK.as_posix() + "/") and key != RECEIPT.name}
    if actual != expected:
        raise PipelineError("Gregory Select Letters staged dependencies differ")
    for relative, digest in expected.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise PipelineError(f"unsafe Gregory Select Letters dependency: {relative}")
        live = (resolve_repo_path(ROOT, relative)
                if path.parts[0] in {"raw", "reports", "exports"} else ROOT / path)
        if not _io_path(live).is_file() or _sha(live) != digest:
            raise PipelineError(f"Gregory Select Letters source or evidence changed: {relative}")


def _scope(root: Path, row: dict) -> None:
    before, after = _files(root / WORK), _files(STAGE / WORK)
    if (row["work_id"] != WORK_ID or Path(row["work_path"]) != WORK
            or row["before"] != before or row["after"] != after
            or len(before) != 3 or len(after) != 21
            or row["source_path"] != SOURCE.as_posix()
            or row["source_sha256"] != SOURCE_SHA
            or row["source_manifest_sha256"] != MANIFEST_SHA
            or row["candidate_package_sha256"] != PACKAGE_SHA
            or row["selected_root_id"] != "iv" or row["native_rows"] != 1):
        raise PipelineError("Gregory Select Letters receipt or acquired work differs")
    if set(before) != {"work.json", "state.json", ACQUISITION}:
        raise PipelineError("Gregory Select Letters prior generation differs")
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if relative in {"work.json", "state.json", ACCEPTANCE, MASTER}:
            continue
        if relative.startswith(EVIDENCE) and relative not in before and relative in after:
            continue
        raise PipelineError(f"Gregory Select Letters unrelated file changed: {relative}")
    if (before[ACQUISITION] != after[ACQUISITION]
            or after[MASTER] != row["new_master_sha256"]
            or after[ACCEPTANCE] != row["new_acceptance_sha256"]
            or after[EVIDENCE + "candidate.tei.xml"] != row["new_master_sha256"]):
        raise PipelineError("Gregory Select Letters acquisition or master differs")
    prior_work = _json(root / WORK / "work.json")
    staged_work = _json(STAGE / WORK / "work.json")
    expected_work = json.loads(json.dumps(prior_work))
    edition = expected_work["textual_forms"][0]["editions"][0]
    if edition.get("category") is not None:
        raise PipelineError("Gregory Select Letters edition already categorized")
    edition["category"] = "prose"
    if staged_work != expected_work:
        raise PipelineError("Gregory Select Letters identity changed beyond prose category")
    prior_state = _json(root / WORK / "state.json")
    staged_state = _json(STAGE / WORK / "state.json")
    if len(prior_state["targets"]) != len(staged_state["targets"]):
        raise PipelineError("Gregory Select Letters state target count changed")
    for old, new in zip(prior_state["targets"], staged_state["targets"], strict=True):
        if old["target_type"] == "acquisition":
            if old != new:
                raise PipelineError("Gregory Select Letters acquisition state changed")
        elif old["target_type"] == "edition":
            expected = dict(old)
            expected.update(stage="accepted", reason=PROMOTED_MASTER_REASON,
                            updated_at=new["updated_at"],
                            evidence=old["evidence"] + [
                                (WORK / MASTER).as_posix(), (WORK / ACCEPTANCE).as_posix()])
            if new != expected:
                raise PipelineError("Gregory Select Letters edition state transition differs")
        else:
            raise PipelineError("Gregory Select Letters unexpected state target")
    acceptance_path = STAGE / WORK / ACCEPTANCE
    accepted = validate_acceptance(_io_path(acceptance_path), root=_io_path(STAGE))
    validate_state(_io_path(STAGE / WORK / "state.json"), root=_io_path(STAGE))
    if (accepted["identity"]["work_id"] != WORK_ID
            or accepted["scope"]["kind"] != "selection"
            or accepted["promotion"]["master"]["sha256"] != row["new_master_sha256"]
            or accepted["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError("Gregory Select Letters selected acceptance differs")
    accounting = _json(STAGE / WORK / EVIDENCE / "source-accounting.json")
    acquisition = _json(root / WORK / ACQUISITION)
    if (accounting["selected_root_id"] != "iv"
            or accounting["selected_root_title"] != ROOT_TITLE
            or accounting["selected_div2_ids"] != ["iv.i", "iv.ii", "iv.iii", "iv.iv"]
            or accounting["excluded_top_level_div1_ids"] != ["i", "ii", "iii", "v"]
            or accounting["source"]["source_scope"] != acquisition["retained_files"][0]["scope"]
            or accounting["accepted_scope"]["kind"] != "selection"):
        raise PipelineError("Gregory Select Letters acquisition/selection boundary differs")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(PACKAGE)
    report = validate(manifest, package, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or report.status != "pass"):
        raise PipelineError("Gregory Select Letters current source oracle differs")
    original = package.member_bytes("content.tei.xml")
    bound = _io_path(STAGE / WORK / MASTER).read_bytes()
    header, body = bound.split(b"</teiHeader>", 1)
    if (original.split(b"</teiHeader>", 1)[1] != body
            or b"sourced via CCEL.org" not in header
            or b'<title type="retained-electronic-title">' not in header
            or b'<note type="retained-electronic-title-source-label" n="npnf207">Electronic volume title source @n: npnf207</note>' not in header
            or ROOT_TITLE.encode("utf-8") not in header):
        raise PipelineError("Gregory Select Letters source text, title label, or credit differs")
    if errors := validate_file(_io_path(STAGE / WORK / MASTER)):
        raise PipelineError(f"Gregory Select Letters P5 errors: {errors[:2]}")
    projected = project_accepted_prose(_io_path(STAGE), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(STAGE), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"Gregory Select Letters native prose differs: {errors[:2]}")


def preflight(*, root_override: Path | None = None) -> tuple[dict, Path, bool]:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError("Gregory Select Letters frozen receipt differs")
    receipt = _json(RECEIPT)
    if (receipt.get("contract") != CONTRACT or receipt.get("status") != "staged-only"
            or receipt.get("installation") != "not-performed"
            or receipt.get("rights") != "not-assessed"
            or Path(receipt.get("stage_root", "")).resolve(strict=True) != STAGE.resolve(strict=True)
            or Path(receipt.get("canonical_root", "")).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError("Gregory Select Letters stage contract or roots differ")
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError("Gregory Select Letters override requires marked review-area fixture")
    if root == STAGE or root in STAGE.parents or STAGE in root.parents:
        raise PipelineError("Gregory Select Letters install roots overlap")
    _dependencies(receipt["dependencies"])
    _scope(root, receipt["work"])
    return receipt, root, fixture


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError("Gregory Select Letters incoming generation already exists")
    _io_path(target).mkdir(parents=True)
    for relative, digest in expected.items():
        origin, destination = _io_path(source / relative), _io_path(target / relative)
        if not origin.is_file() or _sha(origin) != digest:
            raise PipelineError(f"Gregory Select Letters staged file changed: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    if _files(target) != expected:
        raise PipelineError("Gregory Select Letters incoming generation differs")


def install(*, root_override: Path | None = None,
            fail_at: Callable[[str], None] | None = None) -> dict:
    receipt, root, fixture = preflight(root_override=root_override)
    row = receipt["work"]
    target, source = root / WORK, STAGE / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != row["before"] or _files(source) != row["after"]:
            raise PipelineError("Gregory Select Letters work changed while acquiring lock")
        _dependencies(receipt["dependencies"])
        operation = root / "library/.sidecar-operations" / f"gsl-{uuid.uuid4().hex[:12]}"
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in
                                          ("incoming", "previous", "failed-new"))
        journal = dict(contract="ocd-gregory-select-letters-npnf207-work-swap-v1",
                       work_id=WORK_ID, phase="created", before=row["before"],
                       after=row["after"], receipt=RECEIPT.as_posix(), updated_at=_now())
        _write_json_durable(operation / "operation.json", journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, row["after"])
            if _files(target) != row["before"]:
                raise PipelineError("Gregory Select Letters work changed during incoming copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-copy")
            _dependencies(receipt["dependencies"])
            os.replace(_io_path(target), _io_path(previous))
            moved = True
            journal.update(phase="previous-moved", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-old-rename")
            os.replace(_io_path(incoming), _io_path(target))
            live = True
            journal.update(phase="new-live", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-new-rename")
            if _files(target) != row["after"]:
                raise PipelineError("Gregory Select Letters installed generation differs")
            if not fixture:
                validate_acceptance(_io_path(target / ACCEPTANCE), root=_io_path(root))
                validate_state(_io_path(target / "state.json"), root=_io_path(root))
            if fail_at:
                fail_at("after-validation")
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            return dict(status="installed-and-validated", work_id=WORK_ID,
                        operation=operation.as_posix(), before_count=len(row["before"]),
                        after_count=len(row["after"]), master_sha256=row["new_master_sha256"])
        except BaseException:
            try:
                if live:
                    if _files(target) != row["after"]:
                        raise PipelineError("Gregory Select Letters live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row["before"]:
                        raise PipelineError("Gregory Select Letters prior generation differs during rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != row["before"]:
                        raise PipelineError("Gregory Select Letters rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap",
                               updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
            except BaseException as exc:
                journal.update(phase="recovery-required", rollback_error=str(exc),
                               updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
                raise PipelineError(f"Gregory Select Letters rollback requires recovery: {operation}") from exc
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install()
    else:
        receipt, _, _ = preflight()
        result = dict(status="ready-for-review", work_id=WORK_ID,
                      receipt_sha256=RECEIPT_SHA,
                      before_count=len(receipt["work"]["before"]),
                      after_count=len(receipt["work"]["after"]),
                      master_sha256=receipt["work"]["new_master_sha256"])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
