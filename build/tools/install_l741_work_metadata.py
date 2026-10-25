"""Guard one source-backed L741 category/language sidecar update before acceptance."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path, _resolve_work_paths


ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / ".tmp_audit/m"
WORK = Path("library/works/evangelische-gezangen-1806")
EDITION = WORK / "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic"
HANDOFF = STAGE / "l741-metadata-handoff.json"
INSTALL_RESULT = STAGE / "l741-metadata-install-result.json"
BEFORE = {
    "work.json": "a2cf66e3e7c5c7916669fd6c098f21d448a63029de311f55ff580b604d2d8e13",
    "state.json": "6b27f9758a52831cfb4b44d349f9fd6b2c6ab991f4e1571e92ddb06a1c109c32",
    "forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic/acquisitions/evangelische-gezangen-1806-dbnl-acquired.json": "b694e97b4560799b8e8027e5d53ed7dee9341e01319f20ac5f3a72f90a634e29",
}
AFTER_WORK_SHA256 = "0515ccc32f4c5b7aa8c45542057ad92080162daa716bb4f9bc8d0e2941d878ee"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _expected_sidecar() -> dict:
    original = json.loads(_io_path(ROOT / WORK / "work.json").read_text(encoding="utf-8"))
    form = original["textual_forms"][0]
    if (form["textual_form_id"] != "evangelische-gezangen-1806-dbnl-retained"
            or form["editions"][0]["edition_id"] != "evangelische-gezangen-1806-dbnl-electronic"
            or "category" in form or "language" in form):
        raise PipelineError("L741 metadata preimage structure differs")
    form["category"] = "hymns"
    form["language"] = "nl"
    return original


def stage() -> dict[str, object]:
    if STAGE.exists() or _files(ROOT / WORK) != BEFORE:
        raise PipelineError("L741 metadata stage exists or live preimage differs")
    if (ROOT / EDITION / "master.tei.xml").exists() or (ROOT / EDITION / "acceptance.json").exists():
        raise PipelineError("L741 acceptance must follow the metadata update")
    revised = _expected_sidecar()
    STAGE.mkdir(parents=True)
    shutil.copytree(_io_path(ROOT / WORK), _io_path(STAGE / WORK))
    staged_work = STAGE / WORK / "work.json"
    _io_path(staged_work).write_text(
        json.dumps(revised, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    load_work(staged_work)
    after = _files(STAGE / WORK)
    if after != (BEFORE | {"work.json": AFTER_WORK_SHA256}):
        raise PipelineError("L741 metadata stage changed more than the two declared fields")
    handoff = {"contract": "ocd-l741-metadata-update-v1", "status": "ready-to-install",
               "work_id": "evangelische-gezangen-1806", "before": BEFORE, "after": after,
               "changed_fields": ["textual_forms[0].category", "textual_forms[0].language"],
               "changed_files": ["work.json"], "additions": [], "removals": [],
               "canonical_install": "not-performed"}
    HANDOFF.write_text(json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8", newline="\n")
    return {"handoff": str(HANDOFF), "handoff_sha256": _sha(HANDOFF),
            "before_work_sha256": BEFORE["work.json"], "after_work_sha256": after["work.json"]}


def preflight(expected_sha256: str) -> dict[str, object]:
    _resolve_work_paths(ROOT, STAGE, "evangelische-gezangen-1806")
    if _sha(HANDOFF) != expected_sha256 or _files(ROOT / WORK) != BEFORE:
        raise PipelineError("L741 metadata handoff or live preimage differs")
    handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))
    if (handoff.get("contract") != "ocd-l741-metadata-update-v1"
            or handoff.get("status") != "ready-to-install"
            or handoff.get("canonical_install") != "not-performed"
            or handoff.get("before") != BEFORE
            or handoff.get("after") != BEFORE | {"work.json": AFTER_WORK_SHA256}
            or handoff.get("changed_fields") != ["textual_forms[0].category", "textual_forms[0].language"]
            or handoff.get("changed_files") != ["work.json"]
            or handoff.get("additions") != [] or handoff.get("removals") != []):
        raise PipelineError("L741 metadata handoff claims differ")
    if _files(STAGE / WORK) != handoff["after"]:
        raise PipelineError("L741 staged metadata bytes differ")
    if json.loads(_io_path(STAGE / WORK / "work.json").read_text(encoding="utf-8")) != _expected_sidecar():
        raise PipelineError("L741 metadata changed beyond category and language")
    if (ROOT / EDITION / "master.tei.xml").exists() or (ROOT / EDITION / "acceptance.json").exists():
        raise PipelineError("L741 canonical acceptance already exists")
    load_work(STAGE / WORK / "work.json")
    return {"status": "ready-to-install", "handoff_sha256": expected_sha256,
            "before_work_sha256": BEFORE["work.json"], "after_work_sha256": AFTER_WORK_SHA256}


def apply(expected_sha256: str) -> dict[str, object]:
    ready = preflight(expected_sha256)
    if INSTALL_RESULT.exists():
        raise PipelineError("L741 metadata install result already exists")
    _root, _stage, target, source = _resolve_work_paths(ROOT, STAGE, "evangelische-gezangen-1806")
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(expected_sha256)

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                load_work(ROOT / WORK / "work.json")
                validate_state(ROOT / WORK / "state.json", root=ROOT)
                if _files(ROOT / WORK) != BEFORE | {"work.json": AFTER_WORK_SHA256}:
                    raise PipelineError("L741 installed metadata generation differs")

        ready["installation"] = _commit_generation(
            ROOT, target, source, work_id="evangelische-gezangen-1806",
            before=BEFORE, after=BEFORE | {"work.json": AFTER_WORK_SHA256},
            existed=True, replacement=False, operation_kind="l741-category-language-metadata",
            result_status="installed-and-validated", accepted_editions=0, fail_at=checkpoint,
        )
    operation = Path(ready["installation"]["operation"]).resolve(strict=True)
    journal = operation / "operation.json"
    journal_record = json.loads(journal.read_text(encoding="utf-8"))
    if (journal_record.get("phase") != "complete"
            or journal_record.get("result_status") != "installed-and-validated"
            or journal_record.get("work_id") != "evangelische-gezangen-1806"
            or journal_record.get("operation_kind") != "l741-category-language-metadata"
            or journal_record.get("before") != BEFORE
            or journal_record.get("after") != BEFORE | {"work.json": AFTER_WORK_SHA256}):
        raise PipelineError("L741 metadata operation journal is incomplete")
    result = {"contract": "ocd-l741-metadata-install-result-v1", "status": "installed-and-validated",
              "work_id": "evangelische-gezangen-1806", "handoff_sha256": expected_sha256,
              "before": BEFORE, "after": BEFORE | {"work.json": AFTER_WORK_SHA256},
              "operation_journal": str(journal), "operation_journal_sha256": _sha(journal)}
    INSTALL_RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8", newline="\n")
    ready["install_result"] = str(INSTALL_RESULT)
    ready["install_result_sha256"] = _sha(INSTALL_RESULT)
    return ready


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "preflight", "apply"))
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.action == "stage":
        result = stage()
    elif args.expected_sha256 is None:
        parser.error("preflight and apply require --expected-sha256")
    elif args.action == "preflight":
        result = preflight(args.expected_sha256)
    else:
        result = apply(args.expected_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
