"""Preflight the frozen A23804 generation; atomically install only with --apply."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_whole_duty_prayer_acceptance import (
    ACQUISITION, EDITION, EDITION_ID, EVIDENCE, FORM_ID, MANIFEST,
    MANIFEST_SHA, ROOT, SOURCE, SOURCE_SHA256, WORK, WORK_ID,
)
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.projection.categories.prayers import project_accepted_prayers, verify_accepted_prayers
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import (
    _commit_generation, _files, _io_path, _validate_promoted_tree,
    _validate_state_transition,
)

STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/whole-duty-of-prayer-a23804-acceptance-stage-20261003-v2")
RECEIPT_SHA = "dd4959c862f4982bfd629bf703f927ac4a99444e57b012838482fc57ff0c3380"
MASTER = EDITION / "master.tei.xml"
ACCEPTANCE = EDITION / "acceptance.json"


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def preflight(*, _held_stage_lock: Path | None = None) -> dict:
    root, stage = ROOT.resolve(strict=True), STAGE.resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("A23804 installation roots overlap")
    receipt_bytes = _io_path(stage / "a23804-stage-receipt.json").read_bytes()
    if sha256(receipt_bytes).hexdigest() != RECEIPT_SHA:
        raise PipelineError("A23804 frozen stage receipt differs")
    record = json.loads(receipt_bytes)
    if (record.get("contract") != "ocd-a23804-electronic-stage-v1"
            or record.get("status") != "staged-only" or record.get("work_id") != WORK_ID
            or record.get("installation") != "not-performed" or record.get("rights") != "not-assessed"
            or Path(record["stage_root"]).resolve(strict=True) != stage
            or record.get("projection_rows") != 6):
        raise PipelineError("A23804 frozen stage scope differs")
    before, after = _files(root / WORK), _files(stage / WORK)
    if (before != record["before"] or after != record["after"]
            or len(before) != 15 or len(after) != 35 or not set(before).issubset(after)):
        raise PipelineError("A23804 complete generation differs")
    allowed = {"work.json", "state.json", MASTER.relative_to(WORK).as_posix(),
               ACCEPTANCE.relative_to(WORK).as_posix()}
    prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for path in set(before) | set(after):
        if before.get(path) == after.get(path) or path in allowed:
            continue
        if path.startswith(prefix) and path not in before and path in after:
            continue
        raise PipelineError(f"A23804 unrelated authority delta: {path}")
    old_work, new_work = load_work(root / WORK / "work.json"), load_work(stage / WORK / "work.json")
    expected = json.loads(json.dumps(old_work))
    if len(expected["textual_forms"]) != 1 or len(expected["textual_forms"][0]["editions"]) != 1:
        raise PipelineError("A23804 work cardinality differs")
    form = expected["textual_forms"][0]
    edition = form["editions"][0]
    if (form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or form.get("language") is not None or edition.get("language") is not None
            or edition.get("category") is not None):
        raise PipelineError("A23804 metadata preimage differs")
    form["language"] = edition["language"] = "en"
    edition["category"] = "prayers"
    if new_work != expected:
        raise PipelineError("A23804 metadata exceeds exact en/en/prayers prerequisites")
    validate_identity_update(old_work, new_work)
    if before[ACQUISITION.relative_to(WORK).as_posix()] != after[ACQUISITION.relative_to(WORK).as_posix()]:
        raise PipelineError("A23804 acquisition changed")
    if _sha(root / SOURCE) != SOURCE_SHA256 or _sha(root / MANIFEST) != MANIFEST_SHA:
        raise PipelineError("A23804 retained source or manifest differs")
    SourceManifest.load(root / MANIFEST, repository_root=root).verify()
    # Every copied dependency must still equal canonical authority. Work-local
    # generation differences are checked separately above.
    for path, digest in _files(stage).items():
        if path == "a23804-stage-receipt.json" or path.startswith(WORK.as_posix() + "/"):
            continue
        relative = Path(path)
        # acquire_jsonl_lock creates this one operational sibling outside the
        # work generation. Only the path returned by our held context is exempt.
        if _held_stage_lock is not None and stage / relative == _held_stage_lock:
            if _held_stage_lock != (stage / WORK).with_name(WORK.name + ".lock"):
                raise PipelineError("A23804 held stage lock path differs")
            continue
        if relative.is_absolute() or ".." in relative.parts or _sha(root / relative) != digest:
            raise PipelineError(f"A23804 staged dependency differs: {path}")
    if (after[MASTER.relative_to(WORK).as_posix()] != record["master_sha256"]
            or after[ACCEPTANCE.relative_to(WORK).as_posix()] != record["acceptance_sha256"]
            or after[MASTER.relative_to(WORK).as_posix()] != after[(EVIDENCE / "candidate.tei.xml").relative_to(WORK).as_posix()]):
        raise PipelineError("A23804 accepted candidate/master binding differs")
    accepted = _validate_promoted_tree(stage, stage / WORK, work_id=WORK_ID)
    if (len(accepted) != 1 or accepted[0]["identity"]["edition_id"] != EDITION_ID
            or accepted[0]["decision"]["human_decision"]["status"] != "not-recorded"
            or accepted[0]["decision"]["agent_assessment"]["status"] != "accepted"):
        raise PipelineError("A23804 electronic-witness acceptance scope differs")
    _validate_state_transition(root / WORK, stage / WORK, existed=True, replacement=False,
        accepted_evidence_by_edition={EDITION_ID: (MASTER.as_posix(), ACCEPTANCE.as_posix())})
    projected = project_accepted_prayers(stage, acceptance_path=stage / ACCEPTANCE)
    if (len(projected["rows"]) != 6
            or verify_accepted_prayers(stage, acceptance_path=stage / ACCEPTANCE,
                rows=projected["rows"], receipt=projected["receipt"])
            or projected != json.loads(_io_path(stage / EVIDENCE / "actual-master-projection.json").read_bytes())):
        raise PipelineError("A23804 exact staged native projection differs")
    return record


def install() -> dict:
    record = preflight()
    target, source = ROOT / WORK, STAGE / WORK
    with ExitStack() as locks:
        stage_lock = None
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            lock_path = locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
            if path == source:
                stage_lock = lock_path
        # Revalidate dependencies and complete frozen generations under the locks.
        if stage_lock is None or preflight(_held_stage_lock=stage_lock) != record:
            raise PipelineError("A23804 generation changed while acquiring locks")
        return _commit_generation(ROOT.resolve(strict=True), target.resolve(strict=True), source.resolve(strict=True),
            work_id=WORK_ID, before=record["before"], after=record["after"], existed=True,
            replacement=False, operation_kind="initial-install", result_status="installed-and-validated",
            accepted_editions=1, fail_at=None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install() if args.apply else {"status": "ready-for-review", "before_files": len(preflight()["before"]), "after_files": 35}
    print(json.dumps(result, sort_keys=True))
