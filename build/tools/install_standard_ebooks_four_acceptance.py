"""Read-only preflight or independently authorized guarded Standard Ebooks install."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Callable
import uuid

from build.tei.se_candidate_oracle import _oracle
from build.tools.stage_standard_ebooks_four_acceptance import BASE, CASES, CONTRACT, ROOT, _spine
from ocd_kernel.library._common import PipelineError
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from ocd_kernel.tei.validate import validate_file

STAGES = {
    "orthodoxy": BASE / "orthodoxy-acceptance-stage-20260928-v3",
    "heretics": BASE / "heretics-acceptance-stage-20260928-v1",
    "george-macdonald-unspoken-sermons": BASE.parent / "se4-unspoken-v1",
    "the-everlasting-man": BASE.parent / "se4-everlasting-v1",
}
RECEIPT_SHA = {
    "orthodoxy": "65fbafbedcdfb0a75fa9cd0e31049412cb34628df1ec2d398a161c3fde9caedb",
    "heretics": "f9bcff410b3d898e9804f665ee27a85c5f18fea10ef2e62de728e22841874cf9",
    "george-macdonald-unspoken-sermons": "4ff6f4ed04da2d727903774a8b64a746c792e7837cbcf2cd4ebb60d5264aa1b4",
    "the-everlasting-man": "1cf6063a9ce4292d3d0791fadd033a34f17abe313ee2bdc9c33fec395678a107",
}
FIXTURE_MARKER = ".ocd-standard-ebooks-four-fixture"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(_io_path(path).read_bytes())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def preflight(work_id: str, *, root_override: Path | None = None) -> dict:
    if work_id not in CASES:
        raise PipelineError("unlisted Standard Ebooks work")
    stage = STAGES[work_id]
    receipt_path = stage / "stage-receipt.json"
    if not _io_path(receipt_path).is_file() or _sha(receipt_path) != RECEIPT_SHA[work_id]:
        raise PipelineError("frozen Standard Ebooks receipt changed")
    receipt = _json(receipt_path)
    root = root_override.resolve(strict=True) if root_override else ROOT.resolve(strict=True)
    if root_override is not None:
        scratch = BASE.parent.resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError("fixture override requires a marked external review root")
    if (receipt.get("contract") != CONTRACT or receipt.get("status") != "staged-only"
            or receipt.get("installation") != "not-performed" or receipt.get("rights") != "not-assessed"
            or Path(receipt.get("stage_root", "")).resolve(strict=True) != stage.resolve(strict=True)
            or Path(receipt.get("canonical_root", "")).resolve(strict=True) != ROOT.resolve(strict=True)
            or root == stage or root in stage.parents or stage in root.parents):
        raise PipelineError("Standard Ebooks stage contract or roots differ")
    row = receipt["work"]
    work_rel = Path("library/works") / work_id
    if (row.get("work_id") != work_id or row.get("work_path") != work_rel.as_posix()
            or row.get("before") != _files(root / work_rel)
            or row.get("after") != _files(stage / work_rel)
            or row.get("opf_spine_count") != CASES[work_id][2]
            or row.get("native_rows") != CASES[work_id][2]):
        raise PipelineError("Standard Ebooks stage or live work generation changed")
    expected_deps = receipt["dependencies"]
    actual_deps = {key: value for key, value in _files(stage).items()
                   if not key.startswith(work_rel.as_posix() + "/") and key != "stage-receipt.json"}
    if actual_deps != expected_deps:
        raise PipelineError("Standard Ebooks staged dependency set changed")
    for relative, digest in expected_deps.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or _sha(ROOT / path) != digest:
            raise PipelineError(f"Standard Ebooks source or evidence changed: {relative}")
    before, after = row["before"], row["after"]
    if any(after.get(name) != digest for name, digest in before.items()
           if name not in {"work.json", "state.json"}):
        raise PipelineError("Standard Ebooks prior work authority changed")
    prior_work = _json(root / work_rel / "work.json")
    proposed_work = _json(stage / work_rel / "work.json")
    expected_work = json.loads(json.dumps(prior_work))
    if expected_work["textual_forms"][0]["editions"][0].get("category") is not None:
        raise PipelineError("Standard Ebooks category was already set")
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if proposed_work != expected_work:
        raise PipelineError("Standard Ebooks work identity changed beyond prose category")
    prior_state = _json(root / work_rel / "state.json")
    proposed_state = _json(stage / work_rel / "state.json")
    if len(prior_state["targets"]) != len(proposed_state["targets"]):
        raise PipelineError("Standard Ebooks target count changed")
    for old, new in zip(prior_state["targets"], proposed_state["targets"], strict=True):
        if old["target_type"] == "acquisition":
            if new != old:
                raise PipelineError("Standard Ebooks acquired source state changed")
        elif old["target_type"] == "edition":
            expected_state = dict(old)
            expected_state.update(stage="accepted", reason=PROMOTED_MASTER_REASON,
                                  updated_at=new["updated_at"],
                                  evidence=old["evidence"] + [
                                      (work_rel / "forms" / expected_work["textual_forms"][0]["textual_form_id"]
                                       / "editions" / expected_work["textual_forms"][0]["editions"][0]["edition_id"]
                                       / "master.tei.xml").as_posix(),
                                      (work_rel / "forms" / expected_work["textual_forms"][0]["textual_form_id"]
                                       / "editions" / expected_work["textual_forms"][0]["editions"][0]["edition_id"]
                                       / "acceptance.json").as_posix()])
            if new != expected_state:
                raise PipelineError("Standard Ebooks edition state differs")
        else:
            raise PipelineError("Standard Ebooks unexpected state target")
    new_files = set(after) - set(before)
    evidence = "integration/current-standard-ebooks-spine-v1/"
    if any(not (name.startswith(evidence) or name.endswith("/acceptance.json")
                or name.endswith("/master.tei.xml")) for name in new_files):
        raise PipelineError("Standard Ebooks stage adds an unrelated work path")
    acceptance_paths = [name for name in after if name.endswith("/acceptance.json")]
    master_paths = [name for name in after if name.endswith("/master.tei.xml")]
    if len(acceptance_paths) != 1 or len(master_paths) != 1:
        raise PipelineError("Standard Ebooks stage requires one accepted edition")
    acceptance_path = stage / work_rel / acceptance_paths[0]
    master_path = stage / work_rel / master_paths[0]
    if (_sha(acceptance_path) != row["new_acceptance_sha256"]
            or _sha(master_path) != row["new_master_sha256"]
            or after[evidence + "candidate.tei.xml"] != row["new_master_sha256"]):
        raise PipelineError("Standard Ebooks accepted master binding differs")
    accepted = validate_acceptance(_io_path(acceptance_path), root=_io_path(stage))
    validate_state(_io_path(stage / work_rel / "state.json"), root=_io_path(stage))
    if (accepted["identity"]["work_id"] != work_id or accepted["scope"]["kind"] != "edition"
            or accepted["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError("Standard Ebooks accepted scope or decision changed")
    source_name, short, count = CASES[work_id]
    manifest_rel = Path("sources/standard-ebooks") / source_name / f"{work_id}.source-manifest.json"
    manifest = SourceManifest.load(ROOT / manifest_rel, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(BASE / f"{short}-current-20260928-v1" / "package")
    report = validate(manifest, package, _oracle)
    if (manifest.sha256 != row["source_manifest_sha256"]
            or package.sha256 != row["candidate_package_sha256"]
            or report.sha256 != row["oracle_report_sha256"]):
        raise PipelineError("Standard Ebooks current source oracle changed")
    original = package.member_bytes("content.tei.xml")
    master = _io_path(master_path).read_bytes()
    if (original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
            or b'<note type="source-credit">Standard Ebooks electronic edition</note>' not in master):
        raise PipelineError("Standard Ebooks readable text or visible credit changed")
    acquisition = _json(stage / work_rel / "forms" / accepted["identity"]["textual_form_id"]
                        / "editions" / accepted["identity"]["edition_id"] / "acquisitions"
                        / f"{accepted['identity']['acquisition_id']}.json")
    if [item["path"] for item in acquisition["retained_files"]] != _spine(row["source_path"]):
        raise PipelineError("Standard Ebooks acquired OPF spine changed")
    if errors := validate_file(_io_path(master_path)):
        raise PipelineError(f"Standard Ebooks accepted P5 differs: {errors[:2]}")
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(acceptance_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != count:
        raise PipelineError(f"Standard Ebooks accepted native projection differs: {errors[:2]}")
    return {"work_id": work_id, "status": "ready-for-review", "before": len(before),
            "after": len(after), "native_rows": count, "receipt_sha256": RECEIPT_SHA[work_id]}


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError("Standard Ebooks incoming generation already exists")
    _io_path(target).mkdir(parents=True)
    for relative, digest in expected.items():
        origin, destination = _io_path(source / relative), _io_path(target / relative)
        if not origin.is_file() or _sha(origin) != digest:
            raise PipelineError(f"Standard Ebooks staged file changed: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    if _files(target) != expected:
        raise PipelineError("Standard Ebooks incoming generation differs")


def install(work_id: str, *, root_override: Path | None = None,
            fail_at: Callable[[str], None] | None = None) -> dict:
    preflight(work_id, root_override=root_override)
    root = root_override.resolve(strict=True) if root_override else ROOT.resolve(strict=True)
    receipt = _json(STAGES[work_id] / "stage-receipt.json")
    row = receipt["work"]
    work_rel = Path("library/works") / work_id
    target, source = root / work_rel, STAGES[work_id] / work_rel
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != row["before"] or _files(source) != row["after"]:
            raise PipelineError("Standard Ebooks work changed while acquiring lock")
        if any(_sha(ROOT / relative) != digest for relative, digest in receipt["dependencies"].items()):
            raise PipelineError("Standard Ebooks source changed while acquiring lock")
        operation = root / "library/.sidecar-operations" / f"se4-{work_id[:12]}-{uuid.uuid4().hex[:12]}"
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in
                                          ("incoming", "previous", "failed-new"))
        journal = {"contract": "ocd-standard-ebooks-four-work-swap-v1", "work_id": work_id,
                   "phase": "created", "before": row["before"], "after": row["after"],
                   "receipt": (STAGES[work_id] / "stage-receipt.json").as_posix(),
                   "updated_at": _now()}
        _write_json_durable(operation / "operation.json", journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, row["after"])
            if _files(target) != row["before"]:
                raise PipelineError("Standard Ebooks live work changed during copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-copy")
            if any(_sha(ROOT / relative) != digest for relative, digest in receipt["dependencies"].items()):
                raise PipelineError("Standard Ebooks source changed before swap")
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
                raise PipelineError("Standard Ebooks installed generation differs")
            if root_override is None:
                acceptance = next(_io_path(target).rglob("acceptance.json"))
                validate_acceptance(acceptance, root=_io_path(root))
                validate_state(_io_path(target / "state.json"), root=_io_path(root))
            if fail_at:
                fail_at("after-validation")
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            return {"status": "installed-and-validated", "work_id": work_id,
                    "operation": operation.as_posix(), "before": len(row["before"]),
                    "after": len(row["after"]), "master_sha256": row["new_master_sha256"]}
        except BaseException:
            try:
                if live:
                    if _files(target) != row["after"]:
                        raise PipelineError("Standard Ebooks live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row["before"]:
                        raise PipelineError("Standard Ebooks prior generation differs during rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != row["before"]:
                        raise PipelineError("Standard Ebooks rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap", updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
            except BaseException as exc:
                journal.update(phase="recovery-required", rollback_error=str(exc), updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
                raise PipelineError(f"Standard Ebooks rollback requires recovery: {operation}") from exc
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True, choices=CASES)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = preflight(args.work_id)
    if args.apply:
        result = install(args.work_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
