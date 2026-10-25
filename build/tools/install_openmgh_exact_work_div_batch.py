"""Generic exact-pin preflight and stock transaction for openMGH work-div stages.

This module has no install CLI. A cohort-specific wrapper must pin a reviewed
freeze file SHA-256 and work allowlist before exposing an --apply route.
"""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json
from pathlib import Path

from build.tei.openmgh_exact_work_div import check_candidate
from build.tools import prepare_openmgh_exact_work_div_batch as source
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document, verify_accepted_document,
)
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _commit_generation
from ocd_kernel.tei.validate import validate_file


ROOT = Path(__file__).resolve().parents[2]
FREEZE_CONTRACT = "ocd-openmgh-exact-work-div-freeze-v1"
STAGE_CONTRACT = "ocd-openmgh-exact-work-div-acceptance-stage-v1"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(Path(_io_path(path)).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _frozen(freeze_path: Path, expected_sha256: str) -> dict:
    freeze_path = freeze_path.resolve(strict=True)
    if _sha(freeze_path) != expected_sha256:
        raise PipelineError("reviewed exact-source freeze changed")
    frozen = _read(freeze_path)
    if (frozen.get("contract") != FREEZE_CONTRACT
            or frozen.get("status") != "review-ready-staged-only"
            or frozen.get("canonical_install") != "not-performed"):
        raise PipelineError("unrecognized exact-source freeze")
    return frozen


def _record(frozen: dict, work_id: str) -> tuple[dict, Path, dict]:
    pins = [item for item in frozen["works"] if item["work_id"] == work_id]
    if len(pins) != 1:
        raise PipelineError("work absent or repeated in reviewed freeze")
    pin = pins[0]
    receipt = Path(frozen["stage_home"]) / pin["stage_receipt"]
    if _sha(receipt) != pin["stage_receipt_sha256"]:
        raise PipelineError("work stage receipt differs from reviewed freeze")
    record = _read(receipt)
    if (record.get("contract") != STAGE_CONTRACT
            or record.get("status") != "staged-only"
            or record.get("work_id") != work_id
            or record.get("installation") != "not-performed"
            or record.get("projection_rows") != 1):
        raise PipelineError("unrecognized work-local stage")
    return pin, receipt, record


def preflight(freeze_path: Path, *, expected_freeze_sha256: str,
              work_id: str, root: Path = ROOT) -> dict:
    root = root.resolve(strict=True)
    if root != ROOT.resolve(strict=True):
        raise PipelineError("canonical workspace checkout required")
    frozen = _frozen(freeze_path, expected_freeze_sha256)
    manifest_path = root / frozen["manifest"]["path"]
    if _sha(manifest_path) != frozen["manifest"]["sha256"]:
        raise PipelineError("source manifest differs from reviewed freeze")
    manifest = source._manifest(manifest_path, root)
    direct_path = Path(frozen["direct_candidates"]["path"])
    if _sha(direct_path) != frozen["direct_candidates"]["sha256"]:
        raise PipelineError("direct candidate receipt differs from reviewed freeze")
    direct = _read(direct_path)
    if (direct.get("contract") != source.CONTRACT
            or direct.get("manifest_sha256") != frozen["manifest"]["sha256"]
            or len(direct.get("works", [])) != len(manifest["works"])):
        raise PipelineError("direct candidate scope changed")
    entries = [entry for entry in manifest["works"] if entry["work_id"] == work_id]
    directs = [item for item in direct["works"] if item["work_id"] == work_id]
    if len(entries) != 1 or len(directs) != 1:
        raise PipelineError("work missing or repeated in manifest/direct receipt")
    entry, item = entries[0], directs[0]
    pin, receipt, record = _record(frozen, work_id)
    stage = Path(record["stage_root"]).resolve(strict=True)
    if (stage != (Path(frozen["stage_home"]) / work_id).resolve(strict=True)
            or root in stage.parents or stage in root.parents or stage == root
            or Path(record["canonical_root"]).resolve(strict=True) != root
            or record.get("manifest_sha256") != frozen["manifest"]["sha256"]
            or record.get("direct_receipt_sha256") != frozen["direct_candidates"]["sha256"]
            or record.get("category") != entry["category"]
            or record.get("language") != entry["language"]):
        raise PipelineError("work stage root or identity changed")
    work_rel = Path(entry["work_path"]).parent
    if _files(root / work_rel) != record["before"] or _files(stage / work_rel) != record["after"]:
        raise PipelineError("canonical or staged work generation changed")
    live_work, acquired = source._work(root, entry, manifest)
    if (_sha(stage / entry["acquisition_path"]) != entry["acquisition_sha256"]
            or _sha(stage / manifest["source"]["path"]) != manifest["source"]["sha256"]
            or _sha(stage / manifest["package"]["path"]) != manifest["package"]["sha256"]
            or _sha(stage / manifest["acquisition_receipt"]["path"])
               != manifest["acquisition_receipt"]["sha256"]):
        raise PipelineError("staged acquisition copy differs")
    future_work = _read(stage / entry["work_path"])
    validate_identity_update(live_work, future_work)
    load_work(stage / entry["work_path"])
    future_edition = future_work["textual_forms"][0]["editions"][0]
    if (future_edition.get("category") != entry["category"]
            or future_edition.get("language") != entry["language"]):
        raise PipelineError("staged edition category or language changed")
    candidate_path = Path(item["candidate_path"])
    if _sha(candidate_path) != item["candidate_sha256"]:
        raise PipelineError("source-derived direct candidate changed")
    source_bytes = Path(_io_path(root / manifest["source"]["path"])).read_bytes()
    direct_bytes = Path(_io_path(candidate_path)).read_bytes()
    oracle = check_candidate(source_bytes, direct_bytes, manifest, entry, live_work, acquired)
    if (oracle != item["independent_oracle"]
            or item["source_work_div_index"] != entry["source_work_div_index"]):
        raise PipelineError("independent source oracle differs")
    form = future_work["textual_forms"][0]
    edition = (work_rel / "forms" / form["textual_form_id"] / "editions"
               / future_edition["edition_id"])
    acceptance_rel = edition / "acceptance.json"
    master_rel = edition / "master.tei.xml"
    if (Path(_io_path(root / acceptance_rel)).exists()
            or Path(_io_path(root / master_rel)).exists()):
        raise PipelineError("canonical master already exists")
    accepted = validate_acceptance(stage / acceptance_rel, root=stage)
    validate_state(stage / work_rel / "state.json", root=stage)
    master = stage / master_rel
    if (_sha(master) != pin["accepted_master_sha256"]
            or _sha(master) != record["accepted_master_sha256"]
            or _sha(stage / acceptance_rel) != record["acceptance_sha256"]
            or accepted["promotion"]["master"]["sha256"] != pin["accepted_master_sha256"]
            or Path(_io_path(master)).read_bytes().split(b"</teiHeader>", 1)[1]
               != direct_bytes.split(b"</teiHeader>", 1)[1]):
        raise PipelineError("accepted master differs from reviewed source body")
    if errors := validate_file(Path(_io_path(master))):
        raise PipelineError(f"staged master TEI XSD failed: {errors[:3]}")
    notice = stage / edition / "README.source.md"
    if (not Path(_io_path(notice)).is_file()
            or b"Monumenta Germaniae Historica" not in Path(_io_path(notice)).read_bytes()):
        raise PipelineError("human-visible source attribution notice absent")
    projected = project_accepted_document(Path(_io_path(stage)),
                                          acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                          category=entry["category"])
    errors = verify_accepted_document(Path(_io_path(stage)),
                                      acceptance_path=Path(_io_path(stage / acceptance_rel)),
                                      rows=projected["rows"], receipt=projected["receipt"],
                                      category=entry["category"])
    if errors or len(projected["rows"]) != 1:
        raise PipelineError(f"staged native document row changed: {errors[:3]}")
    return {"status": "ready-for-review", "work_id": work_id,
            "source_work_div_index": entry["source_work_div_index"],
            "before_files": len(record["before"]), "after_files": len(record["after"]),
            "projection_rows": 1, "installation": "not-performed",
            "stage_receipt": str(receipt)}


def install(freeze_path: Path, *, expected_freeze_sha256: str,
            work_id: str, fail_at: Callable[[str], None] | None = None) -> dict:
    preflight(freeze_path, expected_freeze_sha256=expected_freeze_sha256, work_id=work_id)
    frozen = _frozen(freeze_path, expected_freeze_sha256)
    pin, receipt, record = _record(frozen, work_id)
    root = ROOT.resolve(strict=True)
    work = Path("library/works") / work_id
    target = root / work
    stage = Path(record["stage_root"]).resolve(strict=True)
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _sha(receipt) != pin["stage_receipt_sha256"]:
            raise PipelineError("reviewed stage receipt changed under work lock")
        preflight(freeze_path, expected_freeze_sha256=expected_freeze_sha256,
                  work_id=work_id)
        result = _commit_generation(
            root, target, stage / work, work_id=work_id,
            before=record["before"], after=record["after"],
            existed=True, replacement=False,
            operation_kind="openmgh-exact-work-div-initial-install",
            result_status="installed-and-validated",
            accepted_editions=1, fail_at=fail_at,
        )
    return result
