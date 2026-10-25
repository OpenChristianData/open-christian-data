"""Privately release the unchanged accepted partial BCP 1928 Collects witness."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

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
from ocd_kernel.release.public_allowlist import _scan
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files


WID = "bcp-1928-collects"
FID = "bcp-1928-collects-retained-electronic"
EID = "bcp-1928-collects-retained-electronic-witness"
AID = "bcp-1928-collects-retained-source-set"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms" / FID / "editions" / EID
MASTER = EDITION / "master.tei.xml"
ACCEPTANCE = EDITION / "acceptance.json"
MANIFEST = ROOT / "sources/prayers" / WID / (WID + ".source-manifest.json")
SOURCE_NOTICE = ROOT / "sources/prayers" / WID / "README.source.md"
DATA_NOTICE = ROOT / "data/prayers/bcp-1928/README.md"
INSTALL = ROOT / "reports/_logs/bcp1928-audit-install-20261004-v1"
STAGE = INSTALL / "stage-receipt.json"
JOURNAL = INSTALL / "install-journal.json"
READBACK = INSTALL / "installed-readback.json"
AUDIT = INSTALL / "installed-generation-audit.json"
SAVED_PROJECTION = WORK / "integration/retained-markup-v7/acceptance-20261004-v1/actual-staged-master-projection.json"
CURRENT_MANIFEST = WORK / "integration/retained-markup-v7/source-manifest-current-v7.json"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
LOG = ROOT / "reports/_logs/bcp1928-private-release-20261004-v1"
PUB = WORK / "publication"
MASTER_SHA = "3258698a841175a5ac4031fc18d1154f3abc46ffd905b6e73f70eac9ed1af167"
ACCEPTANCE_SHA = "1c4b770543582dfaa6e312f438fe0aa95e2927277ef25666310d75cf92d5fbcf"
AUDIT_SHA = "130da87f7ba7b615bbe862c2286b0e1961693a0fb79216c698a236d18d57a304"
READBACK_SHA = "f3d48d76ff9f8eac18e130266902e436316cb6203b6fa26f207f55358950bf4e"
PROJECTION_SHA = "ba9a04a722053eaf841bf095d73f0bb9ed71eb53fbe4b833044b1101fbe09574"
CURRENT_MANIFEST_SHA = "61b05f654f4ca932bcdde8cbe45fc6242ecd9eb3e7f8b8c139f974788ccaf1c6"
MANIFEST_SHA = "139c88453f8ca1f8cc5be76fe9267eb5e6475fea5807053014082381db2558e3"
SOURCE_NOTICE_SHA = "9e11660c885d3d8757b36efa1d8f848497c1899b27bca29b024e78f8b9f1be91"
DATA_NOTICE_SHA = "9add0ba919a5ebe022fb11844c1301d7bb8606835b16cbd81da7dd113d189591"
EXPECTED_RELEASE_FILES = {
    "internal/checks/independent-check.json",
    f"internal/projection-receipts/{WID}.json",
    "internal/release-report.json",
    "internal/release-selection.json",
    "public/README.md",
    "public/data/prayers/train.arrow",
    "public/data/prayers/train.jsonl",
}


def loaded_first_party() -> set[Path]:
    paths = set()
    for module in tuple(sys.modules.values()):
        value = getattr(module, "__file__", None)
        if value:
            path = Path(value).resolve()
            if path.suffix == ".py" and (
                path.is_relative_to(ROOT / "ocd_kernel") or path.is_relative_to(ROOT / "build")
            ):
                paths.add(path)
    return paths


def consumer_paths() -> set[Path]:
    homes = ("ocd_kernel/projection", "ocd_kernel/lib", "ocd_kernel/release",
             "ocd_kernel/library", "ocd_kernel/tei", "ocd_kernel/reconstruction",
             "build/lib")
    paths = {path for home in homes for path in (ROOT / home).rglob("*.py") if path.is_file()}
    paths.update(loaded_first_party())
    for name in ("ocd_kernel/__init__.py", "build/__init__.py", "build/tools/__init__.py",
                 "build/tools/complete_bcp1928_private_release.py",
                 "build/tools/complete_puritan_private_release.py",
                 "build/tools/report_release_stats.py", "build/tools/check_release_reader.py",
                 "build/tools/check_hf_release.py", "build/scripts/export_huggingface.py"):
        path = ROOT / name
        if path.is_file():
            paths.add(path)
    for home in ("schemas/v2", "ocd_kernel/schemas/v1"):
        paths.update(path for path in (ROOT / home).rglob("*.json") if path.is_file())
    return paths


def check_loaded(bindings: dict[str, str]) -> None:
    missing = {path.relative_to(ROOT).as_posix() for path in loaded_first_party()} - set(bindings)
    if missing:
        raise PipelineError("BCP1928 loaded consumer lacks pre-gate binding: " + str(sorted(missing)))


def verify_install() -> tuple[dict[str, str], list[dict]]:
    fixed = ((MASTER, MASTER_SHA), (ACCEPTANCE, ACCEPTANCE_SHA),
             (AUDIT, AUDIT_SHA), (READBACK, READBACK_SHA),
             (SAVED_PROJECTION, PROJECTION_SHA),
             (CURRENT_MANIFEST, CURRENT_MANIFEST_SHA), (MANIFEST, MANIFEST_SHA),
             (SOURCE_NOTICE, SOURCE_NOTICE_SHA), (DATA_NOTICE, DATA_NOTICE_SHA))
    if any(not expected for _, expected in fixed):
        raise PipelineError("BCP1928 runner has unfrozen notice or evidence pins")
    for path, expected in fixed:
        if sha(path) != expected:
            raise PipelineError("BCP1928 installed evidence or notice changed: " + str(path))
    installed = _files(WORK)
    audit, readback, stage, journal = (read(path) for path in (AUDIT, READBACK, STAGE, JOURNAL))
    projection, manifest, accepted = read(SAVED_PROJECTION), read(MANIFEST), read(ACCEPTANCE)
    members = manifest["source_members"]
    identity = {"work_id": WID, "textual_form_id": FID, "edition_id": EID, "acquisition_id": AID}
    if (
        audit["status"] != "pass" or audit["identity"] != identity
        or audit["installed_files"] != 44 or len(installed) != 44
        or audit["source_members"] != 100 or audit["projection_rows"] != 100
        or audit["projection_characters"] != 34003
        or audit["missing_collect_pages"] != ["Trinity23.html", "Trinity24.html"]
        or audit["master_sha256"] != MASTER_SHA or audit["acceptance_sha256"] != ACCEPTANCE_SHA
        or audit["source_manifest_sha256"] != CURRENT_MANIFEST_SHA
        or readback["status"] != "installed-and-validated"
        or readback["all_installed_hashes_equal"] is not True
        or readback["installed_files"] != installed
        or stage["status"] != "staged-only" or stage["after"] != installed
        or stage["master_sha256"] != MASTER_SHA
        or journal["phase"] != "complete" or journal["after"] != installed
        or accepted["identity"] != identity
        or projection["status"] != "pass" or projection["rows"] != 100
        or projection["characters"] != 34003
        or projection["receipt"]["master_sha256"] != MASTER_SHA
        or projection["receipt"]["mapping_version"] != "ocd-prayers-native-v2"
        or len(members) != 100 or manifest["scope"]["member_count"] != 100
        or read(INDEX)["by_work"].get(WID, [])
    ):
        raise PipelineError("BCP1928 saved installation, scope, or prior release differs")
    for member in members:
        if sha(ROOT / member["path"]) != member["sha256"]:
            raise PipelineError("BCP1928 retained source member differs: " + member["path"])
    return installed, members


def input_bindings(installed: dict[str, str], members: list[dict]) -> dict[str, str]:
    bindings = {(Path("library/works") / WID / name).as_posix(): digest
                for name, digest in installed.items()}
    fixed = (MANIFEST, SOURCE_NOTICE, DATA_NOTICE, STAGE, JOURNAL, READBACK, AUDIT,
             SAVED_PROJECTION, CURRENT_MANIFEST, INDEX)
    for path in [*fixed, *(ROOT / member["path"] for member in members), *consumer_paths()]:
        name = path.relative_to(ROOT).as_posix()
        digest = sha(path)
        if name in bindings and bindings[name] != digest:
            raise PipelineError("BCP1928 conflicting input binding: " + name)
        bindings[name] = digest
    return dict(sorted(bindings.items()))


def run() -> dict:
    if io_path(LOG).exists() or io_path(PUB).exists():
        raise PipelineError("Fresh BCP1928 private release and publication roots required")
    installed, members = verify_install()
    source_text = SOURCE_NOTICE.read_text(encoding="utf-8")
    notice_text = DATA_NOTICE.read_text(encoding="utf-8")
    if "data/prayers/bcp-1928/README.md" not in source_text:
        raise PipelineError("BCP1928 source notice lacks data notice direction")
    for phrase in ("EpiscopalNet", "episcopalnet.org", "Trinity 23", "Trinity 24",
                   "Superstats", "MyComputer.com, Inc.", "rights", "private offline"):
        if phrase not in notice_text:
            raise PipelineError("BCP1928 visible notice lost: " + phrase)
    notice = {"source_path": SOURCE_NOTICE.relative_to(ROOT).as_posix(),
              "source_sha256": SOURCE_NOTICE_SHA,
              "notice_path": DATA_NOTICE.relative_to(ROOT).as_posix(),
              "notice_sha256": DATA_NOTICE_SHA}
    selection = {"schema_version": "2.0",
                 "release_id": "bcp1928-private-offline-20261004-v1",
                 "items": [{"item_id": WID, "category": "prayers",
                            "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    if notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE) != [notice_text]:
        raise PipelineError("BCP1928 source-bound visible notice preflight differs")
    bindings = input_bindings(installed, members)
    check(bindings)
    check_loaded(bindings)
    save(LOG / "selection.json", selection)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "source-scope.json", {
        "status": "pass", "work_id": WID, "installed_files": 44,
        "retained_members": 100, "collect_rows": 100, "text_characters": 34003,
        "missing_collect_pages": ["Trinity23.html", "Trinity24.html"],
        "source_provider": "episcopalnet.org", "source_notice_sha256": SOURCE_NOTICE_SHA,
        "visible_notice_sha256": DATA_NOTICE_SHA, "saved_install_audit_sha256": AUDIT_SHA,
        "saved_actual_master_projection_sha256": PROJECTION_SHA,
        "human_acceptance": "not-recorded", "rights_clearance": "unresolved",
        "public_publication": "not-performed"})

    destination = LOG / "release"
    gates = {}
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
                raise PipelineError("BCP1928 " + name + " failed: " + json.dumps(result))
            gates[name] = sha(LOG / (name + ".json"))
            check_loaded(bindings)
            print(name + ": PASS", flush=True)
    assembly = read(LOG / "assembly.json")
    if (len(assembly["items"]) != 1 or assembly["items"][0]["item_id"] != WID
            or assembly["items"][0]["status"] not in {"included", "warned"}
            or assembly["items"][0]["row_count"] != 100):
        raise PipelineError("BCP1928 assembly item accounting differs")
    stats = read(LOG / "statistics.json")["total"]
    if stats["records"] != 100 or stats["text_characters"] != 34003:
        raise PipelineError("BCP1928 released statistics differ")
    receipt = destination / "internal/projection-receipts" / (WID + ".json")
    rows_path = destination / "public/data/prayers/train.jsonl"
    if read(receipt)["mapping_version"] != "ocd-prayers-native-v2":
        raise PipelineError("BCP1928 released native prayer mapping differs")
    count = 0
    with io_path(rows_path).open("r", encoding="utf-8") as stream:
        for count, line in enumerate(stream, 1):
            if _scan(json.loads(line), "BCP1928 public prayer row"):
                raise PipelineError("BCP1928 public prayer row exposes private content: " + str(count))
    card = io_path(destination / "public/README.md").read_text(encoding="utf-8")
    if count != 100 or notice_text.rstrip() not in card:
        raise PipelineError("BCP1928 public rows or complete visible notice differ")
    save(LOG / "public-boundary.json", {
        "status": "pass", "rows": count, "recursive_decoded_string_scan": True,
        "visible_notice_embedded": True, "notice_sha256": DATA_NOTICE_SHA})
    check(bindings)
    check_loaded(bindings)
    if _files(WORK) != installed:
        raise PipelineError("BCP1928 original 44 installed files changed during release")
    release_files = _files(destination)
    if set(release_files) != EXPECTED_RELEASE_FILES:
        raise PipelineError("BCP1928 seven-file private release differs")
    completion = {
        "status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
        "work_id": WID, "textual_form_id": FID, "edition_id": EID,
        "acquisition_id": AID, "rows": 100, "text_characters": 34003,
        "installed_work_files": 44, "retained_source_members": 100,
        "missing_collect_pages": ["Trinity23.html", "Trinity24.html"],
        "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": ACCEPTANCE_SHA,
        "saved_install_audit_sha256": AUDIT_SHA,
        "saved_actual_master_projection_sha256": PROJECTION_SHA,
        "source_notice_sha256": SOURCE_NOTICE_SHA, "visible_notice_sha256": DATA_NOTICE_SHA,
        "input_bindings": bindings, "preserved_work_files": installed,
        "release_file_bindings": release_files, "gates": gates,
        "projection_receipt_sha256": sha(receipt), "public_rows_sha256": sha(rows_path),
        "selection_path": (LOG / "selection.json").relative_to(ROOT).as_posix(),
        "selection_sha256": sha(LOG / "selection.json"),
        "release_path": str(destination.resolve()), "private_offline": True,
        "publication_performed": False, "human_acceptance": "not-recorded",
        "print_collation": "not-performed", "rights_clearance": "unresolved",
        "public_publication_selection": "unresolved",
        "reconstruction_performed": False, "reinstall_performed": False}
    save(LOG / "completion.json", completion)
    save(PUB / "completion.json", (LOG / "completion.json").read_bytes())
    save(PUB / "selection.json", (LOG / "selection.json").read_bytes())
    save(PUB / "README.md", (
        "# BCP 1928 Collects: private offline release\n\n"
        "The unchanged accepted partial EpiscopalNet electronic witness has 100 source-derived "
        "collects from 100 retained pages. The Trinity 23 and Trinity 24 pages contain no "
        "collect; their historical external print-scan claims are outside this accepted master. "
        "Current private assembly, independent verification, statistics, and normal and "
        "streaming readers pass. The complete source and rights notice is visible in the "
        "private dataset card.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this private "
        "release. Human textual acceptance, print collation, electronic-expression rights "
        "clearance, and public publication remain separate.\n").encode("utf-8"))
    expected_work = {**installed, **{"publication/" + name: sha(PUB / name)
                     for name in ("completion.json", "selection.json", "README.md")}}
    check(bindings)
    if _files(WORK) != expected_work or _files(destination) != release_files:
        raise PipelineError("BCP1928 final pointers or private release differ")
    save(LOG / "final-audit.json", {
        "status": "pass", "input_binding_count": len(bindings),
        "canonical_files": expected_work, "release_files": release_files,
        "rows": 100, "text_characters": 34003,
        "public_rows_sha256": sha(rows_path),
        "projection_receipt_sha256": sha(receipt),
        "publication_performed": False,
        "completion_byte_identical": sha(PUB / "completion.json") == sha(LOG / "completion.json"),
        "selection_byte_identical": sha(PUB / "selection.json") == sha(LOG / "selection.json")})
    return completion


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "rows": result["rows"],
                      "text_characters": result["text_characters"]}, sort_keys=True), flush=True)
