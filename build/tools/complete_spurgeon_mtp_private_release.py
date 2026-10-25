"""Complete the accepted MTP electronic cohort as a private offline release."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
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
WID = "spurgeon-mtp"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/spurgeon-mtp-retained-en/editions/spurgeon-mtp-retained-electronic"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
SOURCE_NOTE = ROOT / "sources/sermons/spurgeon-mtp/README.source.md"
NOTICE = ROOT / "data/sermons/spurgeon-mtp/README.md"
MANIFEST = ROOT / "sources/spurgeon-mtp/spurgeon-mtp.source-manifest.install-20261003-v1.json"
JOURNAL = ROOT / "reports/_logs/spurgeon-mtp-retained-install-20261003-v1/canonical-complete-operation.json"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
LOG = ROOT / "reports/_logs/spurgeon-mtp-private-release-20261003-v1"
MASTER_SHA = "e1db04c2728cddacd9ce6fa675ebb329fe931e4c79659d754b6de6df7be2addc"
ACCEPTANCE_SHA = "ccd6e97e6503d03103f44c71eb5456cb5974eabba699e670057e170ce03decf8"
MANIFEST_SHA = "9259f5d0688556dd4cc73e21c7e22fd5114416cd80202a0cb9c0ba3ccecb54ce"
SOURCE_NOTE_SHA = "e51b4ae643e4632b876986fd301cffa46c47d8709b73c3baae40c603c0c5ed0e"


def loaded_kernel_paths() -> set[Path]:
    paths = set()
    for module in sys.modules.values():
        file = getattr(module, "__file__", None)
        if file:
            path = Path(file).resolve()
            if path.suffix == ".py" and path.is_relative_to(ROOT / "ocd_kernel"):
                paths.add(path)
    return paths


def run() -> dict:
    if io_path(LOG).exists() or (WORK / "publication").exists():
        raise PipelineError("Fresh MTP private release destination required")
    if (sha(MASTER), sha(ACCEPTANCE), sha(MANIFEST), sha(SOURCE_NOTE)) != (
            MASTER_SHA, ACCEPTANCE_SHA, MANIFEST_SHA, SOURCE_NOTE_SHA):
        raise PipelineError("Accepted MTP or retained source authority changed")
    installed, journal, manifest = _files(WORK), read(JOURNAL), read(MANIFEST)
    if (len(installed) != 37 or journal["phase"] != "complete" or journal["work_id"] != WID
            or journal["after"] != installed or len(manifest["source_members"]) != 3550
            or len(manifest["authorities"]) != 3567
            or read(INDEX)["by_work"].get(WID, [])):
        raise PipelineError("MTP installation or prior release selection differs")
    notice_text = NOTICE.read_text(encoding="utf-8")
    if ("3,550" not in notice_text or "thirteen numbered slots" not in notice_text
            or "Emmett O'Donnell" not in notice_text or "Benry Yip" not in notice_text
            or "Larry and Marion Pierce" not in notice_text or "express written permission" not in notice_text
            or "Rights in electronic transcription, digitization, and formatting remain unresolved" not in notice_text):
        raise PipelineError("Visible MTP source and rights notice differs")
    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(), "source_sha256": sha(SOURCE_NOTE),
              "notice_path": NOTICE.relative_to(ROOT).as_posix(), "notice_sha256": sha(NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "spurgeon-mtp-private-offline-20261003-v1",
                 "items": [{"item_id": WID, "category": "sermons",
                            "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if len(shown) != 1 or notice_text.rstrip() not in shown[0]:
        raise PipelineError("MTP rights notice is not visible in the release selection")

    bindings = {(Path("library/works") / WID / name).as_posix(): digest
                for name, digest in installed.items()}
    for category_module in ("commentary_group_policy", "lib040_augustine_selected",
                            "native_documents", "prose", "sermons"):
        importlib.import_module("ocd_kernel.projection.categories." + category_module)
    sources = {}
    for member in manifest["authorities"]:
        path = ROOT / member["path"]
        if sha(path) != member["sha256"] or io_path(path).stat().st_size != member["bytes"]:
            raise PipelineError("Retained MTP source member changed: " + member["path"])
        if member["path"] in sources and sources[member["path"]] != member["sha256"]:
            raise PipelineError("Conflicting retained MTP source authority: " + member["path"])
        sources[member["path"]] = member["sha256"]
    if len(sources) != 3566 or not {m["path"] for m in manifest["source_members"]} <= set(sources):
        raise PipelineError("MTP retained source authority paths omit members")
    bindings.update(sources)
    inputs = [MANIFEST, JOURNAL, SOURCE_NOTE, NOTICE, INDEX, Path(__file__),
              ROOT / "ocd_kernel/__init__.py",
              ROOT / "build/tools/complete_puritan_private_release.py",
              ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py",
              ROOT / "build/scripts/export_huggingface.py", ROOT / "build/tools/check_hf_release.py"]
    inputs.extend(loaded_kernel_paths())
    for folder in ("ocd_kernel/projection", "ocd_kernel/lib", "ocd_kernel/release",
                   "ocd_kernel/library", "ocd_kernel/tei"):
        inputs.extend((ROOT / folder).rglob("*.py"))
    inputs.extend((ROOT / "schemas/v2").rglob("*.json"))
    bindings.update({path.relative_to(ROOT).as_posix(): sha(path) for path in inputs})
    check(bindings)
    save(LOG / "selection.json", selection)
    save(LOG / "input-bindings-before.json", bindings)
    save(LOG / "source-inventory.json", {"status": "pass", "retained_members": 3550,
         "source_authority_entries": 3567, "bound_unique_source_authorities": len(sources),
         "shared_profile_path_has_two_source_roles": True,
         "source_manifest_sha256": MANIFEST_SHA, "installed_files": len(installed),
         "installed_work_source_note_sha256": installed["README.source.md"],
         "selected_source_notice_sha256": sha(SOURCE_NOTE), "visible_data_notice_sha256": sha(NOTICE),
         "prior_release_selections": [], "human_acceptance": "not-recorded",
         "rights_clearance": "unresolved", "public_publication": "not-performed"})

    destination, gates = LOG / "release", {}
    with cached_edition_lookups():
        for name, operation in (("assembly", lambda: assemble_release_v2(ROOT, destination, selection=selection)),
                                ("independent-verification", lambda: verify_release_v2(ROOT, destination, selection=selection)),
                                ("statistics", lambda: release_statistics(ROOT, destination, selection)),
                                ("readers", lambda: check_reader(ROOT, destination, selection))):
            print(name + ": START", flush=True)
            result = operation()
            save(LOG / (name + ".json"), result)
            if result["status"] != "pass":
                raise PipelineError(name + " failed: " + json.dumps(result))
            gates[name] = sha(LOG / (name + ".json"))
            print(name + ": PASS", flush=True)
    receipt = destination / "internal/projection-receipts/spurgeon-mtp.json"
    public_rows = destination / "public/data/sermons/train.jsonl"
    assembly = read(LOG / "assembly.json")
    if (len(assembly["items"]) != 1 or assembly["items"][0]["item_id"] != WID
            or assembly["items"][0]["status"] not in {"included", "warned"}
            or assembly["items"][0]["row_count"] != 3550):
        raise PipelineError("MTP assembly item accounting differs")
    stats = read(LOG / "statistics.json")["total"]
    if stats["records"] != 3550 or stats["text_characters"] != 120714217:
        raise PipelineError("Released MTP row/text counts differ")
    with public_rows.open("rb") as stream:
        for line in stream:
            visible = line.decode("utf-8")
            if any(re.search(r"(?i)[0-9a-f]{64}|raw/spurgeon_sermons|master\.tei\.xml", text)
                   for text in (visible, unquote(visible))):
                raise PipelineError("Released MTP rows expose private source bindings")
    card = (destination / "public/README.md").read_text(encoding="utf-8")
    if notice_text.rstrip() not in card:
        raise PipelineError("Released MTP card omits visible source rights notice")
    if read(receipt)["mapping_version"] != "ocd-sermons-spurgeon-mtp-source-native-v1":
        raise PipelineError("Released MTP native mapping receipt differs")
    check(bindings)
    unbound_loaded = {path.relative_to(ROOT).as_posix() for path in loaded_kernel_paths()} - set(bindings)
    if unbound_loaded:
        raise PipelineError("Loaded MTP shared-kernel files lack input bindings: " + str(sorted(unbound_loaded)))
    if _files(WORK) != installed:
        raise PipelineError("Installed MTP work changed during release")
    files = _files(destination)
    if len(files) != 7:
        raise PipelineError("Expected seven MTP release files")
    completion = {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "work_id": WID, "rows": 3550, "text_characters": stats["text_characters"],
                  "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": ACCEPTANCE_SHA,
                  "installed_work_source_note_sha256": installed["README.source.md"],
                  "selected_source_notice_path": SOURCE_NOTE.relative_to(ROOT).as_posix(),
                  "selected_source_notice_sha256": sha(SOURCE_NOTE),
                  "visible_data_notice_path": NOTICE.relative_to(ROOT).as_posix(),
                  "visible_data_notice_sha256": sha(NOTICE),
                  "notice_provenance": "The new sources/sermons pointer satisfies the release notice contract; the installed work-level source note and 37-file journal remain unchanged.",
                  "input_bindings": bindings, "preserved_work_files": installed,
                  "release_file_bindings": files, "gates": gates,
                  "release_item_status": assembly["items"][0]["status"],
                  "release_item_reasons": assembly["items"][0]["reasons"],
                  "projection_receipt_sha256": sha(receipt), "public_rows_sha256": sha(public_rows),
                  "selection_path": (LOG / "selection.json").relative_to(ROOT).as_posix(),
                  "selection_sha256": sha(LOG / "selection.json"), "release_path": str(destination.resolve()),
                  "private_offline": True, "publication_performed": False,
                  "human_acceptance": "not-recorded", "print_collation": "not-performed",
                  "rights_clearance": "unresolved", "final_public_release_selection": "unresolved",
                  "reconstruction_performed": False, "reinstall_performed": False}
    save(LOG / "completion.json", completion)
    save(WORK / "publication/completion.json", (LOG / "completion.json").read_bytes())
    save(WORK / "publication/selection.json", (LOG / "selection.json").read_bytes())
    save(WORK / "publication/README.md", (
        "# Metropolitan Tabernacle Pulpit: private offline release\n\n"
        "The unchanged accepted retained electronic cohort passes current source-native projection, "
        "independent output verification, statistics, and both offline readers: 3,550 textual rows. "
        "The public dataset card carries the retained source credits and Modernized Edition terms. "
        "Thirteen numbered slots remain unresolved; 27 referenced image resources were not retained.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this private release. "
        "Human review, print collation, rights clearance, and public publication remain separate.\n").encode())
    expected = {**installed, **{"publication/" + name: sha(WORK / "publication" / name)
                                  for name in ("completion.json", "selection.json", "README.md")}}
    check(bindings)
    if _files(WORK) != expected or _files(destination) != files:
        raise PipelineError("Final MTP publication pointers or release files differ")
    save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
         "canonical_files": expected, "release_files": files, "rows": 3550,
         "text_characters": stats["text_characters"], "public_rows_sha256": sha(public_rows),
         "projection_receipt_sha256": sha(receipt), "publication_performed": False,
         "completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
         "selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json")})
    return completion


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "rows": result["rows"],
                      "text_characters": result["text_characters"]}, sort_keys=True))
