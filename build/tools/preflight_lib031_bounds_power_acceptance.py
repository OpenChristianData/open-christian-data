"""Read-only install preflight for the isolated LIB-031 Bounds Power stage.

This command has no apply option. An installer must use the returned exact
before/after generations and repeat this preflight immediately before a swap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/bounds-power-through-prayer")
EDITION = WORK / "forms/bounds-power-through-prayer-english/editions/bounds-power-through-prayer-ccel-thml-electronic"
ACQUISITION = EDITION / "acquisitions/bounds-power-through-prayer-ccel-retained-xml.json"
FIXTURE_MARKER = ".ocd-lib031-bounds-power-install-fixture"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def preflight(stage: Path, receipt_sha256: str, *, root_override: Path | None = None) -> dict[str, object]:
    stage = stage.resolve(strict=True)
    root = root_override.resolve(strict=True) if root_override is not None else ROOT.resolve(strict=True)
    fixture = root_override is not None
    if fixture and not (root / FIXTURE_MARKER).is_file():
        raise PipelineError("Bounds root override requires an explicit fixture marker")
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("Bounds stage and target roots overlap")
    if (stage.parent != Path(r"D:\Library\Open Christian Data").resolve(strict=True)
            or not stage.name.startswith("bpow")
            or len(receipt_sha256) != 64):
        raise PipelineError("stage path or receipt pin is outside the declared Bounds route")
    receipt_path = stage / "stage-receipt.json"
    if _sha(receipt_path) != receipt_sha256:
        raise PipelineError("staged Bounds receipt differs from the caller pin")
    receipt = _read(receipt_path)
    if (receipt.get("contract") != "ocd-lib031-bounds-power-stage-v1"
            or receipt.get("status") != "staged-only"
            or Path(str(receipt.get("stage_root"))).resolve() != stage
            or receipt.get("projection_independent_verifier_errors") != []
            or receipt.get("projection_structure_kinds", {}).get("division") != 22
            or receipt.get("projection_structure_kinds", {}).get("heading") != 21):
        raise PipelineError("staged Bounds receipt route or native structure differs")
    staged_files = _files(stage / WORK)
    current_files = _files(root / WORK)
    acquisition_relative = ACQUISITION.relative_to(WORK).as_posix()
    if (current_files.get(acquisition_relative) != staged_files.get(acquisition_relative)
            or any(path not in {"work.json", "state.json", acquisition_relative} for path in current_files)):
        raise PipelineError("canonical Bounds work generation is not the declared three-file acquired baseline")
    expected_new = {"work.json", "state.json", (EDITION / "master.tei.xml").relative_to(WORK).as_posix(), (EDITION / "acceptance.json").relative_to(WORK).as_posix()}
    for path in set(current_files) | set(staged_files):
        if current_files.get(path) == staged_files.get(path):
            continue
        if path in expected_new:
            continue
        if path.startswith("integration/lib031-bounds-power-electronic-v1/") and path not in current_files:
            continue
        raise PipelineError(f"staged Bounds work change exceeds the guarded generation: {path}")
    current_work = _read(root / WORK / "work.json")
    staged_work = _read(stage / WORK / "work.json")
    if current_work.get("creators") or staged_work.get("creators") != [{"name": "Edward M. Bounds", "role": "author", "evidence": ["raw/ccel/bounds/power.xml"]}]:
        raise PipelineError("source-supported creator delta differs")
    current_edition = current_work["textual_forms"][0]["editions"][0]
    staged_edition = staged_work["textual_forms"][0]["editions"][0]
    if (current_edition.get("category") is not None or staged_edition.get("category") != "prose"
            or current_edition.get("language") != "en" or staged_edition.get("language") != "en"):
        raise PipelineError("prose category or language metadata delta differs")
    expected_work = json.loads(json.dumps(current_work))
    expected_work["creators"] = [{"name": "Edward M. Bounds", "role": "author", "evidence": ["raw/ccel/bounds/power.xml"]}]
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if staged_work != expected_work:
        raise PipelineError("staged work.json differs beyond source-evidenced category and creator")
    current_state = _read(root / WORK / "state.json")
    staged_state = _read(stage / WORK / "state.json")
    current_edition_target = next(item for item in current_state["targets"] if item["target_id"] == current_edition["edition_id"])
    staged_edition_target = next(item for item in staged_state["targets"] if item["target_id"] == staged_edition["edition_id"])
    if (current_edition_target["stage"] != "acquired" or staged_edition_target["stage"] != "accepted"
            or staged_edition_target["evidence"] != current_edition_target["evidence"] + [
                (EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()]
            or staged_edition_target["reason"] != PROMOTED_MASTER_REASON):
        raise PipelineError("edition state transition differs")
    expected_state = json.loads(json.dumps(current_state))
    expected_target = next(item for item in expected_state["targets"] if item["target_id"] == current_edition["edition_id"])
    for key in ("stage", "reason", "updated_at", "evidence"):
        expected_target[key] = staged_edition_target[key]
    if staged_state != expected_state:
        raise PipelineError("staged state differs beyond the one-edition acceptance transition")
    for relative, expected in _files(stage).items():
        if relative == "stage-receipt.json" or relative.startswith(WORK.as_posix() + "/"):
            continue
        if relative.startswith(("raw/", "reports/", "exports/")):
            current = root / relative if fixture else resolve_repo_path(root, relative)
        else:
            current = root / relative
        if not current.is_file() or _sha(current) != expected:
            raise PipelineError(f"external staged source or evidence differs: {relative}")
    acceptance = stage / EDITION / "acceptance.json"
    validated = validate_acceptance(acceptance, root=stage)
    if (_sha(acceptance) != receipt["acceptance_sha256"]
            or _sha(stage / EDITION / "master.tei.xml") != receipt["master_sha256"]
            or validated["promotion"]["status"] != "promoted"):
        raise PipelineError("staged accepted master or record differs")
    projection = project_accepted_prose(stage, acceptance_path=acceptance)
    errors = verify_accepted_prose(stage, acceptance_path=acceptance, rows=projection["rows"], receipt=projection["receipt"])
    if errors or len(projection["rows"]) != 1 or projection["receipt"]["unsupported"]:
        raise PipelineError(f"staged Bounds prose projection is not independently verified: {errors[:3]}")
    return {"contract": "ocd-lib031-bounds-power-install-preflight-v1", "status": "pass-read-only", "canonical_action": "none", "stage_receipt_sha256": receipt_sha256, "stage_root": stage.as_posix(), "target_root": root.as_posix(), "current_work_files": len(current_files), "staged_work_files": len(staged_files), "before": current_files, "after": staged_files, "acceptance_sha256": receipt["acceptance_sha256"], "master_sha256": receipt["master_sha256"], "projection_rows": len(projection["rows"]), "projection_independent_verifier_errors": errors, "rights_clearance": receipt["rights_clearance"], "publication": receipt["publication"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    args = parser.parse_args()
    result = preflight(args.stage, args.receipt_sha256)
    print(json.dumps({key: value for key, value in result.items() if key not in {"before", "after"}}, sort_keys=True))


if __name__ == "__main__":
    main()
