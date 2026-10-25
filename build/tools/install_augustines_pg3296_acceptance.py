"""Read-only preflight or guarded work-local install of exact PG3296 Confessions."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from build.tei.augustines_confessions_oracle import _oracle
from build.tools.stage_augustines_pg3296_acceptance import (
    ACQUISITION, CANDIDATE, CATALOG, EDITION, EDITION_ID, EVIDENCE, FORM_ID,
    LIBRARY, MANIFEST, ROOT, SOURCE, SOURCE_SHA, WORK, WORK_ID,
)
from build.tools.reconstruct_candidate import _bound_callable
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document, verify_accepted_document,
)
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _projection(root: Path, acceptance: Path) -> int:
    projected = project_accepted_document(root, acceptance_path=acceptance, category="prose")
    errors = verify_accepted_document(root, acceptance_path=acceptance,
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category="prose")
    locators = [row["locator"]["text_part"] for row in projected["rows"]]
    if errors or locators != ["front"] * 3 + ["body"] * 13 + ["back"] * 2:
        raise PipelineError(f"PG3296 native projection differs: {errors[:3]}; rows={len(locators)}")
    return len(locators)


def preflight(stage: Path, receipt_sha256: str, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    stage = stage.resolve(strict=True)
    fixture = root != ROOT.resolve(strict=True)
    if fixture:
        marker = root / ".ocd-augustines-pg3296-install-fixture"
        if not marker.is_file() or marker.read_text(encoding="utf-8") != "fixture-only\n":
            raise PipelineError("PG3296 root override requires an explicit fixture marker")
    candidate_root = (LIBRARY / "candidate-reviews").resolve(strict=True)
    if (stage.parent != candidate_root or not stage.name.startswith("augustines-pg3296-s")
            or root == stage or root in stage.parents
            or len(receipt_sha256) != 64
            or any(c not in "0123456789abcdef" for c in receipt_sha256)):
        raise PipelineError("PG3296 stage path, root, or receipt pin differs")
    receipt_path = stage / "stage-receipt.json"
    if _sha(receipt_path) != receipt_sha256:
        raise PipelineError("PG3296 receipt differs from caller pin")
    receipt = _read(receipt_path)
    if (receipt.get("contract") != "ocd-augustines-pg3296-external-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("work_id") != WORK_ID
            or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA
            or receipt.get("projection_category") != "prose"
            or receipt.get("projection_rows") != 18
            or receipt.get("independent_verifier_errors") != []
            or receipt.get("physical_line_count") != 9724
            or receipt.get("catalog_bom_witness") != "separate-not-substituted"
            or receipt.get("installation") != "not-performed"):
        raise PipelineError("PG3296 stage receipt identity or claim differs")
    before = _files(root / WORK)
    after = _files(stage / WORK)
    if before != receipt.get("before") or after != receipt.get("after"):
        raise PipelineError("PG3296 complete work preimage or stage generation differs")
    if _io_path(root / EDITION / "acceptance.json").exists() or _io_path(root / EDITION / "master.tei.xml").exists():
        raise PipelineError("PG3296 edition already has accepted master")
    for relative in before:
        if relative not in {"state.json", "work.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"PG3296 stage changes existing authority: {relative}")
    current_work = _read(root / WORK / "work.json")
    proposed_work = _read(stage / WORK / "work.json")
    expected_work = json.loads(json.dumps(current_work))
    if (len(expected_work["textual_forms"]) != 1
            or len(expected_work["textual_forms"][0]["editions"]) != 1):
        raise PipelineError("PG3296 sole form/edition preimage differs")
    form = expected_work["textual_forms"][0]
    edition = form["editions"][0]
    if (form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition.get("category") is not None):
        raise PipelineError("PG3296 identity preimage differs")
    edition["category"] = "prose"
    if proposed_work != expected_work:
        raise PipelineError("PG3296 metadata change exceeds source-bound category")
    master_rel = (EDITION / "master.tei.xml").relative_to(WORK).as_posix()
    acceptance_rel = (EDITION / "acceptance.json").relative_to(WORK).as_posix()
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for relative in set(after) - set(before):
        if relative not in {master_rel, acceptance_rel} and not relative.startswith(evidence_prefix):
            raise PipelineError(f"PG3296 stage adds undeclared work file: {relative}")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    dependencies = {MANIFEST, CATALOG, ACQUISITION}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    dependencies.add(Path(manifest.record["converter"]["implementation_path"]))
    dependencies.add(Path(manifest.record["validator"]["implementation_path"]))
    for relative in dependencies:
        if _sha(root / relative) != _sha(stage / relative):
            raise PipelineError(f"PG3296 source dependency changed: {relative}")
    if manifest.sha256 != receipt["source_manifest_sha256"] or _sha(root / SOURCE) != SOURCE_SHA:
        raise PipelineError("PG3296 source manifest or exact CRLF text differs")
    package = CandidatePackage.load(stage / EVIDENCE / "inputs/package")
    if (package.sha256 != receipt["candidate_package_sha256"]
            or package.sha256 != CandidatePackage.load(CANDIDATE).sha256):
        raise PipelineError("PG3296 candidate package differs")
    oracle = _bound_callable(root, manifest.record["validator"], role="validator") if fixture else _oracle
    report = validate(manifest, package, oracle)
    if report.status != "pass" or report.sha256 != receipt["oracle_report_sha256"]:
        raise PipelineError(f"PG3296 fresh source oracle failed: {report.findings[:3]}")
    account = _read(stage / EVIDENCE / "source-accounting.json")
    source_account = _read(stage / EVIDENCE / "inputs/package/source-accountability.json")
    if (account.get("physical_line_count") != 9724
            or account.get("line_inventory_sha256") != source_account.get("line_inventory_sha256")
            or source_account.get("physical_line_count") != 9724
            or len(source_account.get("line_inventory", [])) != 9724
            or source_account.get("omitted_count") != 0
            or source_account.get("duplicate_count") != 0
            or len(source_account.get("book_order", [])) != 13
            or len(account.get("included_members", [])) != 1
            or account.get("excluded_members") != []):
        raise PipelineError("PG3296 complete source/member accounting differs")
    original = _io_path(stage / EVIDENCE / "inputs/package/content.tei.xml").read_bytes()
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
            or _sha(stage / EDITION / "master.tei.xml") != receipt["master_sha256"]
            or _sha(stage / EDITION / "acceptance.json") != receipt["acceptance_sha256"]):
        raise PipelineError("PG3296 staged master changed source candidate after header")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    if validated["promotion"]["status"] != "promoted" or validated["identity"]["work_id"] != WORK_ID:
        raise PipelineError("PG3296 accepted authority differs")
    rows = _projection(stage, acceptance)
    return {"status": "ready-for-review", "work_id": WORK_ID,
            "receipt_sha256": receipt_sha256, "before_files": len(before),
            "after_files": len(after), "native_rows": rows,
            "source_lines": 9724, "scope_kind": "selection"}


def install(stage: Path, receipt_sha256: str, *, root: Path = ROOT,
            fail_at: Callable[[str], None] | None = None) -> dict:
    root = root.resolve(strict=True)
    stage = stage.resolve(strict=True)
    target, source = root / WORK, stage / WORK
    with ExitStack() as locks:
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
        preflight(stage, receipt_sha256, root=root)
        receipt = _read(stage / "stage-receipt.json")

        def checkpoint(point: str) -> None:
            if point == "after-validated":
                if _files(target) != receipt["after"]:
                    raise PipelineError("installed PG3296 work generation differs")
                acceptance = target / (EDITION / "acceptance.json").relative_to(WORK)
                validate_acceptance(acceptance, root=root)
                validate_state(target / "state.json", root=root)
                _projection(root, acceptance)
            if fail_at is not None:
                fail_at(point)

        result = _commit_generation(
            root, target, source, work_id=WORK_ID,
            before=receipt["before"], after=receipt["after"],
            existed=True, replacement=False,
            operation_kind="pg3296-exact-crlf-text-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )
    return result | {"projection_rows": 18}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    ready = preflight(args.stage, args.expected_sha256)
    if args.apply:
        ready["installation"] = install(args.stage, args.expected_sha256)
    print(json.dumps(ready, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
