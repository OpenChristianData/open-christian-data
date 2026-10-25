"""Read-only preflight or guarded install of Westminster's proof-bound stage.

The default command changes nothing. ``--apply`` commits one complete work
generation with the shared lock, durable journal, and automatic rollback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable

from build.tools.stage_creeds_json_westminster_proofs import CONTRACT, ROOT, ROUTES
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.creeds_json_carrier import PROFILE
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


STAGE_PARENT = Path("D:/Library/Open Christian Data/reports/runs/creeds-json-westminster-proofs-stage-20260926-r2")
STAGE_RECEIPTS = json.loads((ROOT / "build/tools/creeds_json_westminster_proofs_receipts.json").read_text(encoding="utf-8"))
FIXTURE_MARKER = ".ocd-creeds-westminster-proofs-install-fixture"
FIXTURE_CONTENT = "ocd-creeds-westminster-proofs-install-fixture-v1\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _paths(root: Path, work_id: str) -> tuple[Path, Path]:
    work = root / "library/works" / work_id
    acceptance = work / "forms" / f"{work_id}-retained-electronic" / "editions" / f"{work_id}-creeds-json" / "acceptance.json"
    return work, acceptance


def _project_check(root: Path, acceptance: Path, work_id: str) -> int:
    output = project_accepted_doctrinal_documents(_io_path(root), acceptance_path=_io_path(acceptance))
    errors = verify_accepted_doctrinal_documents(
        _io_path(root), acceptance_path=_io_path(acceptance),
        rows=output["rows"], receipt=output["receipt"],
    )
    if (errors or output["receipt"].get("profile") != PROFILE
            or len(output["rows"]) != ROUTES[work_id]["row_count"]):
        raise PipelineError(f"native doctrinal projection differs: {errors[:3]}")
    def null_paths(value: object, path: str = "$") -> list[str]:
        if value is None:
            return [path]
        if isinstance(value, dict):
            return [found for key, child in value.items() for found in null_paths(child, f"{path}/{key}")]
        if isinstance(value, list):
            return [found for index, child in enumerate(value) for found in null_paths(child, f"{path}/{index}")]
        return []

    retained = json.loads(_io_path(root / output["receipt"]["source_path"]).read_bytes())
    expected_nulls = null_paths(retained)
    if [item["json_path"] for item in output["receipt"]["null_carriers"]] != expected_nulls:
        raise PipelineError("typed null carrier paths differ from the retained source")
    source_units = [
        (chapter_index, section_index, chapter, section)
        for chapter_index, chapter in enumerate(retained["Data"])
        for section_index, section in enumerate(chapter["Sections"])
    ]
    if any(
        row["number"] != section["Section"]
        or row["locator"]["divisions"][0]["number"] != chapter["Chapter"]
        or row["locator"]["unit_path"] != ["Data", str(chapter_index), "Sections", str(section_index)]
        or row["content_with_proofs"] != section["ContentWithProofs"]
        or [proof["id"] for proof in row["proofs"]] != [proof["Id"] for proof in section["Proofs"]]
        for row, (chapter_index, section_index, chapter, section) in zip(output["rows"], source_units, strict=True)
    ):
        raise PipelineError("source-defined Westminster hierarchy or proof order differs")
    if (sum(len(row["proofs"]) for row in output["rows"]) != ROUTES[work_id]["proof_count"]
            or sum(len(proof["references"]) for row in output["rows"] for proof in row["proofs"]) != ROUTES[work_id]["reference_count"]):
        raise PipelineError("source-defined Westminster proof/reference census differs")
    return len(output["rows"])


def preflight(work_id: str, *, root_override: Path | None = None) -> dict[str, object]:
    if work_id not in STAGE_RECEIPTS:
        raise PipelineError("work is outside the pinned Westminster proof tranche")
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    if root_override is not None and _io_path(root / FIXTURE_MARKER).read_text(encoding="utf-8") != FIXTURE_CONTENT:
        raise PipelineError("isolated install root requires the exact fixture marker")
    stage = (STAGE_PARENT / work_id).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents or stage.parent != STAGE_PARENT.resolve(strict=True):
        raise PipelineError("stage is outside the bounded durable reports route")
    receipt_path = stage / "final-stage-receipt.json"
    if _sha(receipt_path) != STAGE_RECEIPTS[work_id]:
        raise PipelineError("complete stage receipt differs from the pinned bytes")
    receipt = json.loads(_io_path(receipt_path).read_bytes())
    route = ROUTES[work_id]
    if (receipt.get("contract") != CONTRACT or receipt.get("status") != "staged-only"
            or receipt.get("work_id") != work_id or receipt.get("canonical_root") != ROOT.as_posix()
            or receipt.get("stage_root") != stage.as_posix()
            or receipt.get("source_sha256") != route["source_sha256"]
            or receipt.get("candidate_sha256") != route["package_sha256"]
            or receipt.get("validation_sha256") != route["validation_sha256"]
            or receipt.get("review_sha256") != route["review_sha256"]
            or receipt.get("projection_profile") != PROFILE
            or receipt.get("projection_rows") != route["row_count"]
            or receipt.get("projection_independent_verifier_errors") != []):
        raise PipelineError("stage identity, source, or projection receipt differs")
    work, acceptance = _paths(root, work_id)
    staged_work, staged_acceptance = _paths(stage, work_id)
    before, after = receipt["before"], receipt["after"]
    if _files(work) != before or _files(staged_work) != after:
        raise PipelineError("canonical before or staged after complete generation differs")
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    if changed != set(receipt["changed_paths"]):
        raise PipelineError("stage changed-path set differs")
    if set(before) != {"work.json", "state.json", f"forms/{work_id}-retained-electronic/editions/{work_id}-creeds-json/acquisitions/{work_id}-creeds-json-member.json"}:
        raise PipelineError("canonical work is not the three-file acquired baseline")
    if before[next(path for path in before if path.endswith("-member.json"))] != after[next(path for path in before if path.endswith("-member.json"))]:
        raise PipelineError("staged acquisition differs")
    allowed = {"work.json", "state.json"}
    edition_prefix = f"forms/{work_id}-retained-electronic/editions/{work_id}-creeds-json/"
    integration_prefixes = ("integration/creeds-json-electronic-v1/", "integration/creeds-json-metadata-rebind-v1/")
    if any(path not in allowed and path not in {edition_prefix + "master.tei.xml", edition_prefix + "acceptance.json"}
           and not path.startswith(integration_prefixes) for path in changed):
        raise PipelineError("staged work changes exceed the declared acceptance route")
    for relative, expected in _files(stage).items():
        if relative in {"stage-receipt.json", "final-stage-receipt.json"} or relative.startswith(f"library/works/{work_id}/"):
            continue
        canonical = root / relative
        if not _io_path(canonical).is_file() or _sha(canonical) != expected:
            raise PipelineError(f"external stage dependency changed: {relative}")
    accepted = validate_acceptance(_io_path(staged_acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / "library/works" / work_id / "state.json"), root=_io_path(stage))
    if (accepted["promotion"]["status"] != "promoted" or accepted["identity"]["work_id"] != work_id
            or _sha(staged_acceptance) != receipt["acceptance_sha256"]
            or _sha(staged_acceptance.parent / "master.tei.xml") != receipt["master_sha256"]):
        raise PipelineError("staged accepted master or decision differs")
    rows = _project_check(stage, staged_acceptance, work_id)
    return {"status": "ready-stage-only", "work_id": work_id,
            "stage_receipt_sha256": STAGE_RECEIPTS[work_id],
            "before": before, "after": after, "projection_rows": rows,
            "canonical_action": "none", "provider_rights": receipt["provider_rights"]}


def install(work_id: str, *, root_override: Path | None = None,
            after_live_check: Callable[[], None] | None = None) -> dict[str, object]:
    checked = preflight(work_id, root_override=root_override)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    stage = (STAGE_PARENT / work_id).resolve(strict=True)
    target, acceptance = _paths(root, work_id)
    source, _ = _paths(stage, work_id)

    def checkpoint(phase: str) -> None:
        if phase == "after-validated":
            _project_check(root, acceptance, work_id)
            if after_live_check is not None:
                after_live_check()

    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != checked["before"] or _files(source) != checked["after"]:
            raise PipelineError("work changed after guarded preflight")
        result = _commit_generation(
            root, target, source, work_id=work_id,
            before=checked["before"], after=checked["after"],
            existed=True, replacement=True,
            operation_kind="creeds-json-westminster-proofs-electronic-v1",
            result_status="creeds-json-electronic-accepted",
            accepted_editions=1, fail_at=checkpoint,
        )
    result["stage_receipt_sha256"] = STAGE_RECEIPTS[work_id]
    result["live_projection_rows"] = ROUTES[work_id]["row_count"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, choices=sorted(STAGE_RECEIPTS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = install(args.work) if args.apply else preflight(args.work)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
