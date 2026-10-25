"""Complete the unchanged accepted Adam Clarke cohort as a private offline release."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

from build.tools.check_release_reader import check_reader
from build.tools.complete_puritan_private_release import check, read, save, sha
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WID = "adam-clarke"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/adam-clarke-retained-en/editions/adam-clarke-retained-electronic"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
MANIFEST = WORK / "integration/helloao-retained-v1/source-manifest-current-v1.json"
PROJECTION_PROOF = WORK / "integration/helloao-retained-v1/acceptance-20261004-v1/actual-staged-master-projection.json"
INSTALL_AUDIT = ROOT / "reports/_logs/clarke-audit-install-20261004-v1/installed-generation-audit.json"
JOURNAL = ROOT / ".tmp_audit/accepted-install-b75832bfb01a4b6a/operation.json"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
SOURCE_NOTE = ROOT / "sources/commentaries/adam-clarke/README.source.md"
NOTICE = ROOT / "data/commentaries/adam-clarke/README.md"
LOG = ROOT / "reports/_logs/adam-clarke-private-release-20261004-v1"
PREFLIGHT = ROOT / ".tmp_audit/adam-clarke-private-release-preflight-20261004-v3.json"
MASTER_SHA = "e0ffd34ad2b2a5a82b8737321b7de5ca3241cf60ffe244ba52dbe1a6f89c4e47"
ACCEPTANCE_SHA = "f70fa97b49044ba50c57d0b07fbe7cfde36b1e049cf578e1b2b314f4c4c8b581"
MANIFEST_SHA = "4bf86ef05871b20be68e194997ecfc64a4c43ed0801fd149a671c14349ff954f"
PROJECTION_PROOF_SHA = "c16a31e75fc49a13625a94c91f5b645234bac9207fe0720f65e9331497eb8f8a"
INSTALL_AUDIT_SHA = "24cecaa167333ff917a21d624f4e811fcce6461a2f02b2267fb97f0d2d3499b7"
JOURNAL_SHA = "4ce6e1cc8bc073f4a18201e8bcc90df43bf6882304315046a22794ac60784218"
SOURCE_NOTE_SHA = "8923e45ffa7143dd74d790c7a9454a85fed511495ed8bcac383b7577b7e27012"
NOTICE_SHA = "d2f4bb447499f43421b9e9d000c05533e32f155403e0c6a10c8f153c5a1133d3"
HELPER_SHA = "1bb6e0b8ff58d0bdb23bc983c260d78507aeb2932fb122be512534752d9c815e"
PRIVATE_PATTERN = re.compile(r"(?i)[0-9a-f]{64}|raw/helloao_local|master\.tei\.xml")
EXPECTED_RELEASE_FILES = {
    "internal/checks/independent-check.json",
    "internal/projection-receipts/adam-clarke.json",
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
    """Bind current maintained release consumers without unrelated source tooling."""
    homes = ("ocd_kernel/projection", "ocd_kernel/lib", "ocd_kernel/release",
             "ocd_kernel/library", "ocd_kernel/tei")
    paths = {path for folder in homes for path in (ROOT / folder).rglob("*.py") if path.is_file()}
    paths.add(ROOT / "ocd_kernel/__init__.py")
    for relative in ("build/tools/complete_clarke_private_release.py",
                     "build/tools/complete_puritan_private_release.py",
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
        raise PipelineError("Loaded Clarke first-party consumer lacks pre-gate binding: " + str(sorted(unbound)))


def source_bindings(manifest: dict) -> dict[str, str]:
    authorities = manifest.get("authorities")
    if not isinstance(authorities, list) or len(authorities) != 864:
        raise PipelineError("Clarke retained authority inventory differs")
    result: dict[str, str] = {}
    for member in authorities:
        relative = member["path"]
        path = ROOT / relative
        if (relative in result or sha(path) != member["sha256"]
                or io_path(path).stat().st_size != member["bytes"]):
            raise PipelineError("Clarke retained source authority changed: " + relative)
        result[relative] = member["sha256"]
    if len(result) != 864 or sum(path.startswith("raw/helloao_local/api/c/adam-clarke/") for path in result) != 856:
        raise PipelineError("Clarke complete 856-member source cohort differs")
    return result


def build_bindings(installed: dict[str, str], manifest: dict) -> dict[str, str]:
    bindings = {(Path("library/works") / WID / name).as_posix(): digest
                for name, digest in installed.items()}
    bindings.update(source_bindings(manifest))
    fixed = [INSTALL_AUDIT, JOURNAL, INDEX, SOURCE_NOTE, NOTICE]
    fixed.extend(first_party_code_and_schemas())
    for path in fixed:
        relative = path.relative_to(ROOT).as_posix()
        current = sha(path)
        if relative in bindings and bindings[relative] != current:
            raise PipelineError("Conflicting Clarke binding: " + relative)
        bindings[relative] = current
    if bindings.get("ocd_kernel/projection/categories/commentary_source_native.py") != HELPER_SHA:
        raise PipelineError("Clarke current source-native helper pin differs")
    return bindings


def run() -> dict:
    if io_path(LOG).exists() or (WORK / "publication").exists():
        raise PipelineError("Fresh Clarke private release destination required")
    for path, expected in ((MASTER, MASTER_SHA), (ACCEPTANCE, ACCEPTANCE_SHA),
                           (MANIFEST, MANIFEST_SHA), (PROJECTION_PROOF, PROJECTION_PROOF_SHA),
                           (INSTALL_AUDIT, INSTALL_AUDIT_SHA), (JOURNAL, JOURNAL_SHA),
                           (SOURCE_NOTE, SOURCE_NOTE_SHA), (NOTICE, NOTICE_SHA),
                           (ROOT / "ocd_kernel/projection/categories/commentary_source_native.py", HELPER_SHA)):
        if sha(path) != expected:
            raise PipelineError("Clarke accepted or notice authority changed: " + str(path))
    installed = _files(WORK)
    journal, audit, proof, manifest = read(JOURNAL), read(INSTALL_AUDIT), read(PROJECTION_PROOF), read(MANIFEST)
    if (len(installed) != 33 or journal.get("phase") != "complete"
            or journal.get("work_id") != WID or journal.get("after") != installed
            or audit.get("status") != "pass" or audit.get("installed_file_count") != 33
            or audit.get("master_sha256") != MASTER_SHA or audit.get("acceptance_sha256") != ACCEPTANCE_SHA
            or audit.get("actual_master_projection_rows") != 57
            or audit.get("actual_master_projection_characters") != 13583400
            or audit.get("independent_checker_with_producer_disabled_pass") is not True
            or proof.get("status") != "pass" or proof.get("rows") != 57
            or proof.get("characters") != 13583400
            or read(INDEX)["by_work"].get(WID, [])):
        raise PipelineError("Clarke install, saved projection proof, or prior release selection differs")
    notice_text = NOTICE.read_text(encoding="utf-8")
    for phrase in ("Adam Clarke", "HelloAO", "Public Domain Mark 1.0", "cc0-1.0",
                   "Rights in the electronic transcription and formatting have not been independently cleared",
                   "Deuteronomy, Judges, Psalms, Proverbs, Ecclesiastes, Jeremiah, Joel, Malachi, and Matthew",
                   "127", "2 Samuel 14:27", "hath not God", "not authorization for public redistribution"):
        if phrase not in notice_text:
            raise PipelineError("Clarke visible notice lost a source or rights qualification: " + phrase)
    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(), "source_sha256": sha(SOURCE_NOTE),
              "notice_path": NOTICE.relative_to(ROOT).as_posix(), "notice_sha256": sha(NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "adam-clarke-private-offline-20261004-v1",
                 "items": [{"item_id": WID, "category": "commentary",
                            "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if len(shown) != 1 or notice_text.rstrip() not in shown[0]:
        raise PipelineError("Clarke complete source and rights notice is not visible")

    bindings = build_bindings(installed, manifest)
    preflight = read(PREFLIGHT)
    if (preflight.get("status") != "pass" or preflight.get("work_id") != WID
            or preflight.get("input_bindings") != bindings
            or preflight.get("installed_file_count") != 33
            or preflight.get("source_authority_count") != 864):
        raise PipelineError("Clarke pre-gate finite first-party closure differs")
    check(bindings)
    save(LOG / "selection.json", selection)
    save(LOG / "preflight-input-bindings.json", PREFLIGHT.read_bytes())
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "source-inventory.json", {"status": "pass", "retained_members": 856,
         "bound_source_authorities": 864, "installed_files": 33,
         "saved_actual_master_rows": 57, "saved_actual_master_text_characters": 13583400,
         "source_manifest_sha256": MANIFEST_SHA, "source_note_sha256": SOURCE_NOTE_SHA,
         "visible_notice_sha256": NOTICE_SHA, "prior_release_selections": [],
         "human_acceptance": "not-recorded", "rights_clearance": "unresolved",
         "public_publication": "not-performed"})

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
            or assembly["items"][0]["row_count"] != 57):
        raise PipelineError("Clarke assembly item accounting differs")
    stats = read(LOG / "statistics.json")["total"]
    if stats["records"] != 57 or stats["text_characters"] != 13583400:
        raise PipelineError("Released Clarke row/text counts differ")
    receipt = destination / "internal/projection-receipts/adam-clarke.json"
    rows_path = destination / "public/data/commentary/train.jsonl"
    if read(receipt)["mapping_version"] != "ocd-commentary-accepted-source-native-v1":
        raise PipelineError("Released Clarke source-native mapping receipt differs")
    rows = 0
    with io_path(rows_path).open("r", encoding="utf-8") as stream:
        for line in stream:
            rows += 1
            if PRIVATE_PATTERN.search(line) or PRIVATE_PATTERN.search(unquote(line)):
                raise PipelineError(f"Clarke public row exposes private source binding at {rows}")
    if rows != 57 or notice_text.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
        raise PipelineError("Clarke public row count or complete visible notice differs")
    check(bindings)
    require_loaded_first_party_bound(bindings)
    if _files(WORK) != installed:
        raise PipelineError("Clarke original 33 installed files changed during release")
    release_files = _files(destination)
    if set(release_files) != EXPECTED_RELEASE_FILES:
        raise PipelineError("Clarke seven-file private release differs")

    completion = {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "work_id": WID, "edition_id": "adam-clarke-retained-electronic",
                  "rows": 57, "text_characters": stats["text_characters"],
                  "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": ACCEPTANCE_SHA,
                  "installed_work_files": 33, "source_manifest_sha256": MANIFEST_SHA,
                  "saved_install_audit_sha256": INSTALL_AUDIT_SHA,
                  "saved_projection_proof_sha256": PROJECTION_PROOF_SHA,
                  "preflight_input_bindings_sha256": sha(LOG / "preflight-input-bindings.json"),
                  "selected_source_notice_sha256": SOURCE_NOTE_SHA,
                  "visible_data_notice_sha256": NOTICE_SHA,
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
        "# Adam Clarke commentary: private offline release\n\n"
        "The unchanged accepted HelloAO electronic witness passes current source-native projection, "
        "independent release verification, statistics, and both offline readers: 57 book rows. "
        "The public dataset card carries the complete source and rights notice. Nine books are absent; "
        "127 chapters contain only an introduction, both 2 Samuel 14:27 occurrences remain, and the "
        "retained 2 John 1:9 wording is `hath not God`. This does not establish 66-book or printed-edition completeness.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this private release. "
        "Human textual review, printed-edition collation, electronic rights clearance, and public publication "
        "remain separate.\n").encode("utf-8"))
    expected_work = {**installed, **{"publication/" + name: sha(WORK / "publication" / name)
                                   for name in ("completion.json", "selection.json", "README.md")}}
    check(bindings)
    if _files(WORK) != expected_work or _files(destination) != release_files:
        raise PipelineError("Final Clarke publication pointers or release files differ")
    save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
         "canonical_files": expected_work, "release_files": release_files,
         "rows": 57, "text_characters": stats["text_characters"],
         "public_rows_sha256": sha(rows_path), "projection_receipt_sha256": sha(receipt),
         "publication_performed": False,
         "completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
         "selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json")})
    return completion


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "rows": result["rows"],
                      "text_characters": result["text_characters"]}, sort_keys=True))
