"""Read-only preflight or guarded work-local install of Eliza Southall Brief Memoir PG11959."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path

from build.tei.eliza_southall_pg11959_oracle import _oracle
from build.tools.stage_eliza_southall_pg11959_acceptance import (
    ACQUISITION, CANDIDATE, EDITION, EVIDENCE, FORM_ID, EDITION_ID, LIBRARY,
    MANIFEST, ROOT, SOURCE, SOURCE_SHA, WORK, WORK_ID,
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


def _sha(path: Path) -> str:
    return sha256(_io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(_io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def preflight(stage: Path, receipt_sha256: str, *, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    stage = stage.resolve(strict=True)
    fixture = root != ROOT.resolve(strict=True)
    if fixture:
        marker = root / ".ocd-eliza-southall-install-fixture"
        if not marker.is_file() or marker.read_text(encoding="utf-8") != "fixture-only\n":
            raise PipelineError("Eliza Southall Brief Memoir root override requires an explicit fixture marker")
    candidate_root = (LIBRARY / "candidate-reviews").resolve(strict=True)
    if (stage.parent != candidate_root or not stage.name.startswith("es-s")
            or root == stage or root in stage.parents
            or len(receipt_sha256) != 64
            or any(c not in "0123456789abcdef" for c in receipt_sha256)):
        raise PipelineError("Eliza Southall Brief Memoir stage path, root, or receipt pin differs")
    receipt_path = stage / "stage-receipt.json"
    if _sha(receipt_path) != receipt_sha256:
        raise PipelineError("Eliza Southall Brief Memoir stage receipt differs from caller pin")
    receipt = _read(receipt_path)
    if (receipt.get("contract") != "ocd-eliza-southall-pg11959-external-stage-v1"
            or receipt.get("status") != "staged-only" or receipt.get("work_id") != WORK_ID
            or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != SOURCE_SHA
            or receipt.get("projection_category") != "prose"
            or receipt.get("projection_rows") != 1
            or receipt.get("independent_verifier_errors") != []
            or receipt.get("accepted_source_scope") != "complete-extracted-html-body"
            or receipt.get("excluded_support_members") != 2
            or receipt.get("installation") != "not-performed"):
        raise PipelineError("Eliza Southall Brief Memoir stage receipt identity or claim differs")
    before = _files(root / WORK)
    after = _files(stage / WORK)
    if before != receipt.get("before") or after != receipt.get("after"):
        raise PipelineError("Eliza Southall Brief Memoir complete work preimage or stage generation differs")
    if (root / EDITION / "acceptance.json").exists() or (root / EDITION / "master.tei.xml").exists():
        raise PipelineError("Eliza Southall Brief Memoir edition already has accepted master")
    for relative in before:
        if relative not in {"state.json", "work.json"} and after.get(relative) != before[relative]:
            raise PipelineError(f"Eliza Southall Brief Memoir stage changes existing authority: {relative}")
    current_work = _read(root / WORK / "work.json")
    proposed_work = _read(stage / WORK / "work.json")
    expected_work = json.loads(json.dumps(current_work))
    form = expected_work["textual_forms"][0]
    edition = form["editions"][0]
    if (form["textual_form_id"] != FORM_ID or edition["edition_id"] != EDITION_ID
            or edition.get("category") is not None):
        raise PipelineError("Eliza Southall Brief Memoir work metadata preimage differs")
    form["language"] = "en"
    edition["category"] = "prose"
    edition["language"] = "en"
    if proposed_work != expected_work:
        raise PipelineError("Eliza Southall Brief Memoir metadata change exceeds source-bound category")
    master_rel = (EDITION / "master.tei.xml").relative_to(WORK).as_posix()
    acceptance_rel = (EDITION / "acceptance.json").relative_to(WORK).as_posix()
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for relative in set(after) - set(before):
        if relative not in {master_rel, acceptance_rel} and not relative.startswith(evidence_prefix):
            raise PipelineError(f"Eliza Southall Brief Memoir stage adds undeclared work file: {relative}")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    dependencies = {SOURCE, MANIFEST, Path("raw/gutenberg/11959/acquisition-receipt.json"),
                    Path("raw/gutenberg/11959/html/11959-cover.png"), ACQUISITION}
    dependencies.update(Path(item["path"]) for item in manifest.record["authorities"])
    for relative in dependencies:
        if _sha(root / relative) != _sha(stage / relative):
            raise PipelineError(f"Eliza Southall Brief Memoir source dependency changed: {relative}")
    if manifest.sha256 != receipt["source_manifest_sha256"] or _sha(root / SOURCE) != SOURCE_SHA:
        raise PipelineError("Eliza Southall Brief Memoir manifest or retained extracted HTML differs")
    package = CandidatePackage.load(stage / EVIDENCE / "inputs/package")
    if (package.sha256 != receipt["candidate_package_sha256"]
            or package.sha256 != CandidatePackage.load(CANDIDATE).sha256):
        raise PipelineError("Eliza Southall Brief Memoir candidate package differs")
    validation_manifest = (SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
                           if fixture else manifest)
    report = validate(validation_manifest, package, _oracle)
    if report.status != "pass" or report.sha256 != receipt["oracle_report_sha256"]:
        raise PipelineError(f"Eliza Southall Brief Memoir fresh source oracle failed: {report.findings[:3]}")
    account = _read(stage / EVIDENCE / "source-accounting.json")
    source_account = _read(stage / EVIDENCE / "inputs/package/source-accountability.json")
    if (account.get("represented_html_elements") != 1362
            or account.get("flattened_table_wrappers") != 0
            or account.get("omitted_html_elements") != 0
            or account.get("body_decoded_text_characters") != 274715
            or source_account.get("represented_elements") != 1362
            or source_account.get("flattened_wrappers") != 0
            or source_account.get("omitted_elements") != 0
            or account.get("accepted_scope", {}).get("kind") != "selection"
            or len(account.get("included_members", [])) != 1
            or len(account.get("excluded_members", [])) != 2):
        raise PipelineError("Eliza Southall Brief Memoir exact HTML member accounting differs")
    original = _io_path(stage / EVIDENCE / "inputs/package/content.tei.xml").read_bytes()
    master = _io_path(stage / EDITION / "master.tei.xml").read_bytes()
    if (original.split(b"</teiHeader>", 1)[1] != master.split(b"</teiHeader>", 1)[1]
            or _sha(stage / EDITION / "master.tei.xml") != receipt["master_sha256"]
            or _sha(stage / EDITION / "acceptance.json") != receipt["acceptance_sha256"]):
        raise PipelineError("Eliza Southall Brief Memoir staged master changed source candidate body")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(acceptance, root=stage)
    validate_state(stage / WORK / "state.json", root=stage)
    if (validated["promotion"]["status"] != "promoted"
            or validated["identity"]["work_id"] != WORK_ID):
        raise PipelineError("Eliza Southall Brief Memoir accepted authority differs")
    projection = project_accepted_document(stage, acceptance_path=acceptance, category="prose")
    errors = verify_accepted_document(stage, acceptance_path=acceptance,
                                      rows=projection["rows"], receipt=projection["receipt"],
                                      category="prose")
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"Eliza Southall Brief Memoir actual-master native projection differs: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": WORK_ID,
            "receipt_sha256": receipt_sha256, "before_files": len(before),
            "after_files": len(after), "native_rows": 1,
            "source_elements": 1362, "scope_kind": "selection"}


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
                    raise PipelineError("installed Eliza Southall Brief Memoir work generation differs")
                acceptance = target / (EDITION / "acceptance.json").relative_to(WORK)
                validate_acceptance(acceptance, root=root)
                validate_state(target / "state.json", root=root)
                projected = project_accepted_document(root, acceptance_path=acceptance,
                                                       category="prose")
                errors = verify_accepted_document(root, acceptance_path=acceptance,
                    rows=projected["rows"], receipt=projected["receipt"], category="prose")
                if errors or len(projected["rows"]) != 1:
                    raise PipelineError(f"installed Eliza Southall Brief Memoir native row differs: {errors[:3]}")
            if fail_at is not None:
                fail_at(point)

        result = _commit_generation(
            root, target, source, work_id=WORK_ID,
            before=receipt["before"], after=receipt["after"],
            existed=True, replacement=False,
            operation_kind="pg11959-exact-html-member-install",
            result_status="installed-and-validated", accepted_editions=1,
            fail_at=checkpoint,
        )
    return result | {"projection_rows": 1}


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
