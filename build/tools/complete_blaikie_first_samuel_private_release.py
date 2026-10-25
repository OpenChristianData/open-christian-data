"""Privately release the unchanged accepted First Book of Samuel title work."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from build.tools.check_release_reader import check_reader
from build.tools.complete_puritan_private_release import check, read, save, sha
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files


WID = "blaikie-first-book-of-samuel"
FORM_ID = "blaikie-first-book-of-samuel--retained-en"
EDITION_ID = "blaikie-first-book-of-samuel--ccel-electronic"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
SOURCE = ROOT / "raw/ccel/expositors-bible/blaikie_expositor8.xml"
CHECKPOINT = ROOT / "reports/_logs/current-root-installed-20261003-v1/blaikie-three-title-checkpoint-v1.json"
JOURNAL = ROOT / "reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/title-canonical-operation-journal-v2.json"
INSTALL_READBACK = ROOT / "reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/parent-title-installed-generation-readback-v2.json"
READER_PROOF = ROOT / "reports/_logs/blaikie-first-samuel-existing-install-20261003-v1/current-reader-after-group-native-proof-v1.json"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
CCEL_PERMISSION = ROOT / "sources/commentaries/expositors-bible/ccel-permission.md"
SOURCE_NOTE = ROOT / "sources/commentaries" / WID / "README.source.md"
DATA_NOTICE = ROOT / "data/commentaries" / WID / "README.md"
LOG = ROOT / "reports/_logs/blaikie-first-samuel-private-release-20261004-v1"

MASTER_SHA = "2bc3bc13824ca7068521a9fbf499ffebe0bec0f425ee34de5131fbb1e3c94409"
ACCEPTANCE_SHA = "391e6014a06a221d6f8e8093ca48d37d399e7cbaf8c720cc55ad624fb456c296"
SOURCE_SHA = "b46bd6cb856df0819dedc06b23a657f7763b49501248db63ce762585d67603d4"
CHECKPOINT_SHA = "89e21cb1145f66ae0cc715131ceb0d449431924b00df59f8e0ae4eecff4192f9"
JOURNAL_SHA = "879b6f4e38daa5b7ae896393b4add54dfe8a23998b09c85779200e014d5884bb"
INSTALL_READBACK_SHA = "2b273fe5819205b8e30fbcc454caf2ea4aca67cdd3295b48fd28a336498520cb"
READER_PROOF_SHA = "fbac14b1ad22d93f3d84921e3b7a4accb9144f6b88e8ab7659c714afe6fd6ed1"
CCEL_PERMISSION_SHA = "e71d588f2309d0cb03f84310fe8149bbfa26309a4f1ef7a2df2b8645b14d93d1"
SOURCE_NOTE_SHA = "b32f995fb3c4a6380d53064a389d83b71bb11f044f4b48a5ba9cf1cb5d0bd5e1"
DATA_NOTICE_SHA = "48cbf98f9e2c10dab97e9c3e87d96cc115a45e8282f06b6346fa90e0382fd153"
PUBLIC_PRIVATE_PATTERN = re.compile(r"(?i)[0-9a-f]{64}|raw/ccel|master\.tei\.xml")
EXPECTED_RELEASE_FILES = {
    "internal/checks/independent-check.json",
    f"internal/projection-receipts/{WID}.json",
    "internal/release-report.json",
    "internal/release-selection.json",
    "public/README.md",
    "public/data/commentary/train.arrow",
    "public/data/commentary/train.jsonl",
}


def loaded_first_party_paths() -> set[Path]:
    paths: set[Path] = set()
    for module in tuple(sys.modules.values()):
        value = getattr(module, "__file__", None)
        if value:
            path = Path(value).resolve()
            if path.suffix == ".py" and (path.is_relative_to(ROOT / "ocd_kernel")
                                         or path.is_relative_to(ROOT / "build")):
                paths.add(path)
    return paths


def first_party_code_and_schemas() -> set[Path]:
    """Capture the maintained release-consumer closure and actual loaded modules."""
    homes = ("ocd_kernel/projection", "ocd_kernel/lib", "ocd_kernel/release",
             "ocd_kernel/library", "ocd_kernel/tei")
    paths = {path for folder in homes for path in (ROOT / folder).rglob("*.py") if path.is_file()}
    paths.add(ROOT / "ocd_kernel/__init__.py")
    paths.add(Path(__file__).resolve())
    for relative in ("build/tools/complete_puritan_private_release.py",
                     "build/tools/report_release_stats.py", "build/tools/check_release_reader.py",
                     "build/tools/check_hf_release.py", "build/scripts/export_huggingface.py"):
        paths.add(ROOT / relative)
    for folder in ("schemas/v2", "ocd_kernel/schemas/v1"):
        paths.update(path for path in (ROOT / folder).rglob("*.json") if path.is_file())
    paths.update(loaded_first_party_paths())
    return paths


def require_loaded_first_party_bound(bindings: dict[str, str]) -> None:
    unbound = {path.relative_to(ROOT).as_posix() for path in loaded_first_party_paths()} - set(bindings)
    if unbound:
        raise PipelineError("Loaded First Samuel consumer lacks pre-gate binding: " + str(sorted(unbound)))


def verify_saved_install() -> dict[str, str]:
    expected = ((MASTER, MASTER_SHA), (ACCEPTANCE, ACCEPTANCE_SHA), (SOURCE, SOURCE_SHA),
                (CHECKPOINT, CHECKPOINT_SHA), (JOURNAL, JOURNAL_SHA),
                (INSTALL_READBACK, INSTALL_READBACK_SHA), (READER_PROOF, READER_PROOF_SHA),
                (CCEL_PERMISSION, CCEL_PERMISSION_SHA),
                (SOURCE_NOTE, SOURCE_NOTE_SHA), (DATA_NOTICE, DATA_NOTICE_SHA))
    if any(not digest for _, digest in expected):
        raise PipelineError("First Samuel runner has unfrozen evidence or notice pins")
    for path, digest in expected:
        if sha(path) != digest:
            raise PipelineError("First Samuel installed authority or notice changed: " + str(path))
    installed = _files(WORK)
    checkpoint = read(CHECKPOINT)
    matches = [item for item in checkpoint["works"] if item["work_id"] == WID]
    journal, prior, current = read(JOURNAL), read(INSTALL_READBACK), read(READER_PROOF)
    if (len(matches) != 1 or matches[0]["canonical_files"] != installed
            or matches[0]["files"] != 26 or matches[0]["projection_rows"] != 38
            or len(installed) != 26 or journal.get("phase") != "complete"
            or journal.get("work_id") != WID or journal.get("after") != installed
            or prior.get("status") != "pass" or prior.get("after_files") != 26
            or prior.get("projection_gate", {}).get("status") != "pass"
            or prior["projection_gate"].get("rows") != 38
            or current.get("status") != "pass" or current.get("projection", {}).get("rows") != 38
            or current.get("independent_observer", {}).get("status") != "pass"
            or current.get("accepted_master", {}).get("sha256") != MASTER_SHA
            or current.get("accepted_record", {}).get("sha256") != ACCEPTANCE_SHA
            or current.get("full_installed_and_stage_26_file_maps_equal_twice") is not True
            or read(INDEX)["by_work"].get(WID, [])):
        raise PipelineError("First Samuel saved install, observer, or prior selection differs")
    return installed


def bindings_for(installed: dict[str, str]) -> dict[str, str]:
    bindings = {(Path("library/works") / WID / name).as_posix(): digest
                for name, digest in installed.items()}
    fixed = [SOURCE, CHECKPOINT, JOURNAL, INSTALL_READBACK, READER_PROOF, INDEX, CCEL_PERMISSION,
             SOURCE_NOTE, DATA_NOTICE]
    fixed.extend(first_party_code_and_schemas())
    for path in fixed:
        relative = path.relative_to(ROOT).as_posix()
        digest = sha(path)
        if relative in bindings and bindings[relative] != digest:
            raise PipelineError("Conflicting First Samuel binding: " + relative)
        bindings[relative] = digest
    return bindings


def run() -> dict:
    if io_path(LOG).exists() or (WORK / "publication").exists():
        raise PipelineError("Fresh First Samuel private release destination required")
    installed = verify_saved_install()
    notice_text = DATA_NOTICE.read_text(encoding="utf-8")
    for phrase in ("W. G. Blaikie", "William Robertson Nicoll", "sourced via CCEL.org",
                   "Willard", "Williard", "I–XXXVI", "Public Domain", "formatting",
                   "do not sell", "rights", "private offline"):
        if phrase not in notice_text:
            raise PipelineError("First Samuel visible notice lost a source or rights qualifier: " + phrase)
    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(),
              "source_sha256": sha(SOURCE_NOTE),
              "notice_path": DATA_NOTICE.relative_to(ROOT).as_posix(),
              "notice_sha256": sha(DATA_NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "blaikie-first-samuel-private-offline-20261004-v1",
                 "items": [{"item_id": WID, "category": "commentary",
                            "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if len(shown) != 1 or notice_text.rstrip() not in shown[0]:
        raise PipelineError("First Samuel complete source and rights notice is not visible")

    bindings = bindings_for(installed)
    check(bindings)
    require_loaded_first_party_bound(bindings)
    save(LOG / "selection.json", selection)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "source-inventory.json", {
        "status": "pass", "work_id": WID, "retained_members": 1,
        "installed_files": 26, "saved_projection_rows": 38,
        "source_sha256": SOURCE_SHA, "checkpoint_sha256": CHECKPOINT_SHA,
        "ccel_permission_sha256": CCEL_PERMISSION_SHA,
        "saved_current_reader_sha256": READER_PROOF_SHA,
        "prior_release_selections": [], "human_acceptance": "not-recorded",
        "rights_clearance": "unresolved", "public_publication": "not-performed",
    })

    destination = LOG / "release"
    gates: dict[str, str] = {}
    with cached_edition_lookups():
        for name, operation in (
            ("assembly", lambda: assemble_release_v2(ROOT, destination, selection=selection)),
            ("independent-verification", lambda: verify_release_v2(ROOT, destination, selection=selection)),
            ("statistics", lambda: release_statistics(ROOT, destination, selection)),
            ("readers", lambda: check_reader(ROOT, destination, selection)),
        ):
            print(name + ": START", flush=True)
            result = operation()
            save(LOG / (name + ".json"), result)
            if result["status"] != "pass":
                raise PipelineError(name + " failed: " + json.dumps(result))
            gates[name] = sha(LOG / (name + ".json"))
            require_loaded_first_party_bound(bindings)
            print(name + ": PASS", flush=True)

    assembly = read(LOG / "assembly.json")
    if (len(assembly["items"]) != 1 or assembly["items"][0]["item_id"] != WID
            or assembly["items"][0]["status"] not in {"included", "warned"}
            or assembly["items"][0]["row_count"] != 38):
        raise PipelineError("First Samuel assembly item accounting differs")
    stats = read(LOG / "statistics.json")["total"]
    if stats["records"] != 38:
        raise PipelineError("Released First Samuel row count differs")
    receipt = destination / "internal/projection-receipts" / (WID + ".json")
    rows_path = destination / "public/data/commentary/train.jsonl"
    if read(receipt)["mapping_version"] != "ocd-commentary-mapping-provisional-v9":
        raise PipelineError("Released First Samuel accepted-commentary mapping differs")
    rows = 0
    with io_path(rows_path).open("r", encoding="utf-8") as stream:
        for line in stream:
            rows += 1
            if PUBLIC_PRIVATE_PATTERN.search(line) or PUBLIC_PRIVATE_PATTERN.search(unquote(line)):
                raise PipelineError(f"First Samuel public row exposes private source binding at {rows}")
    if rows != 38 or notice_text.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
        raise PipelineError("First Samuel public rows or complete visible notice differ")
    check(bindings)
    require_loaded_first_party_bound(bindings)
    if _files(WORK) != installed:
        raise PipelineError("First Samuel original 26 installed files changed during release")
    release_files = _files(destination)
    if set(release_files) != EXPECTED_RELEASE_FILES:
        raise PipelineError("First Samuel seven-file private release differs")

    completion = {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "work_id": WID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID,
                  "rows": 38, "text_characters": stats["text_characters"],
                  "source_sha256": SOURCE_SHA, "accepted_master_sha256": MASTER_SHA,
                  "acceptance_sha256": ACCEPTANCE_SHA, "installed_work_files": 26,
                  "saved_install_checkpoint_sha256": CHECKPOINT_SHA,
                  "saved_install_journal_sha256": JOURNAL_SHA,
                  "saved_install_readback_sha256": INSTALL_READBACK_SHA,
                  "saved_current_reader_sha256": READER_PROOF_SHA,
                  "retained_ccel_permission_sha256": CCEL_PERMISSION_SHA,
                  "selected_source_notice_sha256": SOURCE_NOTE_SHA,
                  "visible_data_notice_sha256": DATA_NOTICE_SHA,
                  "input_bindings": bindings, "preserved_work_files": installed,
                  "release_file_bindings": release_files, "gates": gates,
                  "release_item_status": assembly["items"][0]["status"],
                  "release_item_reasons": assembly["items"][0]["reasons"],
                  "projection_receipt_sha256": sha(receipt), "public_rows_sha256": sha(rows_path),
                  "selection_path": (LOG / "selection.json").relative_to(ROOT).as_posix(),
                  "selection_sha256": sha(LOG / "selection.json"),
                  "release_path": str(destination.resolve()), "private_offline": True,
                  "publication_performed": False, "human_acceptance": "not-recorded",
                  "print_collation": "not-performed", "rights_clearance": "unresolved",
                  "final_public_release_selection": "unresolved",
                  "reconstruction_performed": False, "reinstall_performed": False}
    save(LOG / "completion.json", completion)
    save(WORK / "publication/completion.json", (LOG / "completion.json").read_bytes())
    save(WORK / "publication/selection.json", (LOG / "selection.json").read_bytes())
    save(WORK / "publication/README.md", (
        "# The First Book of Samuel: private offline release\n\n"
        "The unchanged accepted W. G. Blaikie First Samuel CCEL electronic witness passes current "
        "accepted-commentary projection, independent release verification, statistics, and both "
        "offline readers: 38 rows. The public dataset card carries the complete source and rights "
        "notice. This is the separately titled First Samuel work, not the older author container, "
        "Second Samuel, Joshua, or the whole Expositor's Bible series.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this private release. "
        "Human textual review, printed-edition collation, independent electronic-file and formatting "
        "rights clearance, and public publication remain separate.\n").encode("utf-8"))
    expected_work = {**installed, **{"publication/" + name: sha(WORK / "publication" / name)
                                   for name in ("completion.json", "selection.json", "README.md")}}
    check(bindings)
    if _files(WORK) != expected_work or _files(destination) != release_files:
        raise PipelineError("Final First Samuel pointers or release files differ")
    save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
         "canonical_files": expected_work, "release_files": release_files,
         "rows": 38, "text_characters": stats["text_characters"],
         "public_rows_sha256": sha(rows_path), "projection_receipt_sha256": sha(receipt),
         "publication_performed": False,
         "completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
         "selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json")})
    return completion


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "rows": result["rows"],
                      "text_characters": result["text_characters"]}, sort_keys=True))
