"""Preflight or guarded-install the exact staged Morning and Evening work.

The default command is read-only. ``--apply`` delegates the exact work-tree
generation swap to ``ocd_kernel.tei.install_accepted`` after binding the stage
receipt and rechecking the current canonical preimage. This tool does not grant
human acceptance, rights clearance, or publication authorization.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from typing import Any

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.path_io import io_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work, validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import (
    project_accepted_document,
    verify_accepted_document,
)
from ocd_kernel.tei.acceptance import PROMOTED_MASTER_REASON, validate_acceptance
from ocd_kernel.tei.install_accepted import (
    _commit_generation,
    _files,
    _validate_promoted_tree,
    _validate_state_transition,
)
from ocd_kernel.reconstruction import SourceManifest


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = Path("D:/Library/Open Christian Data")
STAGE = LIBRARY / "candidate-reviews/spurgeons-morneve-acceptance-stage-20261003-v4"
RECEIPT_SHA256 = "62c74b568ab704a9ec3e06cc6ecfcf5cb5c0db5ff0f7acd992c7877f2fe6c59b"
WORK_ID = "spurgeons-morning-evening"
WORK = Path("library/works") / WORK_ID
FORM_ID = "spurgeons-morning-evening-english"
EDITION_ID = "spurgeons-morning-evening-ccel-thml-electronic"
ACQUISITION_ID = "spurgeons-morning-evening-ccel-retained-xml"
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACQUISITION = EDITION / "acquisitions" / f"{ACQUISITION_ID}.json"
SOURCE = Path("raw/ccel/spurgeon/morneve.xml")
SOURCE_SHA256 = "3512797ae879d4fdbdcde90e5ebc04299e501658fd8fb6c09977c2e2648ad0a4"
MANIFEST = Path(
    "sources/devotionals/spurgeons-morning-evening/"
    "lib030.source-manifest-current-closure-20261003-v1.json"
)
MANIFEST_SHA256 = "8152bc4c8ad9d0cad8ce283477de7a503031f14564e6f584955662e84fba30bc"
EVIDENCE = WORK / "integration/lib030-current-acceptance-20261003-v1"
AUTHORITY_SNAPSHOT = EVIDENCE / "inputs/source-manifest-authority-snapshots.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _single_edition(work: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    forms = work.get("textual_forms")
    if not isinstance(forms, list) or len(forms) != 1 or not isinstance(forms[0], dict):
        raise PipelineError("expected exactly one Morning and Evening textual form")
    form = forms[0]
    editions = form.get("editions")
    if not isinstance(editions, list) or len(editions) != 1 or not isinstance(editions[0], dict):
        raise PipelineError("expected exactly one Morning and Evening edition")
    return form, editions[0]


def preflight(*, _held_stage_lock: Path | None = None) -> dict[str, Any]:
    root = ROOT.resolve(strict=True)
    stage = STAGE.resolve(strict=True)
    if root == stage or root in stage.parents or stage in root.parents:
        raise PipelineError("canonical and candidate-review roots overlap")
    if stage.parent != (LIBRARY / "candidate-reviews").resolve(strict=True):
        raise PipelineError("stage is outside the exact candidate-review home")
    receipt_path = stage / "stage-receipt.json"
    if _sha(receipt_path) != RECEIPT_SHA256:
        raise PipelineError("v4 stage receipt differs from the reviewed byte pin")
    receipt = _read(receipt_path)
    if (
        receipt.get("contract") != "ocd-lib030-morning-evening-external-stage-v1"
        or receipt.get("status") != "staged-only"
        or receipt.get("work_id") != WORK_ID
        or receipt.get("stage_root") != stage.as_posix()
        or receipt.get("installation") != "not-performed"
        or receipt.get("human_acceptance") != "not-recorded"
        or receipt.get("rights") != "unassessed"
        or receipt.get("publication") != "not-authorized"
        or receipt.get("canonical_before") != receipt.get("canonical_after")
    ):
        raise PipelineError("stage receipt identity or authorization boundary differs")

    live, promoted = root / WORK, stage / WORK
    before = _files(live)
    after = _files(promoted)
    if before != receipt.get("before") or after != receipt.get("after"):
        raise PipelineError("live/staged work generation differs from the receipt snapshots")
    if before != receipt.get("canonical_before"):
        raise PipelineError("canonical work no longer matches the pre-staging snapshot")
    if len(before) != 3 or len(after) != 33 or not set(before).issubset(after):
        raise PipelineError("complete acquired/staged work generations differ from the reviewed 3/33-file scope")
    allowed = {
        "work.json",
        "state.json",
        (EDITION / "master.tei.xml").relative_to(WORK).as_posix(),
        (EDITION / "acceptance.json").relative_to(WORK).as_posix(),
    }
    evidence_prefix = EVIDENCE.relative_to(WORK).as_posix() + "/"
    for path in set(before) | set(after):
        if before.get(path) == after.get(path) or path in allowed:
            continue
        if path.startswith(evidence_prefix) and path not in before and path in after:
            continue
        raise PipelineError(f"staged generation has an unrelated work-local change: {path}")
    acquisition_relative = ACQUISITION.relative_to(WORK).as_posix()
    if before.get(acquisition_relative) != after.get(acquisition_relative):
        raise PipelineError("acquisition record changed in the staged generation")

    if _sha(root / SOURCE) != SOURCE_SHA256 or _sha(root / MANIFEST) != MANIFEST_SHA256:
        raise PipelineError("retained source or current source manifest differs")
    manifest = SourceManifest.load(root / MANIFEST, repository_root=root)
    if manifest.sha256 != MANIFEST_SHA256 or manifest.verify() is not None:
        raise PipelineError("source manifest closure no longer verifies")
    acquisition = validate_acquisition(root / ACQUISITION, root=root)
    if (acquisition["source_sha256"] != SOURCE_SHA256
            or acquisition["source_path"] != SOURCE.as_posix()):
        raise PipelineError("current acquisition identity no longer matches the retained source")

    authority_snapshot = _read(stage / AUTHORITY_SNAPSHOT)
    authorities = manifest.record["authorities"]
    snapshots = authority_snapshot.get("authorities")
    if (authority_snapshot.get("source_manifest_sha256") != manifest.sha256
            or not isinstance(snapshots, list) or len(snapshots) != len(authorities)):
        raise PipelineError("staged seven-authority snapshot inventory differs")
    expected_authorities = {item["name"]: item for item in authorities}
    observed_authorities = {item.get("name"): item for item in snapshots if isinstance(item, dict)}
    if set(observed_authorities) != set(expected_authorities):
        raise PipelineError("staged source-authority snapshot names differ")
    for name, authority in expected_authorities.items():
        snapshot = observed_authorities[name]
        original = Path(authority["path"])
        snapshot_path = Path(snapshot["snapshot_path"])
        data = io_path(stage / snapshot_path).read_bytes()
        if (snapshot.get("original_path") != original.as_posix()
                or snapshot.get("sha256") != authority["sha256"]
                or len(data) != authority["bytes"]
                or _sha(stage / snapshot_path) != authority["sha256"]
                or _sha(root / original) != authority["sha256"]):
            raise PipelineError(f"source authority snapshot differs: {name}")

    for relative_text, digest in _files(stage).items():
        if relative_text == "stage-receipt.json" or relative_text.startswith(WORK.as_posix() + "/"):
            continue
        relative = Path(relative_text)
        if (_held_stage_lock is not None
                and stage / relative == _held_stage_lock):
            if _held_stage_lock != (stage / WORK).with_name(WORK.name + ".lock"):
                raise PipelineError("held stage lock is not the exact lock created for this source")
            continue
        if relative.is_absolute() or ".." in relative.parts or _sha(root / relative) != digest:
            raise PipelineError(f"staged external dependency differs from canonical authority: {relative_text}")

    old_work = _read(live / "work.json")
    staged_work = _read(promoted / "work.json")
    old_form, old_edition = _single_edition(old_work)
    new_form, new_edition = _single_edition(staged_work)
    expected_work = json.loads(json.dumps(old_work))
    expected_work["textual_forms"][0]["editions"][0]["category"] = "prose"
    if staged_work != expected_work:
        raise PipelineError("staged work metadata changes beyond category=prose")
    validate_identity_update(old_work, staged_work)
    if (
        old_form.get("textual_form_id") != FORM_ID
        or old_form.get("language") != "en"
        or old_edition.get("edition_id") != EDITION_ID
        or old_edition.get("language") != "en"
        or old_edition.get("acquisition_ids") != [ACQUISITION_ID]
        or "category" in old_edition
        or new_form.get("textual_form_id") != FORM_ID
        or new_form.get("language") != "en"
        or new_edition.get("category") != "prose"
    ):
        raise PipelineError("form/edition identity or the category-only metadata change differs")
    if not load_work(promoted / "work.json") == staged_work:
        raise PipelineError("staged work metadata does not load through the identity validator")

    old_state, new_state = _read(live / "state.json"), _read(promoted / "state.json")
    old_targets = [item for item in old_state.get("targets", []) if item.get("target_id") == EDITION_ID]
    new_targets = [item for item in new_state.get("targets", []) if item.get("target_id") == EDITION_ID]
    if len(old_targets) != 1 or len(new_targets) != 1:
        raise PipelineError("one exact edition state target is required")
    old_target, new_target = old_targets[0], new_targets[0]
    if (
        old_target.get("stage") != "acquired"
        or new_target.get("stage") != "accepted"
        or new_target.get("reason") != PROMOTED_MASTER_REASON
        or new_target.get("evidence") != old_target.get("evidence")
        + [(EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix()]
    ):
        raise PipelineError("state transition exceeds one promoted edition")
    expected_state = json.loads(json.dumps(old_state))
    expected_target = next(item for item in expected_state["targets"] if item.get("target_id") == EDITION_ID)
    for key in ("stage", "reason", "updated_at", "evidence"):
        expected_target[key] = new_target[key]
    if new_state != expected_state:
        raise PipelineError("staged state differs beyond this edition's acceptance transition")
    validate_state(promoted / "state.json", root=stage)

    acceptance_path = stage / EDITION / "acceptance.json"
    acceptance = validate_acceptance(acceptance_path, root=stage)
    master_path = stage / EDITION / "master.tei.xml"
    if (
        _sha(acceptance_path) != receipt.get("acceptance_sha256")
        or _sha(master_path) != receipt.get("master_sha256")
        or acceptance["promotion"].get("status") != "promoted"
        or acceptance["identity"].get("work_id") != WORK_ID
        or acceptance["identity"].get("textual_form_id") != FORM_ID
        or acceptance["identity"].get("edition_id") != EDITION_ID
        or acceptance["identity"].get("acquisition_id") != ACQUISITION_ID
    ):
        raise PipelineError("promoted master or acceptance binding differs")
    accepted = _validate_promoted_tree(stage, promoted, work_id=WORK_ID)
    if (len(accepted) != 1
            or accepted[0]["identity"].get("edition_id") != EDITION_ID
            or accepted[0]["decision"].get("human_decision", {}).get("status") != "not-recorded"
            or accepted[0]["decision"].get("agent_assessment", {}).get("status") != "accepted"):
        raise PipelineError("promoted tree does not carry the scoped agent electronic-witness decision")
    _validate_state_transition(
        live,
        promoted,
        existed=True,
        replacement=False,
        accepted_evidence_by_edition={
            EDITION_ID: ((EDITION / "master.tei.xml").as_posix(), (EDITION / "acceptance.json").as_posix())
        },
    )
    projection = project_accepted_document(stage, acceptance_path=acceptance_path, category="prose")
    errors = verify_accepted_document(
        stage,
        acceptance_path=acceptance_path,
        rows=projection["rows"],
        receipt=projection["receipt"],
        category="prose",
    )
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"native accepted-master projection failed: {errors[:3]}")
    persisted_path = promoted / Path(
        "integration/lib030-current-acceptance-20261003-v1/accepted-master-projection.json"
    )
    persisted = _read(persisted_path)
    if (
        persisted.get("rows") != projection["rows"]
        or persisted.get("receipt") != projection["receipt"]
        or persisted.get("independent_verifier_errors") != []
    ):
        raise PipelineError("persisted actual-master projection differs from current projection")

    differences = {
        name: {"before": before.get(name), "after": after.get(name)}
        for name in sorted(set(before) | set(after))
        if before.get(name) != after.get(name)
    }
    return {
        "status": "pass-read-only",
        "canonical_action": "none",
        "work_id": WORK_ID,
        "stage": stage.as_posix(),
        "receipt_sha256": RECEIPT_SHA256,
        "before_file_count": len(before),
        "after_file_count": len(after),
        "before": before,
        "after": after,
        "changed_paths": differences,
        "acceptance_sha256": receipt["acceptance_sha256"],
        "master_sha256": receipt["master_sha256"],
        "projection_rows": len(projection["rows"]),
        "independent_projection_errors": errors,
        "rights": receipt["rights"],
        "publication": receipt["publication"],
    }


def install() -> dict[str, Any]:
    record = preflight()
    root, stage = ROOT.resolve(strict=True), STAGE.resolve(strict=True)
    target, source = root / WORK, stage / WORK
    with ExitStack() as locks:
        held_stage_lock = None
        for path in sorted((target, source), key=lambda item: item.as_posix()):
            lock_path = locks.enter_context(acquire_jsonl_lock(path, acquire_timeout=30.0))
            if path == source:
                held_stage_lock = lock_path
        if held_stage_lock is None or preflight(_held_stage_lock=held_stage_lock) != record:
            raise PipelineError("Morning and Evening generation changed while locks were acquired")
        result = _commit_generation(
            root,
            target.resolve(strict=True),
            source.resolve(strict=True),
            work_id=WORK_ID,
            before=record["before"],
            after=record["after"],
            existed=True,
            replacement=False,
            operation_kind="initial-install",
            result_status="installed-and-validated",
            accepted_editions=1,
            fail_at=None,
        )
    installed = root / WORK
    acceptance_path = root / EDITION / "acceptance.json"
    validate_acceptance(acceptance_path, root=root)
    validate_state(installed / "state.json", root=root)
    projection = project_accepted_document(root, acceptance_path=acceptance_path, category="prose")
    errors = verify_accepted_document(
        root,
        acceptance_path=acceptance_path,
        rows=projection["rows"],
        receipt=projection["receipt"],
        category="prose",
    )
    if errors or len(projection["rows"]) != 1:
        raise PipelineError(f"installed actual-master projection failed: {errors[:3]}")
    result.update(projection_rows=len(projection["rows"]), independent_projection_errors=errors)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        print(json.dumps(install(), sort_keys=True))
    else:
        preview = preflight()
        print(json.dumps({
            "status": preview["status"],
            "work_id": preview["work_id"],
            "before_file_count": preview["before_file_count"],
            "after_file_count": preview["after_file_count"],
            "changed_paths": sorted(preview["changed_paths"]),
            "stage_receipt_sha256": preview["receipt_sha256"],
            "projection_rows": preview["projection_rows"],
            "installation": "not-performed",
        }, sort_keys=True))


if __name__ == "__main__":
    main()
