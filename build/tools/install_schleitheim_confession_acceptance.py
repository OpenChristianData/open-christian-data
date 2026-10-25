"""Preflight or guardedly install the frozen Schleitheim electronic witness.

The default command is read-only. ``--apply`` swaps only this work generation
under the shared work lock with journaled rollback; it does not write public data.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from build.tei.schleitheim_confession_oracle import _oracle
from build.tools.stage_schleitheim_confession_acceptance import (
    ACQUISITION, CANDIDATE, CONTRACT, EDITION, EVIDENCE, MANIFEST, PACKAGE_SHA,
    ROOT, SOURCE, SOURCE_BYTES, SOURCE_SHA, WORK, WORK_ID,
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


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/schleitheim-acceptance-20260928-v2")
RECEIPT = STAGE / "stage-receipt.json"
RECEIPT_SHA = "61e06ec42cc5c004e24832d59e40bf185fcc9a72a5acbd643f87e7396a1b599f"
SOURCE_CREDIT_SHA = "14106690813432f965f46ec7b3e2f3b350dde311f1ec9e700484bb7e28b096d9"
FIXTURE_MARKER = ".ocd-schleitheim-install-fixture"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"Schleitheim JSON object required: {path}")
    return value


def _dependencies(stage: Path, before_work: dict) -> dict[str, str]:
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    manifest.verify()
    old_work = _json(ROOT / WORK / "work.json")
    old_state = _json(ROOT / WORK / "state.json")
    paths = {MANIFEST, SOURCE, Path("raw/anabaptists.org/schleitheim-confession-1527.manifest.json")}
    paths.update(Path(item["path"]) for item in manifest.record["authorities"])
    for reference in set(old_work.get("evidence", [])) | {
        value for target in old_state["targets"] for value in target["evidence"]
    }:
        relative = Path(reference.partition("#")[0])
        if relative.is_absolute() or ".." in relative.parts:
            raise PipelineError(f"unsafe inherited Schleitheim evidence: {reference}")
        paths.add(relative)
    paths.discard(ACQUISITION)
    expected = {path.as_posix(): _sha(ROOT / path) for path in paths}
    files = _files(stage)
    prefix = WORK.as_posix() + "/"
    other = {name: digest for name, digest in files.items()
             if not name.startswith(prefix) and name not in {
                 RECEIPT.name, WORK.as_posix() + ".lock"}}
    if other != expected:
        raise PipelineError("Schleitheim staged source/evidence dependency set differs")
    if len(before_work) != 3 or _sha(ROOT / SOURCE) != SOURCE_SHA or len(_io_path(ROOT / SOURCE).read_bytes()) != SOURCE_BYTES:
        raise PipelineError("Schleitheim current source or work preimage differs")
    return expected


def preflight(*, root_override: Path | None = None) -> dict:
    if not _io_path(RECEIPT).is_file() or _sha(RECEIPT) != RECEIPT_SHA:
        raise PipelineError("Schleitheim frozen receipt differs")
    receipt = _json(RECEIPT)
    stage = STAGE.resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override else ROOT.resolve(strict=True)
    fixture = root_override is not None
    if fixture and (not _io_path(root / FIXTURE_MARKER).is_file()
                    or _io_path(root / FIXTURE_MARKER).read_bytes() != b"fixture-only\n"
                    or root == ROOT.resolve(strict=True)):
        raise PipelineError("Schleitheim override requires a marked isolated fixture")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Schleitheim install roots overlap")
    if (receipt.get("contract") != CONTRACT or receipt.get("status") != "staged-only"
            or receipt.get("installation") != "not-performed" or receipt.get("work_id") != WORK_ID
            or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("canonical_root") != ROOT.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA
            or receipt.get("candidate_package_sha256") != PACKAGE_SHA
            or receipt.get("projection_rows") != 9
            or receipt.get("independent_verifier_errors") != []
            or receipt.get("rights") != "unresolved-translation-rights"
            or receipt.get("human_review") != "not-recorded"):
        raise PipelineError("Schleitheim frozen receipt claim or identity differs")
    before = _files(root / WORK)
    after = _files(stage / WORK)
    if before != receipt["before"] or after != receipt["after"]:
        raise PipelineError("Schleitheim work preimage or staged generation differs")
    if (set(before) != {"work.json", "state.json", ACQUISITION.relative_to(WORK).as_posix()}
            or len(after) != 22 or after.get("SOURCE_CREDIT.md") != SOURCE_CREDIT_SHA):
        raise PipelineError("Schleitheim work scope or visible source credit differs")
    allowed = {"work.json", "state.json", "SOURCE_CREDIT.md",
               ACQUISITION.relative_to(WORK).as_posix(),
               (EDITION / "master.tei.xml").relative_to(WORK).as_posix(),
               (EDITION / "acceptance.json").relative_to(WORK).as_posix()}
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for name in set(before) | set(after):
        if before.get(name) == after.get(name):
            continue
        if name not in allowed and not (name.startswith(evidence_prefix) and name not in before):
            raise PipelineError(f"Schleitheim unrelated work path changed: {name}")
    old_work = _json(root / WORK / "work.json")
    new_work = _json(stage / WORK / "work.json")
    expected_work = json.loads(json.dumps(old_work))
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if new_work != expected_work:
        raise PipelineError("Schleitheim staged identity exceeds prose category change")
    old_state = _json(root / WORK / "state.json")
    new_state = _json(stage / WORK / "state.json")
    for old, new in zip(old_state["targets"], new_state["targets"], strict=True):
        if old["target_id"] != new["target_id"] or old["target_type"] != new["target_type"]:
            raise PipelineError("Schleitheim state target identity differs")
        if old["target_type"] == "acquisition":
            if old != new:
                raise PipelineError("Schleitheim acquisition state changed")
        elif (old["stage"] != "acquired" or new["stage"] != "accepted"
              or new["evidence"] != old["evidence"] + [
                  (EDITION / "master.tei.xml").as_posix(),
                  (EDITION / "acceptance.json").as_posix()]):
            raise PipelineError("Schleitheim edition state transition differs")
    dependencies = _dependencies(stage, before)
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    package = CandidatePackage.load(stage / EVIDENCE / "inputs/package")
    report = validate(manifest, package, _oracle)
    if (report.status != "pass" or report.findings or package.sha256 != PACKAGE_SHA
            or package.sha256 != CandidatePackage.load(CANDIDATE).sha256
            or report.sha256 != receipt["oracle_report_sha256"]
            or manifest.sha256 != receipt["source_manifest_sha256"]):
        raise PipelineError("Schleitheim current source/candidate/oracle binding differs")
    original = package.member_bytes("content.tei.xml")
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
            or _sha(stage / EDITION / "master.tei.xml") != receipt["master_sha256"]
            or _sha(stage / EDITION / "acceptance.json") != receipt["acceptance_sha256"]):
        raise PipelineError("Schleitheim accepted master or header binding differs")
    acceptance = stage / EDITION / "acceptance.json"
    record = validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / WORK / "state.json"), root=_io_path(stage))
    if (record["promotion"]["status"] != "promoted"
            or record["identity"]["work_id"] != WORK_ID
            or record["decision"]["human_decision"]["status"] != "not-recorded"):
        raise PipelineError("Schleitheim accepted electronic-witness authority differs")
    projected = project_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance), category="prose")
    errors = verify_accepted_document(_io_path(stage), acceptance_path=_io_path(acceptance),
                                      rows=projected["rows"], receipt=projected["receipt"], category="prose")
    if errors or len(projected["rows"]) != 9:
        raise PipelineError(f"Schleitheim actual-master native projection differs: {errors[:3]}")
    return dict(status="ready-for-review", work_id=WORK_ID, receipt_sha256=RECEIPT_SHA,
                before_files=len(before), after_files=len(after), dependencies=len(dependencies),
                native_rows=9, rights="unresolved-translation-rights", installation="not-performed")


def install(*, root_override: Path | None = None,
            fail_at: Callable[[str], None] | None = None) -> dict:
    root = root_override.resolve(strict=True) if root_override else ROOT.resolve(strict=True)
    stage = STAGE.resolve(strict=True)
    target, source = root / WORK, stage / WORK
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(root_override=root_override)
        receipt = _json(RECEIPT)

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("Schleitheim installed work generation differs")
                acceptance = target / (EDITION / "acceptance.json").relative_to(WORK)
                validate_acceptance(_io_path(acceptance), root=_io_path(root))
                validate_state(_io_path(target / "state.json"), root=_io_path(root))
                projected = project_accepted_document(_io_path(root), acceptance_path=_io_path(acceptance), category="prose")
                errors = verify_accepted_document(_io_path(root), acceptance_path=_io_path(acceptance),
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != 9:
                    raise PipelineError(f"Schleitheim installed native rows differ: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        result = _commit_generation(
            root, target, source, work_id=WORK_ID,
            before=receipt["before"], after=receipt["after"],
            existed=True, replacement=False,
            operation_kind="schleitheim-current-html-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )
    return result | {"projection_rows": 9}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    ready = preflight()
    if args.apply:
        ready["installation"] = install()
    print(json.dumps(ready, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
