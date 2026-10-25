"""Read-only preflight or serial guarded install of three LIB-089 HTML works.

By default, preflight all three frozen stages. ``--apply`` requires one exact
``--work`` and swaps only that work under a journaled lock. No public data is
written by this command.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from build.tei.lib089_westminster_standards_oracle import _oracle
from build.tools.stage_lib089_three_acceptances import (
    CANDIDATE_ROOT, COHORT, CONTRACT, ROOT, WORK_IDS, _paths,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document, verify_accepted_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


INDEX = COHORT / "freeze-index.json"
INDEX_SHA = "0b2636e5ce8ec93f7573cc4de84caf61739ed5f5e50d90671f948faa827d35d6"
FIXTURE_MARKER = ".ocd-lib089-three-install-fixture"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"LIB-089 JSON object required: {path}")
    return value


def _index() -> dict[str, dict]:
    if not _io_path(INDEX).is_file() or _sha(INDEX) != INDEX_SHA:
        raise PipelineError("LIB-089 frozen cohort index differs")
    index = _json(INDEX)
    if (index.get("contract") != "ocd-lib089-three-current-html-freeze-index-v1"
            or index.get("status") != "staged-only"
            or index.get("installation") != "not-performed"
            or index.get("canonical_root") != ROOT.as_posix()
            or index.get("cohort_root") != COHORT.as_posix()
            or [row["work_id"] for row in index["works"]] != list(WORK_IDS)):
        raise PipelineError("LIB-089 frozen cohort identity differs")
    return {row["work_id"]: row for row in index["works"]}


def _dependencies(work_id: str, stage: Path, manifest: SourceManifest,
                  work_path: Path, acquisition_path: Path) -> int:
    old_work = _json(ROOT / work_path / "work.json")
    old_state = _json(ROOT / work_path / "state.json")
    _, _, _, manifest_path, _ = _paths(work_id)
    sources = [item for item in manifest.record["authorities"] if item["role"] == "primary-source"]
    if len(sources) != 1:
        raise PipelineError(f"LIB-089 {work_id} source member count differs")
    paths = {manifest_path, Path(sources[0]["path"])}
    paths.update(Path(item["path"]) for item in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        value for target in old_state["targets"] for value in target["evidence"]
    }:
        path = Path(reference.partition("#")[0])
        if path.is_absolute() or ".." in path.parts:
            raise PipelineError(f"unsafe LIB-089 {work_id} inherited evidence: {reference}")
        paths.add(path)
    paths.discard(acquisition_path)
    expected = {path.as_posix(): _sha(ROOT / path) for path in paths}
    prefix = work_path.as_posix() + "/"
    other = {name: digest for name, digest in _files(stage).items()
             if not name.startswith(prefix) and name not in {
                 "stage-receipt.json", work_path.as_posix() + ".lock"}}
    if other != expected:
        raise PipelineError(f"LIB-089 {work_id} staged source/evidence dependency set differs")
    return len(expected)


def preflight(work_id: str, *, root_override: Path | None = None) -> dict:
    if work_id not in WORK_IDS:
        raise PipelineError(f"LIB-089 work outside frozen cohort: {work_id}")
    pin = _index()[work_id]
    stage = (COHORT / work_id).resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override else ROOT.resolve(strict=True)
    if root_override and (root == ROOT.resolve(strict=True)
                          or not _io_path(root / FIXTURE_MARKER).is_file()
                          or _io_path(root / FIXTURE_MARKER).read_bytes() != b"fixture-only\n"):
        raise PipelineError("LIB-089 root override requires an isolated marked fixture")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("LIB-089 install roots overlap")
    receipt_path = stage / "stage-receipt.json"
    if not _io_path(receipt_path).is_file() or _sha(receipt_path) != pin["receipt_sha256"]:
        raise PipelineError(f"LIB-089 {work_id} frozen work receipt differs")
    receipt = _json(receipt_path)
    work_path, edition_path, acquisition_path, manifest_path, evidence = _paths(work_id)
    if (receipt.get("contract") != CONTRACT or receipt.get("status") != "staged-only"
            or receipt.get("installation") != "not-performed"
            or receipt.get("work_id") != work_id
            or receipt.get("canonical_root") != ROOT.as_posix()
            or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != pin["source_sha256"]
            or receipt.get("master_sha256") != pin["master_sha256"]
            or receipt.get("acceptance_sha256") != pin["acceptance_sha256"]
            or receipt.get("projection_rows") != pin["projection_rows"]
            or receipt.get("independent_verifier_errors") != []
            or receipt.get("rights") != "unresolved-provider-transcription-rights"
            or receipt.get("human_review") != "not-recorded"):
        raise PipelineError(f"LIB-089 {work_id} frozen receipt claim differs")
    before = _files(root / work_path)
    after = _files(stage / work_path)
    if before != receipt["before"] or after != receipt["after"]:
        raise PipelineError(f"LIB-089 {work_id} complete work preimage/stage differs")
    if (set(before) != {"work.json", "state.json", acquisition_path.relative_to(work_path).as_posix()}
            or len(after) != 22 or "SOURCE_CREDIT.md" not in after):
        raise PipelineError(f"LIB-089 {work_id} work file scope differs")
    allowed = {"work.json", "state.json", "SOURCE_CREDIT.md",
               acquisition_path.relative_to(work_path).as_posix(),
               (edition_path / "master.tei.xml").relative_to(work_path).as_posix(),
               (edition_path / "acceptance.json").relative_to(work_path).as_posix()}
    prefix = evidence.relative_to(work_path).as_posix() + "/"
    for name in set(before) | set(after):
        if before.get(name) == after.get(name):
            continue
        if name not in allowed and not (name.startswith(prefix) and name not in before):
            raise PipelineError(f"LIB-089 {work_id} unrelated work path changed: {name}")
    old_work = _json(root / work_path / "work.json")
    new_work = _json(stage / work_path / "work.json")
    expected_work = json.loads(json.dumps(old_work))
    expected_form = expected_work["textual_forms"][0]
    expected_form["language"] = "en"
    expected_edition = expected_form["editions"][0]
    expected_edition["language"] = "en"
    expected_edition["category"] = "prose"
    if new_work != expected_work:
        raise PipelineError(f"LIB-089 {work_id} staged identity exceeds language/prose additions")
    old_state = _json(root / work_path / "state.json")
    new_state = _json(stage / work_path / "state.json")
    for old, new in zip(old_state["targets"], new_state["targets"], strict=True):
        if old["target_id"] != new["target_id"] or old["target_type"] != new["target_type"]:
            raise PipelineError(f"LIB-089 {work_id} state target identity differs")
        if old["target_type"] == "acquisition":
            if old != new:
                raise PipelineError(f"LIB-089 {work_id} acquisition state changed")
        elif (old["stage"] != "acquired" or new["stage"] != "accepted"
              or new["evidence"] != old["evidence"] + [
                  (edition_path / "master.tei.xml").as_posix(),
                  (edition_path / "acceptance.json").as_posix()]):
            raise PipelineError(f"LIB-089 {work_id} edition state transition differs")
    manifest = SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
    manifest.verify()
    dependencies = _dependencies(work_id, stage, manifest, work_path, acquisition_path)
    source_path = Path(receipt["source_path"])
    if (_sha(ROOT / source_path) != receipt["source_sha256"]
            or len(_io_path(ROOT / source_path).read_bytes()) != receipt["source_bytes"]
            or manifest.sha256 != receipt["source_manifest_sha256"]):
        raise PipelineError(f"LIB-089 {work_id} live source/manifest differs")
    package = CandidatePackage.load(stage / evidence / "inputs/package")
    report = validate(manifest, package, _oracle)
    reference = CandidatePackage.load(CANDIDATE_ROOT / f"lib089-{work_id}-current-20260928-v1/package")
    if (report.status != "pass" or report.findings
            or package.sha256 != receipt["candidate_package_sha256"]
            or package.sha256 != reference.sha256
            or report.sha256 != receipt["oracle_report_sha256"]):
        raise PipelineError(f"LIB-089 {work_id} source candidate/oracle differs")
    original = package.member_bytes("content.tei.xml")
    master = _io_path(stage / edition_path / "master.tei.xml").read_bytes()
    if (original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
            or _sha(stage / edition_path / "master.tei.xml") != receipt["master_sha256"]
            or _sha(stage / edition_path / "acceptance.json") != receipt["acceptance_sha256"]):
        raise PipelineError(f"LIB-089 {work_id} accepted master/header differs")
    acceptance = stage / edition_path / "acceptance.json"
    record = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / work_path / "state.json"), root=_io_path(stage))
    if (record["promotion"]["status"] != "promoted"
            or record["identity"]["work_id"] != work_id
            or record["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError(f"LIB-089 {work_id} acceptance authority differs")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != pin["projection_rows"]:
        raise PipelineError(f"LIB-089 {work_id} native projection differs: {errors[:3]}")
    return dict(status="ready-for-review", work_id=work_id,
                receipt_sha256=pin["receipt_sha256"], before_files=len(before),
                after_files=len(after), dependencies=dependencies,
                native_rows=len(projected["rows"]), installation="not-performed")


def install(work_id: str, *, root_override: Path | None = None,
            fail_at: Callable[[str], None] | None = None) -> dict:
    if work_id not in WORK_IDS:
        raise PipelineError(f"LIB-089 work outside cohort: {work_id}")
    root = root_override.resolve(strict=True) if root_override else ROOT.resolve(strict=True)
    stage = (COHORT / work_id).resolve(strict=True)
    work_path, edition_path, _, _, _ = _paths(work_id)
    target, source = root / work_path, stage / work_path
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(work_id, root_override=root_override)
        receipt = _json(stage / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError(f"LIB-089 {work_id} installed generation differs")
                acceptance = target / (edition_path / "acceptance.json").relative_to(work_path)
                validate_acceptance(_io_path(acceptance), root=_io_path(root))
                validate_state(_io_path(target / "state.json"), root=_io_path(root))
                projected = project_accepted_document(_io_path(root), acceptance_path=_io_path(acceptance), category="prose")
                errors = verify_accepted_document(_io_path(root), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != receipt["projection_rows"]:
                    raise PipelineError(f"LIB-089 {work_id} installed native rows differ: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        result = _commit_generation(
            root, target, source, work_id=work_id,
            before=receipt["before"], after=receipt["after"],
            existed=True, replacement=False,
            operation_kind="lib089-current-html-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )
    return result | {"projection_rows": receipt["projection_rows"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", choices=WORK_IDS)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and args.work is None:
        parser.error("--apply requires one --work for serial installation")
    selected = (args.work,) if args.work else WORK_IDS
    results = [preflight(work_id) for work_id in selected]
    if args.apply:
        results[0]["installation"] = install(args.work)
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
