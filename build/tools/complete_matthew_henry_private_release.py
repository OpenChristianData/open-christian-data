"""Complete the accepted retained Matthew Henry cohort as a private offline release."""

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
WID = "matthew-henry-complete"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/matthew-henry-complete-retained-en/editions/matthew-henry-complete-retained-electronic"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
MANIFEST = WORK / "integration/helloao-retained-v1/source-manifest-current-v1.json"
JOURNAL = ROOT / "reports/_logs/henry-audit-install-20261004-v1/operation.json"
SOURCE_NOTE = ROOT / "sources/commentaries/matthew-henry-complete/README.source.md"
NOTICE = ROOT / "data/commentaries/matthew-henry-complete/README.md"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
LOG = ROOT / "reports/_logs/matthew-henry-complete-private-release-20261004-v1"
MASTER_SHA = "e31aeda60be13fc7db0a1463c43688fed9a8098e262aa0fc9195735137d70abe"
ACCEPTANCE_SHA = "eed77cb270520e64dab7b2ec083eaa6e132f6ee261d159a7bd08696a6c341859"
MANIFEST_SHA = "24c211072c0979b3754da54a46cc3f9e3167835594761f53e0f6c0a75d66f8d0"


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
        raise PipelineError("Fresh Henry private release destination required")
    if (sha(MASTER), sha(ACCEPTANCE), sha(MANIFEST)) != (MASTER_SHA, ACCEPTANCE_SHA, MANIFEST_SHA):
        raise PipelineError("Accepted Henry master, decision, or source manifest changed")
    installed, journal, manifest = _files(WORK), read(JOURNAL), read(MANIFEST)
    if (len(installed) != 34 or journal["phase"] != "complete" or journal["work_id"] != WID
            or journal["after"] != installed or len(manifest["authorities"]) != 1175
            or read(INDEX)["by_work"].get(WID, [])):
        raise PipelineError("Henry installation or prior release selection differs")
    notice_text = NOTICE.read_text(encoding="utf-8")
    for phrase in ("HelloAO Bible API", "Public Domain Mark 1.0", "CC0", "65 of the usual 66",
                   "Song of Solomon", "Matthew chapters 19–28", "Jonah chapters 2–4",
                   "Isaiah chapter 67", "Rights in this particular electronic transcription"):
        if phrase not in notice_text:
            raise PipelineError("Henry visible source or rights notice differs: " + phrase)
    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(), "source_sha256": sha(SOURCE_NOTE),
              "notice_path": NOTICE.relative_to(ROOT).as_posix(), "notice_sha256": sha(NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "matthew-henry-complete-private-offline-20261004-v1",
                 "items": [{"item_id": WID, "category": "commentary",
                            "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if len(shown) != 1 or notice_text.rstrip() not in shown[0]:
        raise PipelineError("Henry source and rights notice is not visible in release selection")

    bindings = {(Path("library/works") / WID / name).as_posix(): digest
                for name, digest in installed.items()}
    sources = {}
    for member in manifest["authorities"]:
        path = ROOT / member["path"]
        if sha(path) != member["sha256"] or io_path(path).stat().st_size != member["bytes"]:
            raise PipelineError("Retained Henry source authority changed: " + member["path"])
        if member["path"] in sources and sources[member["path"]] != member["sha256"]:
            raise PipelineError("Conflicting retained Henry source authority: " + member["path"])
        sources[member["path"]] = member["sha256"]
    if len(sources) != 1175:
        raise PipelineError("Henry source authority membership differs")
    bindings.update(sources)
    inputs = [MANIFEST, JOURNAL, SOURCE_NOTE, NOTICE, INDEX, Path(__file__),
              ROOT / "ocd_kernel/__init__.py", ROOT / "build/tools/complete_puritan_private_release.py",
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
    save(LOG / "source-inventory.json", {"status": "pass", "retained_json_members": 1169,
         "source_authority_entries": len(sources), "installed_files": len(installed),
         "source_manifest_sha256": MANIFEST_SHA, "visible_data_notice_sha256": sha(NOTICE),
         "selected_source_notice_sha256": sha(SOURCE_NOTE), "prior_release_selections": [],
         "human_acceptance": "not-recorded", "rights_clearance": "unresolved",
         "public_publication": "not-performed"})

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
    receipt = destination / "internal/projection-receipts/matthew-henry-complete.json"
    public_rows = destination / "public/data/commentary/train.jsonl"
    assembly = read(LOG / "assembly.json")
    if (len(assembly["items"]) != 1 or assembly["items"][0]["item_id"] != WID
            or assembly["items"][0]["status"] not in {"included", "warned"}
            or assembly["items"][0]["row_count"] != 65):
        raise PipelineError("Henry assembly item accounting differs")
    stats = read(LOG / "statistics.json")["total"]
    if stats["records"] != 65 or stats["text_characters"] != 32720180:
        raise PipelineError("Released Henry row/text counts differ")
    with public_rows.open("rb") as stream:
        for line in stream:
            visible = line.decode("utf-8")
            if any(re.search(r"(?i)[0-9a-f]{64}|raw/helloao_local|master\.tei\.xml", text)
                   for text in (visible, unquote(visible))):
                raise PipelineError("Released Henry rows expose private source bindings")
    card = (destination / "public/README.md").read_text(encoding="utf-8")
    if notice_text.rstrip() not in card:
        raise PipelineError("Released Henry card omits source rights and coverage notice")
    check(bindings)
    unbound_loaded = {path.relative_to(ROOT).as_posix() for path in loaded_kernel_paths()} - set(bindings)
    if unbound_loaded or _files(WORK) != installed:
        raise PipelineError("Henry runtime or installed work drifted: " + str(sorted(unbound_loaded)))
    files = _files(destination)
    if len(files) != 7:
        raise PipelineError("Expected seven Henry release files")
    completion = {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "work_id": WID, "rows": 65, "text_characters": stats["text_characters"],
                  "accepted_master_sha256": MASTER_SHA, "acceptance_sha256": ACCEPTANCE_SHA,
                  "selected_source_notice_path": SOURCE_NOTE.relative_to(ROOT).as_posix(),
                  "selected_source_notice_sha256": sha(SOURCE_NOTE),
                  "visible_data_notice_path": NOTICE.relative_to(ROOT).as_posix(),
                  "visible_data_notice_sha256": sha(NOTICE), "input_bindings": bindings,
                  "preserved_work_files": installed, "release_file_bindings": files, "gates": gates,
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
        "# Matthew Henry: private offline release\n\n"
        "The accepted partial HelloAO electronic witness passes current source-native projection, "
        "independent output verification, statistics, and both offline readers: 65 book rows. "
        "The public dataset card carries source credit, rights qualifiers, and coverage gaps.\n\n"
        "[Completion](completion.json) and [selection](selection.json) bind this private release. "
        "Human review, print collation, rights clearance, and public publication remain separate.\n").encode())
    expected = {**installed, **{"publication/" + name: sha(WORK / "publication" / name)
                                  for name in ("completion.json", "selection.json", "README.md")}}
    check(bindings)
    if _files(WORK) != expected or _files(destination) != files:
        raise PipelineError("Final Henry publication pointers or release files differ")
    save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
         "canonical_files": expected, "release_files": files, "rows": 65,
         "text_characters": stats["text_characters"], "public_rows_sha256": sha(public_rows),
         "projection_receipt_sha256": sha(receipt), "publication_performed": False,
         "completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
         "selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json")})
    return completion


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "rows": result["rows"],
                      "text_characters": result["text_characters"]}, sort_keys=True))
