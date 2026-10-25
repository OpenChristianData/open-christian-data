"""Preflight or guardedly install one selected LIB-028 NPNF2-02 history.

The default command is read-only. ``--apply`` is reserved for the reviewing
operator and swaps only the named work's complete sidecar generation.
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

from lxml import etree

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path, _write_json_durable
from ocd_kernel.tei.validate import validate_file

from build.tei.lib028_oracle import _oracle
from build.tools.stage_lib028_socrates_sozomen_acceptance import (
    CONTRACT, MANIFEST, MANIFEST_SHA, PACKAGE, PACKAGE_SHA, ROOT, ROUTES,
    SOURCE, SOURCE_SHA, _node_sha,
)


STAGE_ROOT = Path("D:/Library/Open Christian Data/candidate-reviews/lib028-npnf202-two-selected-stage-20260928-v4")
RECEIPT_SHA = {
    "socrates-ecclesiastical-history": "f7382113b453283f0a8b67e284e3e66551e864c312fb0211e5d20d4d0774d102",
    "sozomen-ecclesiastical-history": "b21fdda6311a29de4976901f793bffcd8cf777c28ea2f74a5f3518776ebd6294",
}
FIXTURE_MARKER = ".ocd-lib028-npnf202-two-selected-fixture"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    return json.loads(_io_path(path).read_bytes())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dependencies(stage: Path, work_id: str, expected: dict[str, str]) -> None:
    actual = {key: value for key, value in _files(stage).items()
              if not key.startswith(f"library/works/{work_id}/") and key != "stage-receipt.json"}
    if actual != expected:
        raise PipelineError(f"LIB028 {work_id} staged dependencies differ")
    for relative, digest in expected.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise PipelineError(f"unsafe LIB028 dependency: {relative}")
        live = (resolve_repo_path(ROOT, relative)
                if path.parts[0] in {"raw", "reports", "exports"} else ROOT / path)
        if not _io_path(live).is_file() or _sha(live) != digest:
            raise PipelineError(f"LIB028 source or evidence changed: {relative}")


def _scope(root: Path, stage: Path, work_id: str, row: dict) -> None:
    route = ROUTES[work_id]
    work_path = Path("library/works") / work_id
    before, after = _files(root / work_path), _files(stage / work_path)
    if (row["work_id"] != work_id or Path(row["work_path"]) != work_path
            or row["before"] != before or row["after"] != after
            or len(before) != 3 or len(after) != 21
            or row["source_path"] != SOURCE.as_posix()
            or row["source_sha256"] != SOURCE_SHA
            or row["selected_root_id"] != route["source_id"]
            or row["selected_feature_count"] != route["features"]
            or row["native_rows"] != 1):
        raise PipelineError(f"LIB028 {work_id} receipt or acquired work differs")
    edition = (Path("forms") / f"{work_id}-ccel-npnf202-retained-en" / "editions"
               / f"{work_id}-ccel-npnf202-electronic")
    acquisition = (edition / "acquisitions" / f"{work_id}-ccel-npnf202-acquired.json").as_posix()
    acceptance = (edition / "acceptance.json").as_posix()
    master = (edition / "master.tei.xml").as_posix()
    evidence = f"integration/{work_id}-lib028-npnf202-selected-v1/"
    if set(before) != {"work.json", "state.json", acquisition}:
        raise PipelineError(f"LIB028 {work_id} prior work generation differs")
    for relative in set(before) | set(after):
        if before.get(relative) == after.get(relative):
            continue
        if relative in {"work.json", "state.json", acceptance, master}:
            continue
        if relative.startswith(evidence) and relative not in before and relative in after:
            continue
        raise PipelineError(f"LIB028 {work_id} unrelated file changed: {relative}")
    if (before[acquisition] != after[acquisition]
            or after[master] != row["new_master_sha256"]
            or after[acceptance] != row["new_acceptance_sha256"]
            or after[evidence + "candidate.tei.xml"] != row["new_master_sha256"]):
        raise PipelineError(f"LIB028 {work_id} acquisition or accepted master differs")
    prior_work = _json(root / work_path / "work.json")
    staged_work = _json(stage / work_path / "work.json")
    expected_work = json.loads(json.dumps(prior_work))
    category = expected_work["textual_forms"][0]["editions"][0]
    if category.get("category") is not None:
        raise PipelineError(f"LIB028 {work_id} edition already categorized")
    category["category"] = "prose"
    if staged_work != expected_work:
        raise PipelineError(f"LIB028 {work_id} identity changed beyond prose category")
    prior_state = _json(root / work_path / "state.json")
    staged_state = _json(stage / work_path / "state.json")
    if len(prior_state["targets"]) != len(staged_state["targets"]):
        raise PipelineError(f"LIB028 {work_id} state target count differs")
    for old, new in zip(prior_state["targets"], staged_state["targets"], strict=True):
        if old["target_type"] == "acquisition":
            if old != new:
                raise PipelineError(f"LIB028 {work_id} acquisition state changed")
        elif old["target_type"] == "edition":
            expected = dict(old)
            expected.update(stage="accepted", reason=PROMOTED_MASTER_REASON,
                            updated_at=new["updated_at"],
                            evidence=old["evidence"] + [
                                (work_path / master).as_posix(),
                                (work_path / acceptance).as_posix()])
            if new != expected:
                raise PipelineError(f"LIB028 {work_id} edition state differs")
        else:
            raise PipelineError(f"LIB028 {work_id} unexpected state target")
    accepted_path = stage / work_path / acceptance
    accepted = validate_acceptance(_io_path(accepted_path), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / "state.json"), root=_io_path(stage))
    if (accepted["identity"]["work_id"] != work_id
            or accepted["scope"]["kind"] != "selection"
            or accepted["promotion"]["master"]["sha256"] != row["new_master_sha256"]
            or accepted["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError(f"LIB028 {work_id} selected acceptance differs")
    accounting = _json(stage / work_path / evidence / "source-accounting.json")
    if (accounting["selected_root_id"] != route["source_id"]
            or accounting["selected_root_title"] != route["title"]
            or accounting["selected_feature_count"] != route["features"]
            or accounting["selected_tei_node_sha256"] != row["selected_tei_node_sha256"]
            or accounting["source"]["source_scope"] !=
            _json(root / work_path / acquisition)["retained_files"][0]["scope"]
            or accounting["accepted_scope"]["kind"] != "selection"):
        raise PipelineError(f"LIB028 {work_id} acquisition/selection boundary differs")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    package = CandidatePackage.load(PACKAGE)
    report = validate(manifest, package, _oracle)
    if (manifest.sha256 != MANIFEST_SHA or package.sha256 != PACKAGE_SHA
            or row["source_manifest_sha256"] != MANIFEST_SHA
            or row["candidate_package_sha256"] != PACKAGE_SHA
            or report.status != "pass"):
        raise PipelineError(f"LIB028 {work_id} current source oracle differs")
    original = etree.fromstring(package.member_bytes("content.tei.xml"),
                                etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    selected = [node for node in original.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
                if node.get("subtype") == work_id]
    bound = _io_path(stage / work_path / master).read_bytes()
    accepted_tree = etree.fromstring(bound, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    accepted_body = accepted_tree.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    header = accepted_tree.find("{http://www.tei-c.org/ns/1.0}teiHeader")
    bibliography_ids = [node.get("{http://www.w3.org/XML/1998/namespace}id")
                        for node in header.findall(".//{http://www.tei-c.org/ns/1.0}sourceDesc/{http://www.tei-c.org/ns/1.0}bibl")
                        if node.get("{http://www.w3.org/XML/1998/namespace}id")]
    if (len(selected) != 1 or accepted_body is None or len(accepted_body) != 1
            or accepted_body[0].get("subtype") != work_id
            or bibliography_ids != ["source-npnf202"]):
        raise PipelineError(f"LIB028 {work_id} selected source body differs")
    selected[0].tail = None
    accepted_body[0].tail = None
    if (_node_sha(selected[0]) != row["selected_tei_node_sha256"]
            or _node_sha(accepted_body[0]) != row["selected_tei_node_sha256"]
            or b"sourced via CCEL.org" not in bound.split(b"</teiHeader>", 1)[0]
            or b'Electronic volume title source @n: npnf202' not in bound.split(b"</teiHeader>", 1)[0]
            or route["title"].encode("utf-8") not in bound):
        raise PipelineError(f"LIB028 {work_id} source text or visible credit differs")
    if errors := validate_file(_io_path(stage / work_path / master)):
        raise PipelineError(f"LIB028 {work_id} P5 errors: {errors[:2]}")
    projected = project_accepted_prose(_io_path(stage), acceptance_path=_io_path(accepted_path))
    errors = verify_accepted_prose(_io_path(stage), acceptance_path=_io_path(accepted_path),
                                   rows=projected["rows"], receipt=projected["receipt"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"LIB028 {work_id} native prose differs: {errors[:2]}")


def preflight(work_id: str, *, root_override: Path | None = None) -> tuple[dict, Path, Path, bool]:
    if work_id not in ROUTES:
        raise PipelineError(f"unsupported LIB028 selected work: {work_id}")
    stage = STAGE_ROOT / work_id
    receipt_path = stage / "stage-receipt.json"
    if not _io_path(receipt_path).is_file() or _sha(receipt_path) != RECEIPT_SHA[work_id]:
        raise PipelineError(f"LIB028 {work_id} frozen receipt differs")
    receipt = _json(receipt_path)
    if (receipt.get("contract") != CONTRACT or receipt.get("status") != "staged-only"
            or receipt.get("installation") != "not-performed"
            or receipt.get("rights") != "not-assessed"
            or Path(receipt.get("stage_root", "")).resolve(strict=True) != stage.resolve(strict=True)
            or Path(receipt.get("canonical_root", "")).resolve(strict=True) != ROOT.resolve(strict=True)):
        raise PipelineError(f"LIB028 {work_id} stage contract differs")
    fixture = root_override is not None
    root = root_override.resolve(strict=True) if fixture else ROOT.resolve(strict=True)
    if fixture:
        scratch = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
        if scratch not in root.parents or not _io_path(root / FIXTURE_MARKER).is_file():
            raise PipelineError("LIB028 override requires a marked review-area fixture")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("LIB028 install roots overlap")
    _dependencies(stage, work_id, receipt["dependencies"])
    _scope(root, stage, work_id, receipt["work"])
    return receipt, root, stage, fixture


def _copy_generation(source: Path, target: Path, expected: dict[str, str]) -> None:
    if _io_path(target).exists():
        raise PipelineError("LIB028 incoming generation already exists")
    _io_path(target).mkdir(parents=True)
    for relative, digest in expected.items():
        origin, destination = _io_path(source / relative), _io_path(target / relative)
        if not origin.is_file() or _sha(origin) != digest:
            raise PipelineError(f"LIB028 staged file changed: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    if _files(target) != expected:
        raise PipelineError("LIB028 incoming generation differs")


def install(work_id: str, *, root_override: Path | None = None,
            fail_at: Callable[[str], None] | None = None) -> dict:
    receipt, root, stage, fixture = preflight(work_id, root_override=root_override)
    row = receipt["work"]
    work_path = Path(row["work_path"])
    target, source = root / work_path, stage / work_path
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != row["before"] or _files(source) != row["after"]:
            raise PipelineError(f"LIB028 {work_id} work changed while acquiring lock")
        _dependencies(stage, work_id, receipt["dependencies"])
        operation = (root / "library/.sidecar-operations" /
                     f"n207-{uuid.uuid4().hex[:12]}")
        _io_path(operation).mkdir(parents=True, exist_ok=False)
        incoming, previous, failed_new = (operation / name for name in
                                          ("incoming", "previous", "failed-new"))
        journal = dict(contract="ocd-lib028-selected-work-swap-v1", work_id=work_id,
                       phase="created", before=row["before"], after=row["after"],
                       receipt=(stage / "stage-receipt.json").as_posix(), updated_at=_now())
        _write_json_durable(operation / "operation.json", journal)
        moved = live = False
        try:
            _copy_generation(source, incoming, row["after"])
            if _files(target) != row["before"]:
                raise PipelineError(f"LIB028 {work_id} work changed during incoming copy")
            journal.update(phase="prepared", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            if fail_at:
                fail_at("after-copy")
            _dependencies(stage, work_id, receipt["dependencies"])
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
                raise PipelineError(f"LIB028 {work_id} installed generation differs")
            if not fixture:
                acceptance = next(value for value in row["after"] if value.endswith("/acceptance.json"))
                validate_acceptance(_io_path(target / acceptance), root=_io_path(root))
                validate_state(_io_path(target / "state.json"), root=_io_path(root))
            if fail_at:
                fail_at("after-validation")
            journal.update(phase="complete", updated_at=_now())
            _write_json_durable(operation / "operation.json", journal)
            return dict(status="installed-and-validated", work_id=work_id,
                        operation=operation.as_posix(), before_count=len(row["before"]),
                        after_count=len(row["after"]), master_sha256=row["new_master_sha256"])
        except BaseException:
            try:
                if live:
                    if _files(target) != row["after"]:
                        raise PipelineError(f"LIB028 {work_id} live generation differs during rollback")
                    os.replace(_io_path(target), _io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != row["before"]:
                        raise PipelineError(f"LIB028 {work_id} prior generation differs during rollback")
                    os.replace(_io_path(previous), _io_path(target))
                    if _files(target) != row["before"]:
                        raise PipelineError(f"LIB028 {work_id} rollback restored wrong bytes")
                journal.update(phase="rolled-back" if moved else "failed-before-swap",
                               updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
            except BaseException as exc:
                journal.update(phase="recovery-required", rollback_error=str(exc),
                               updated_at=_now())
                _write_json_durable(operation / "operation.json", journal)
                raise PipelineError(f"LIB028 rollback requires recovery: {operation}") from exc
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True, choices=tuple(ROUTES))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        result = install(args.work_id)
    else:
        receipt, _, _, _ = preflight(args.work_id)
        result = dict(status="ready-for-review", work_id=args.work_id,
                      receipt_sha256=RECEIPT_SHA[args.work_id],
                      before_count=len(receipt["work"]["before"]),
                      after_count=len(receipt["work"]["after"]),
                      master_sha256=receipt["work"]["new_master_sha256"])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
