"""Install only the authorized, pinned source-native image-target repair."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from build.tools.stage_nancy_prince_pg63579 import ROOT, WORK, EDITION, WORK_ID
from build.tools.prepare_nancy_prince_pg63579 import canonical
from ocd_kernel.library._common import io_path
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import (
    _files, _commit_generation, _validate_promoted_tree,
    _replacement_changes_are_scoped, _validate_state_transition,
    _validate_acceptance_for_work,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promoted",type=Path,required=True)
    parser.add_argument("--receipt-sha256",required=True)
    parser.add_argument("--evidence",type=Path,required=True)
    args = parser.parse_args()
    promoted = args.promoted.absolute()
    if promoted.parent.resolve(strict=True) != Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True) or not promoted.name.startswith("nancy-prince-pg63579-promoted-repair-"):
        raise ValueError("exact work-owned repair stage required")
    raw = (promoted/"stage-receipt.json").read_bytes()
    if sha256(raw).hexdigest() != args.receipt_sha256:
        raise ValueError("repair stage receipt changed")
    receipt = json.loads(raw)
    if receipt["status"] != "pass" or receipt["rows"] != 4 or receipt["repair"]["superseded_master_sha256"] != "287bc87f71f3e6d8378eaa0b0e3af50359d2b677c60c5eb2001702f86356402e":
        raise ValueError("repair evidence contract differs")
    target,source = ROOT/WORK,promoted/WORK
    args.evidence.mkdir(parents=True,exist_ok=False)
    (args.evidence/"staged-repair-receipt.json").write_bytes(raw)

    def preflight() -> None:
        if _files(target) != receipt["before"] or _files(source) != receipt["after"]:
            raise ValueError("locked canonical or incoming generation differs from complete receipt")
        old_records = _validate_promoted_tree(ROOT,target,work_id=WORK_ID)
        new_records = _validate_promoted_tree(promoted,source,work_id=WORK_ID)
        if len(old_records) != 1 or len(new_records) != 1 or old_records[0]["identity"] != new_records[0]["identity"]:
            raise ValueError("repair changes accepted identities")
        _replacement_changes_are_scoped(receipt["before"],receipt["after"])
        for relative,digest in receipt["before"].items():
            if Path(relative).name not in {"master.tei.xml","acceptance.json","state.json"} and receipt["after"].get(relative) != digest:
                raise ValueError("repair changes an existing source, metadata, or evidence file: " + relative)
        additions = set(receipt["after"])-set(receipt["before"])
        if any(not relative.startswith("acceptance/pg63579-complete-html-v2/") for relative in additions):
            raise ValueError("repair adds files outside its acceptance evidence")
        _validate_state_transition(target,source,existed=True,replacement=True,
                                  accepted_evidence_by_edition={new_records[0]["identity"]["edition_id"]:((EDITION/"master.tei.xml").as_posix(),(EDITION/"acceptance.json").as_posix())})

    def checkpoint(phase: str) -> None:
        if phase == "after-validated":
            _validate_acceptance_for_work(ROOT/EDITION/"acceptance.json",root=ROOT,work_id=WORK_ID)
            validate_state(ROOT/WORK/"state.json",root=ROOT)
            if _files(target) != receipt["after"]:
                raise ValueError("installed generation differs from the complete pinned after-set")
            if sha256(io_path(ROOT/EDITION/"master.tei.xml").read_bytes()).hexdigest() != receipt["master_sha256"]:
                raise ValueError("canonical repaired master hash differs")

    with ExitStack() as locks:
        for directory in sorted((target,source),key=lambda p:p.as_posix()):
            locks.enter_context(acquire_jsonl_lock(directory,acquire_timeout=30.0))
        preflight()
        result = _commit_generation(ROOT,target,source,work_id=WORK_ID,before=receipt["before"],after=receipt["after"],existed=True,replacement=True,
                                    operation_kind="nancy-prince-source-native-image-target-repair",result_status="replaced-and-validated",accepted_editions=1,fail_at=checkpoint)
    validate_acceptance(ROOT/EDITION/"acceptance.json",root=ROOT)
    (args.evidence/"installation.json").write_bytes(canonical(result))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
