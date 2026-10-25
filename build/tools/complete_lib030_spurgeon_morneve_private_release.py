"""Prepare a private offline release from installed Morning and Evening TEI.

Execution writes only the named reports/_logs and work publication evidence.
The public tree is a private offline verification artifact; this script never
publishes it. Run only after independent parent review of this caller and the
source-directed human-visible notice.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.lib.path_io import io_glob, io_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
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
SOURCE_NOTE = Path("sources/devotionals/spurgeons-morning-evening/README.source.md")
SOURCE_NOTE_SHA256 = "9fa94c69ced32bb4ab74ef3966b36fd896b7085d395422daabcf472837f72f63"
DATA_NOTICE = Path("data/devotionals/spurgeons-morning-evening/README.md")
DATA_NOTICE_SHA256 = "aea2f79347f48e0f75758ed5476c5dc14fd93802b3ac8cff81bff8d4451dc6c5"
INSTALL_READBACK = Path(
    "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
    "MORNING_EVENING_INSTALL_READBACK_20261003.json"
)
INSTALL_READBACK_SHA256 = "b795e7e34d13e0a7b4eab13bc86e0366f005bd0a7afe6425c0a85bcc7fedcf15"
STAGE_RECEIPT = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "spurgeons-morneve-acceptance-stage-20261003-v4/stage-receipt.json"
)
STAGE_RECEIPT_SHA256 = "62c74b568ab704a9ec3e06cc6ecfcf5cb5c0db5ff0f7acd992c7877f2fe6c59b"
JOURNAL = Path(".tmp_audit/accepted-install-18d7fa1eea734a1f/operation.json")
JOURNAL_SHA256 = "a4765f9d07eda79c7cf2a91e650c6c20b5c3134eb7db7e300f4c04ce490132dd"
PARENT_READBACK = Path(
    "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
    "MORNING_EVENING_INSTALL_READBACK_20261003.json"
)
OUT = Path("reports/_logs/morning-evening-private-release-20261003-v1")
PUBLICATION = WORK / "publication"

IMPLEMENTATIONS = (
    "build/tools/complete_lib030_spurgeon_morneve_private_release.py",
    "build/tools/check_release_reader.py",
    "build/tools/report_release_stats.py",
    "build/tools/stage_lib030_spurgeon_morneve_acceptance.py",
    "build/tools/install_lib030_spurgeon_morneve_acceptance.py",
    "build/tools/readback_lib030_spurgeon_morneve_install.py",
    "build/tei/lib030_reconstruction.py",
    "build/tei/lib030_oracle.py",
    "build/tei/lib030_native_projection_adapter.py",
    "ocd_kernel/projection/categories/prose.py",
    "ocd_kernel/projection/categories/native_documents.py",
    "ocd_kernel/projection/native_content.py",
    "ocd_kernel/projection/native_content_check.py",
    "ocd_kernel/projection/source_projection_evidence.py",
    "ocd_kernel/projection/receipt.py",
    "ocd_kernel/release/assemble.py",
    "ocd_kernel/release/verify.py",
    "ocd_kernel/release/notices.py",
    "ocd_kernel/release/selection.py",
    "ocd_kernel/release/typed_rows.py",
    "ocd_kernel/tei/acceptance.py",
    "ocd_kernel/tei/validate.py",
    "ocd_kernel/tei/reviewed_integration.py",
    "ocd_kernel/tei/install_accepted.py",
    "ocd_kernel/library/identities.py",
    "ocd_kernel/library/state.py",
    "ocd_kernel/library/acquisitions.py",
    "ocd_kernel/library/_common.py",
    "ocd_kernel/reconstruction/contract.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(io_path(path).read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(io_path(path).read_bytes())
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def save(path: Path, value: dict) -> None:
    target = io_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )


def _freeze_implementations(manifest: SourceManifest) -> dict[str, str]:
    paths = set(IMPLEMENTATIONS)
    paths.update(
        manifest.record[role]["implementation_path"]
        for role in ("converter", "validator")
    )
    result = {path: digest(ROOT / path) for path in sorted(paths)}
    for schema in io_glob(ROOT / "schemas/v2", "**/*.json"):
        result[schema.relative_to(ROOT).as_posix()] = digest(schema)
    return result


def _check_input_bindings(inputs: dict[str, str], implementation: dict[str, str]) -> None:
    for relative, expected in inputs.items():
        if digest(ROOT / relative) != expected:
            raise PipelineError(f"private-release source or work authority changed: {relative}")
    for relative, expected in implementation.items():
        if digest(ROOT / relative) != expected:
            raise PipelineError(f"private-release implementation or schema changed: {relative}")


@cached_edition_lookups()
def main() -> None:
    log = ROOT / OUT
    release = log / "release"
    completion_target = ROOT / PUBLICATION / "completion.json"
    publication_outputs = (
        ROOT / PUBLICATION / "selection.json",
        ROOT / PUBLICATION / "actual-master-projection.json",
        completion_target,
    )
    if io_path(log).exists() or any(io_path(path).exists() for path in publication_outputs):
        raise FileExistsError("Reconcile an existing private release before rerunning")

    install_bytes = io_path(ROOT / INSTALL_READBACK).read_bytes()
    if hashlib.sha256(install_bytes).hexdigest() != INSTALL_READBACK_SHA256:
        raise PipelineError("parent installed-generation readback changed")
    install = json.loads(install_bytes)
    current_work = ROOT / WORK
    generation = _files(current_work)
    if (install.get("status") != "pass-installed-agent-electronic-witness"
            or install.get("work_id") != WORK_ID
            or install.get("recovery_readback_exit_code") != 0
            or len(generation) != 33
            or generation != install.get("installation", {}).get("installed_files")):
        raise PipelineError("current installed generation differs from parent readback")

    journal_bytes = io_path(ROOT / JOURNAL).read_bytes()
    stage_receipt_bytes = io_path(STAGE_RECEIPT).read_bytes()
    if (hashlib.sha256(journal_bytes).hexdigest() != JOURNAL_SHA256
            or hashlib.sha256(stage_receipt_bytes).hexdigest() != STAGE_RECEIPT_SHA256
            or digest(ROOT / PARENT_READBACK) != INSTALL_READBACK_SHA256
            or json.loads(journal_bytes).get("phase") != "complete"):
        raise PipelineError("completed install journal or stage/parent receipt differs")
    stage_receipt = json.loads(stage_receipt_bytes)
    if (stage_receipt.get("rights") != "unassessed"
            or stage_receipt.get("human_acceptance") != "not-recorded"
            or stage_receipt.get("publication") != "not-authorized"):
        raise PipelineError("technical acceptance boundary changed")

    if digest(ROOT / SOURCE) != SOURCE_SHA256 or digest(ROOT / MANIFEST) != MANIFEST_SHA256:
        raise PipelineError("retained electronic witness or source manifest differs")
    manifest = SourceManifest.load(ROOT / MANIFEST, repository_root=ROOT)
    if manifest.sha256 != MANIFEST_SHA256 or manifest.verify() is not None:
        raise PipelineError("current seven-authority source manifest no longer verifies")
    acquisition = validate_acquisition(ROOT / ACQUISITION, root=ROOT)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != SOURCE.as_posix()):
        raise PipelineError("acquisition no longer binds the exact CCEL witness")

    source_note_hash = digest(ROOT / SOURCE_NOTE)
    notice_hash = digest(ROOT / DATA_NOTICE)
    if source_note_hash != SOURCE_NOTE_SHA256 or notice_hash != DATA_NOTICE_SHA256:
        raise PipelineError("source-directed notice bytes differ from reviewed pins")

    authority_inputs = {
        (WORK / relative).as_posix(): expected
        for relative, expected in generation.items()
    }
    authority_inputs.update({
        SOURCE.as_posix(): SOURCE_SHA256,
        MANIFEST.as_posix(): manifest.sha256,
        SOURCE_NOTE.as_posix(): source_note_hash,
        DATA_NOTICE.as_posix(): notice_hash,
        INSTALL_READBACK.as_posix(): INSTALL_READBACK_SHA256,
        JOURNAL.as_posix(): JOURNAL_SHA256,
    })
    authority_inputs.update({
        item["path"]: item["sha256"] for item in manifest.record["authorities"]
    })
    implementations = _freeze_implementations(manifest)

    acceptance = ROOT / EDITION / "acceptance.json"
    accepted = validate_acceptance(acceptance, root=ROOT)
    state = validate_state(ROOT / WORK / "state.json", root=ROOT)
    if (accepted["identity"].get("work_id") != WORK_ID
            or accepted["identity"].get("textual_form_id") != FORM_ID
            or accepted["identity"].get("edition_id") != EDITION_ID
            or accepted["identity"].get("acquisition_id") != ACQUISITION_ID
            or accepted["promotion"].get("status") != "promoted"
            or accepted["decision"]["human_decision"].get("status") != "not-recorded"
            or accepted["decision"]["agent_assessment"].get("status") != "accepted"):
        raise PipelineError("accepted electronic-witness identity or decision differs")
    edition_targets = [item for item in state["targets"] if item.get("target_id") == EDITION_ID]
    if len(edition_targets) != 1 or edition_targets[0].get("stage") != "accepted":
        raise PipelineError("canonical edition state is not accepted")

    item = {
        "item_id": WORK_ID,
        "category": "prose",
        "acceptance_path": (EDITION / "acceptance.json").as_posix(),
        "public_notices": [{
            "source_path": SOURCE_NOTE.as_posix(),
            "source_sha256": source_note_hash,
            "notice_path": DATA_NOTICE.as_posix(),
            "notice_sha256": notice_hash,
        }],
    }
    selection = {
        "schema_version": "2.0",
        "release_id": "spurgeons-morning-evening-private-offline-20261003-v1",
        "items": [item],
    }
    notices = notice_texts_for_item(ROOT, item, acceptance)
    if (len(notices) != 1 or notices[0] != io_path(ROOT / DATA_NOTICE).read_text(encoding="utf-8")
            or "converter contact" in notices[0].lower()):
        raise PipelineError("source-directed notice binding or privacy disposition differs")

    with cached_edition_lookups():
        projection = project_accepted_prose(ROOT, acceptance_path=acceptance)
        errors = verify_accepted_prose(
            ROOT, acceptance_path=acceptance,
            rows=projection["rows"], receipt=projection["receipt"],
        )
    if (errors or len(projection["rows"]) != 1
            or projection["receipt"].get("master_sha256") != generation[(EDITION / "master.tei.xml").relative_to(WORK).as_posix()]):
        raise PipelineError(f"current accepted-master prose projection differs: {errors[:3]}")

    io_path(log).mkdir(parents=True)
    save(log / "authority-before.json", authority_inputs)
    save(log / "implementation-schema-before.json", implementations)
    save(log / "selection.json", selection)
    save(log / "actual-master-projection.json", projection)
    save(log / "projection-check.json", {
        "status": "pass",
        "work_id": WORK_ID,
        "rows": len(projection["rows"]),
        "text_characters": sum(len(row["text"]) for row in projection["rows"]),
        "master_sha256": projection["receipt"]["master_sha256"],
        "independent_errors": errors,
        "notice_count": len(notices),
        "personal_contact_copied": False,
        "human_acceptance": "not-recorded",
        "rights_clearance": "unassessed",
        "public_authorization": False,
    })

    results = {}
    for name, operation in (
        ("assembly", lambda: assemble_release_v2(ROOT, release, selection=selection)),
        ("independent-verification", lambda: verify_release_v2(ROOT, release, selection=selection)),
        ("statistics", lambda: release_statistics(ROOT, release, selection)),
        ("readers", lambda: check_reader(ROOT, release, selection)),
    ):
        result = operation()
        save(log / f"{name}.json", result)
        if result.get("status") != "pass":
            raise PipelineError(f"Morning and Evening private release {name} failed: {result}")
        results[name] = result

    assembly_items = results["assembly"].get("items", [])
    if (results["assembly"].get("release_id") != selection["release_id"]
            or len(assembly_items) != 1
            or assembly_items[0].get("item_id") != WORK_ID
            or assembly_items[0].get("category") != "prose"
            or assembly_items[0].get("status") not in {"included", "warned"}
            or assembly_items[0].get("row_count") != len(projection["rows"])):
        raise PipelineError("assembled item/row accounting differs from the accepted Morning and Evening work")
    statistics_rows = results["statistics"].get("total", {}).get("records")
    reader_configs = results["readers"].get("configurations", [])
    if (statistics_rows != len(projection["rows"])
            or len(reader_configs) != 1
            or reader_configs[0].get("category") != "prose"
            or reader_configs[0].get("rows") != len(projection["rows"])
            or reader_configs[0].get("normal_and_streaming") != "pass"
            or reader_configs[0].get("all_original_values_and_order_preserved") is not True):
        raise PipelineError("statistics or normal/streaming reader accounting differs")

    public_readme = io_path(release / "public/README.md").read_text(encoding="utf-8")
    if notices[0].rstrip() not in public_readme:
        raise PipelineError("verified private release omits the exact source-directed public notice")
    release_files = _files(release)
    required_outputs = {
        "internal/release-selection.json",
        "internal/release-report.json",
        "internal/checks/independent-check.json",
        "public/README.md",
    }
    for configuration in results["assembly"].get("configurations", []):
        required_outputs.add(configuration["path"])
        typed = configuration.get("typed_companion")
        if isinstance(typed, dict) and isinstance(typed.get("path"), str):
            required_outputs.add(typed["path"])
    if not release_files or not required_outputs.issubset(release_files):
        raise PipelineError("private release output is empty or missing required verified outputs")
    if _files(current_work) != generation:
        raise PipelineError("accepted work generation changed during offline release verification")
    _check_input_bindings(authority_inputs, implementations)
    if digest(STAGE_RECEIPT) != STAGE_RECEIPT_SHA256:
        raise PipelineError("external staged acceptance receipt changed during release verification")

    stats = results["statistics"]
    completion = {
        "contract": "ocd-lib030-morning-evening-private-offline-completion-v1",
        "status": "pass-offline-verified-not-authorized-for-publication",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": WORK_ID,
        "accepted_master_sha256": generation[(EDITION / "master.tei.xml").relative_to(WORK).as_posix()],
        "acceptance_sha256": generation[(EDITION / "acceptance.json").relative_to(WORK).as_posix()],
        "source_sha256": SOURCE_SHA256,
        "source_manifest_sha256": manifest.sha256,
        "source_notice_sha256": source_note_hash,
        "data_notice_sha256": notice_hash,
        "rows": stats["total"]["records"],
        "text_characters": stats["total"]["text_characters"],
        "assembly_item_status": assembly_items[0]["status"],
        "release_path": release.as_posix(),
        "private_offline": True,
        "publication_performed": False,
        "human_acceptance": "not-recorded",
        "rights_clearance": "unassessed",
        "print_collation": "not-performed",
        "personal_contact_copied_to_notice": False,
        "input_bindings": authority_inputs,
        "implementation_schema_bindings": implementations,
        "release_file_bindings": release_files,
        "gates": {name: value.get("status") for name, value in results.items()},
        "remaining": [
            "Human textual acceptance is not recorded.",
            "Collation against an 1865 print exemplar was not performed.",
            "Independent CCEL/Logos rights clearance remains unresolved.",
            "Public attribution notice is prepared but publication authorization is not recorded.",
            "No public publication occurred.",
        ],
    }
    save(ROOT / PUBLICATION / "selection.json", selection)
    save(ROOT / PUBLICATION / "actual-master-projection.json", projection)
    save(log / "release-file-hashes.json", release_files)
    save(log / "completion.json", completion)
    save(ROOT / PUBLICATION / "completion.json", completion)
    print(json.dumps({"status": completion["status"], "rows": completion["rows"],
                      "text_characters": completion["text_characters"],
                      "public_publication": False}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
