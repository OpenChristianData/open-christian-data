"""Read-only preflight or guarded install of pinned LIB062 catechism stages.

The default command changes nothing. ``--apply`` commits one complete work
generation with the shared lock, durable journal, and automatic rollback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable

from build.tools.stage_creeds_json_lib062_remaining import CONTRACT, ROOT, ROUTES
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.catechisms import project_accepted_catechisms, verify_accepted_catechisms
from ocd_kernel.projection.categories.creeds_json_lib062_remaining_profile import PROFILE
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation, _files, _io_path


STAGE_PARENT = Path("D:/Library/Open Christian Data/reports/runs/creeds-json-lib062-remaining-stage-20260926-r3")
SHORTER_STAGE_PARENT = Path("D:/Library/Open Christian Data/reports/runs/creeds-json-shorter-explained-stage-20260929-r1")
EXPOSITION_STAGE_PARENT = Path("D:/Library/Open Christian Data/reports/runs/creeds-json-exposition-stage-20260929-r1")
HEIDELBERG_STAGE_PARENT = Path("D:/Library/Open Christian Data/reports/runs/creeds-json-heidelberg-stage-20260930-r1")
STAGE_RECEIPTS = json.loads((ROOT / "build/tools/creeds_json_lib062_remaining_receipts.json").read_text(encoding="utf-8"))
FIXTURE_MARKER = ".ocd-creeds-lib062-remaining-install-fixture"
FIXTURE_CONTENT = "ocd-creeds-lib062-remaining-install-fixture-v1\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _stage_parent(work_id: str) -> Path:
    if work_id == "heidelberg-catechism":
        return HEIDELBERG_STAGE_PARENT
    if work_id == "shorter-catechism-explained":
        return SHORTER_STAGE_PARENT
    if work_id == "exposition-of-the-assemblies-catechism":
        return EXPOSITION_STAGE_PARENT
    return STAGE_PARENT


def _paths(root: Path, work_id: str) -> tuple[Path, Path]:
    route = ROUTES[work_id]
    work = root / "library/works" / work_id
    form_id = route.get("textual_form_id", f"{work_id}-retained-electronic")
    acceptance = work / "forms" / form_id / "editions" / route["edition_id"] / "acceptance.json"
    return work, acceptance


def _null_paths(value: object, path: str = "$") -> list[str]:
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [found for key, child in value.items() for found in _null_paths(child, f"{path}/{key}")]
    if isinstance(value, list):
        return [found for index, child in enumerate(value) for found in _null_paths(child, f"{path}/{index}")]
    return []


def _project_check(root: Path, acceptance: Path, work_id: str) -> int:
    output = project_accepted_catechisms(_io_path(root), acceptance_path=_io_path(acceptance))
    errors = verify_accepted_catechisms(
        _io_path(root), acceptance_path=_io_path(acceptance), rows=output["rows"], receipt=output["receipt"],
    )
    route = ROUTES[work_id]
    receipt = output["receipt"]
    if (errors or receipt.get("profile") != PROFILE or len(output["rows"]) != route["row_count"]
            or receipt.get("proof_count") != route["proof_count"]
            or receipt.get("reference_count") != route["reference_count"]
            or receipt.get("subquestion_count") != route["subquestion_count"]
            or (work_id == "heidelberg-catechism" and receipt.get("question_with_proofs_count") != 2)):
        raise PipelineError(f"native catechism projection differs: {errors[:3]}")
    retained = json.loads(_io_path(root / route["source_path"]).read_bytes())
    if receipt["null_json_paths"] != _null_paths(retained):
        raise PipelineError("typed source null paths differ from retained catechism")
    if any(row["item_id"] != str(source["Number"]) or row["question"] != source["Question"]
           or row["answer"] != source["Answer"]
           for row, source in zip(output["rows"], retained["Data"], strict=True)):
        raise PipelineError("source-defined catechism Q&A differs")
    return len(output["rows"])


def preflight(work_id: str, *, root_override: Path | None = None) -> dict[str, object]:
    if work_id not in STAGE_RECEIPTS or work_id not in ROUTES:
        raise PipelineError("work is outside pinned catechism stages")
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    if root_override is not None and _io_path(root / FIXTURE_MARKER).read_text(encoding="utf-8") != FIXTURE_CONTENT:
        raise PipelineError("isolated catechism install root requires the exact fixture marker")
    stage_parent = _stage_parent(work_id).resolve(strict=True)
    stage = (stage_parent / work_id).resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents or stage.parent != stage_parent:
        raise PipelineError("stage is outside the bounded durable reports route")
    receipt_path = stage / "final-stage-receipt.json"
    if _sha(receipt_path) != STAGE_RECEIPTS[work_id]:
        raise PipelineError("complete catechism stage receipt differs from pinned bytes")
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
            or receipt.get("projection_proofs") != route["proof_count"]
            or receipt.get("projection_references") != route["reference_count"]
            or receipt.get("projection_subquestions") != route["subquestion_count"]
            or (work_id == "heidelberg-catechism" and receipt.get("projection_question_with_proofs") != 2)
            or receipt.get("projection_independent_verifier_errors") != []):
        raise PipelineError("stage identity, source, or native catechism projection differs")
    work, _ = _paths(root, work_id)
    staged_work, staged_acceptance = _paths(stage, work_id)
    before, after = receipt["before"], receipt["after"]
    if _files(work) != before or _files(staged_work) != after:
        raise PipelineError("canonical before or staged after complete generation differs")
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    if changed != set(receipt["changed_paths"]):
        raise PipelineError("stage changed-path set differs")
    form_id = route.get("textual_form_id", f"{work_id}-retained-electronic")
    acquisition = f"forms/{form_id}/editions/{route['edition_id']}/acquisitions/{route['acquisition_id']}.json"
    if set(before) != {"work.json", "state.json", acquisition} or before[acquisition] != after[acquisition]:
        raise PipelineError("canonical catechism work is not the three-file acquired baseline")
    edition_prefix = f"forms/{form_id}/editions/{route['edition_id']}/"
    allowed = {"work.json", "state.json", edition_prefix + "master.tei.xml", edition_prefix + "acceptance.json"}
    if any(path not in allowed and not path.startswith(("integration/creeds-json-electronic-v1/",
                                                       "integration/creeds-json-metadata-rebind-v1/")) for path in changed):
        raise PipelineError("staged catechism changes exceed the declared acceptance route")
    for relative, expected in _files(stage).items():
        if relative in {"final-stage-receipt.json"} or relative.startswith(f"library/works/{work_id}/"):
            continue
        canonical = root / relative
        if not _io_path(canonical).is_file() or _sha(canonical) != expected:
            raise PipelineError(f"external catechism stage dependency changed: {relative}")
    accepted = validate_acceptance(_io_path(staged_acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / "library/works" / work_id / "state.json"), root=_io_path(stage))
    if (accepted["promotion"]["status"] != "promoted" or accepted["identity"]["work_id"] != work_id
            or accepted["identity"]["edition_id"] != route["edition_id"]
            or _sha(staged_acceptance) != receipt["acceptance_sha256"]
            or _sha(staged_acceptance.parent / "master.tei.xml") != receipt["master_sha256"]):
        raise PipelineError("staged catechism accepted master or decision differs")
    rows = _project_check(stage, staged_acceptance, work_id)
    return {"status": "ready-stage-only", "work_id": work_id,
            "stage_receipt_sha256": STAGE_RECEIPTS[work_id],
            "before": before, "after": after, "projection_rows": rows,
            "canonical_action": "none", "provider_rights": receipt["provider_rights"]}


def install(work_id: str, *, root_override: Path | None = None,
            after_live_check: Callable[[], None] | None = None) -> dict[str, object]:
    checked = preflight(work_id, root_override=root_override)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    stage = (_stage_parent(work_id) / work_id).resolve(strict=True)
    target, acceptance = _paths(root, work_id)
    source, _ = _paths(stage, work_id)

    def checkpoint(phase: str) -> None:
        if phase == "after-validated":
            _project_check(root, acceptance, work_id)
            if after_live_check is not None:
                after_live_check()

    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != checked["before"] or _files(source) != checked["after"]:
            raise PipelineError("catechism work changed after guarded preflight")
        result = _commit_generation(
            root, target, source, work_id=work_id,
            before=checked["before"], after=checked["after"],
            existed=True, replacement=True,
            operation_kind="creeds-json-lib062-remaining-electronic-v1",
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
