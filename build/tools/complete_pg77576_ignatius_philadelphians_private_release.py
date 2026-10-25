"""Private offline release of the unchanged accepted Ignatius to Philadelphians."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree, html

from build.tools.check_release_reader import check_reader
from build.tools.complete_puritan_private_release import check, read, save, sha
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import cached_edition_lookups
import ocd_kernel.projection.categories.native_documents as native_documents
import ocd_kernel.projection.categories.prose as prose
import ocd_kernel.projection.native_content as native_content
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.install_accepted import _files


ROOT = Path(__file__).resolve().parents[2]
WID = "pg77576-ignatius-philadelphians"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/pg77576-ignatius-philadelphians-english/editions/pg77576-ignatius-philadelphians-pg77576-edition"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
SOURCE = ROOT / "raw/gutenberg/77576/html/pg77576-images.html"
PROFILE = WORK / "integration/pg77576-html-v1/profile.json"
JOURNAL = ROOT / ".tmp_audit/accepted-install-f877eba3dabc4d92/operation.json"
SOURCE_NOTE = ROOT / "sources/gutenberg" / WID / "README.source.md"
NOTICE = ROOT / "data/structured-text" / WID / "README.md"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
LOG = ROOT / "reports/_logs/pg77576-ignatius-philadelphians-private-release-20261003-v1"
MASTER_SHA = "84bcaf39498b983d170364c977b87dd73598ba9d5480137c6b3f3ca557eb19fb"
ACCEPTANCE_SHA = "6f04192fa2dfcb03c95f94835625bb613e029c64fec5f78eacf6f4bb828b7ddd"
SOURCE_SHA = "ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507"
LICENSE_SHA = "9df13869f294cf8b9625debae7b80846b71ebd015287cc3971435f98f0cae046"


def run() -> dict:
    if LOG.exists() or (WORK / "publication").exists():
        raise PipelineError("Fresh Philadelphians private release destination required")
    if (sha(MASTER), sha(ACCEPTANCE), sha(SOURCE)) != (MASTER_SHA, ACCEPTANCE_SHA, SOURCE_SHA):
        raise PipelineError("Accepted Philadelphians or source authority changed")
    installed, journal = _files(WORK), read(JOURNAL)
    if (len(installed) != 75 or journal["phase"] != "complete" or journal["work_id"] != WID
            or journal["after"] != installed or read(INDEX)["by_work"].get(WID, [])):
        raise PipelineError("Installed Philadelphians files or earlier release differ")
    profile = read(PROFILE)
    if (profile["work_id"] != WID or profile["source_sha256"] != SOURCE_SHA
            or profile["body_intervals"] != [[669, 729]] or profile["shared_context_children"] != []
            or profile["note_ids"] != [f"f{n}" for n in range(1139, 1230)]
            or len(profile["pages"]) != 11):
        raise PipelineError("Philadelphians source selection differs")
    tei = etree.parse(str(MASTER))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    footnotes = tei.xpath('//t:text//t:div[@type="source-footnotes"]', namespaces=ns)
    references = tei.xpath('//t:text//t:ref', namespaces=ns)
    ids = [child.get(xml_id) for child in footnotes[0]] if len(footnotes) == 1 else []
    targets = [ref.get("target") for ref in references]
    if (ids != profile["note_ids"] or len(references) != 273 or targets.count(None) != 91
            or sum(isinstance(x, str) and x.startswith("#f") for x in targets) != 91
            or sum(isinstance(x, str) and x.startswith("#r") for x in targets) != 91):
        raise PipelineError("Philadelphians note/reference attachments differ")

    source_tree = html.fromstring(SOURCE.read_bytes())
    headings = source_tree.xpath('//h2[@id="pg-footer-heading"]')
    if len(headings) != 1:
        raise PipelineError("Retained PG77576 license heading differs")
    license_text = "\n\n".join(etree.tostring(node, method="text", encoding="unicode").strip()
                             for node in [headings[0], *headings[0].itersiblings()]).replace("\r\n", "\n")
    notice_text = NOTICE.read_text(encoding="utf-8")
    if (len(license_text) != 17072 or sha256(license_text.encode()).hexdigest() != LICENSE_SHA
            or license_text not in notice_text or not notice_text.endswith(license_text + "\n```\n")):
        raise PipelineError("Visible Philadelphians notice omits exact full license")
    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(), "source_sha256": sha(SOURCE_NOTE),
              "notice_path": NOTICE.relative_to(ROOT).as_posix(), "notice_sha256": sha(NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "pg77576-ignatius-philadelphians-private-offline-20261003-v1",
                 "items": [{"item_id": WID, "category": "prose", "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if len(shown) != 1 or license_text not in shown[0] or "Roberts and Donaldson" not in shown[0]:
        raise PipelineError("Source-bound visible Philadelphians attribution differs")

    original_io = prose.io_path
    canonical = {str(ROOT), str(ACCEPTANCE)}
    def equivalent_path(path: Path) -> Path:
        ordinary = str(path).removeprefix("\\\\?\\")
        return Path(ordinary) if ordinary in canonical else original_io(path)
    outside = ROOT.parent / "EzraOCR" / "AGENTS.md"
    if equivalent_path(outside) != original_io(outside):
        raise PipelineError("Equivalent-path adapter changed an outside path")
    prose.io_path = equivalent_path
    try:
        with cached_edition_lookups():
            print("actual-master-projection: START", flush=True)
            projected = prose.project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
            prior_prose, prior_native, prior_content = (prose.project_accepted_prose,
                native_documents.project_accepted_document, native_content.project_content)
            def unavailable(*args, **kwargs):
                raise AssertionError("Independent checker invoked a producer")
            try:
                prose.project_accepted_prose = unavailable
                native_documents.project_accepted_document = unavailable
                native_content.project_content = unavailable
                errors = prose.verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                    rows=projected["rows"], receipt=projected["receipt"])
            finally:
                prose.project_accepted_prose, native_documents.project_accepted_document = prior_prose, prior_native
                native_content.project_content = prior_content
        rows = projected["rows"]
        characters = sum(len(row["text"]) for row in rows)
        public_rows = json.dumps(rows, ensure_ascii=False)
        if (errors or len(rows) != 2 or characters != 30096 or projected["receipt"]["master_sha256"] != MASTER_SHA
                or [sha256(row["text"].encode()).hexdigest() for row in rows] != [
                    "564381fa9d4e3e3a6958618ec15c4c653b39420a38daba723f17aa458f701d3d",
                    "7f1ff75d4e23a6d55e125f45bda9b62b9c032af67b72bb73fde36c732f51bb8f"]
                or [len(row["source_references"]) for row in rows] != [182, 91]
                or "raw/" in public_rows or re.search(r"(?i)[0-9a-f]{64}", public_rows)):
            raise PipelineError("Philadelphians actual-master projection/checker/privacy differs: " + str(errors))
        print("actual-master-projection: PASS", flush=True)

        bindings = {(Path("library/works") / WID / path).as_posix(): digest for path, digest in installed.items()}
        inputs = [JOURNAL, SOURCE, ROOT / "raw/gutenberg/77576/pg77576-h.zip",
                  ROOT / "raw/gutenberg/77576/acquisition-receipt.json", PROFILE, SOURCE_NOTE, NOTICE,
                  INDEX, Path(__file__), ROOT / "build/tools/complete_puritan_private_release.py",
                  ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py",
                  ROOT / "build/scripts/export_huggingface.py", ROOT / "build/tools/check_hf_release.py"]
        inputs.extend(ROOT / "ocd_kernel/projection" / name for name in (
            "categories/prose.py", "categories/sermons.py", "categories/native_documents.py",
            "envelope.py", "native_content.py", "native_content_check.py", "source_projection_evidence.py",
            "receipt.py", "scripture_authority.py", "scripture_targets.py", "scripture_targets_check.py"))
        for folder in ("ocd_kernel/release", "ocd_kernel/library", "ocd_kernel/tei"):
            inputs.extend((ROOT / folder).rglob("*.py"))
        inputs.extend((ROOT / "schemas/v2").rglob("*.json"))
        bindings.update({path.relative_to(ROOT).as_posix(): sha(path) for path in inputs})
        check(bindings)
        save(LOG / "selection.json", selection)
        save(LOG / "input-bindings-before.json", bindings)
        save(LOG / "actual-master-projection.json", projected)
        save(LOG / "independent-projection.json", {"status": "pass", "errors": errors,
            "producer_disabled": True, "rows": 2, "text_characters": characters,
            "master_sha256": MASTER_SHA, "saved_projection_sha256": sha(LOG / "actual-master-projection.json")})
        save(LOG / "source-structure.json", {"status": "pass", "body_intervals": profile["body_intervals"],
            "shared_context_children": [], "ordered_endnote_ids": ids,
            "ordered_page_ids": profile["pages"], "source_references": 273,
            "targetless_references": 91, "footnote_targets": 91, "backlink_targets": 91,
            "full_license_characters": len(license_text), "full_license_sha256": LICENSE_SHA,
            "visible_notice_sha256": sha(NOTICE)})
        del projected, rows

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
        total = read(LOG / "statistics.json")["total"]
        public_jsonl = (destination / "public/data/prose/train.jsonl").read_text(encoding="utf-8")
        if (total["records"] != 2 or total["text_characters"] != characters
                or "raw/" in public_jsonl or re.search(r"(?i)[0-9a-f]{64}", public_jsonl)):
            raise PipelineError("Released Philadelphians counts/privacy differ")
        if notice_text.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
            raise PipelineError("Release card omits full visible source notice")
        check(bindings)
        if _files(WORK) != installed:
            raise PipelineError("Installed Philadelphians changed during release")
        files = _files(destination)
        completion = {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
            "work_id": WID, "rows": 2, "text_characters": characters, "accepted_master_sha256": MASTER_SHA,
            "acceptance_sha256": ACCEPTANCE_SHA, "input_bindings": bindings,
            "preserved_work_files": installed, "release_file_bindings": files, "gates": gates,
            "selection_path": (LOG / "selection.json").relative_to(ROOT).as_posix(),
            "selection_sha256": sha(LOG / "selection.json"), "release_path": str(destination.resolve()),
            "private_offline": True, "publication_performed": False, "human_acceptance": "not-recorded",
            "print_collation": "not-performed", "rights_clearance": "unresolved",
            "final_public_release_selection": "unresolved", "reconstruction_performed": False,
            "reinstall_performed": False}
        save(LOG / "completion.json", completion)
        save(WORK / "publication/completion.json", (LOG / "completion.json").read_bytes())
        save(WORK / "publication/selection.json", (LOG / "selection.json").read_bytes())
        save(WORK / "publication/README.md", (
            "# The Epistle of Ignatius to the Philadelphians: private offline release\n\n"
            f"The unchanged accepted electronic witness passes actual-master prose projection, "
            f"independent checking, private assembly, release verification, statistics, and both "
            f"offline readers: 2 rows and {characters:,} text characters. The public dataset card "
            "carries source credit and the complete retained Project Gutenberg License.\n\n"
            "[Completion](completion.json) and [selection](selection.json) bind this release. "
            "Human acceptance, print collation, rights clearance, and public publication remain separate.\n"
        ).encode("utf-8"))
        expected = dict(installed)
        expected.update({"publication/" + name: sha(WORK / "publication" / name)
            for name in ("completion.json", "selection.json", "README.md")})
        if _files(WORK) != expected or _files(destination) != files:
            raise PipelineError("Final Philadelphians delivery differs")
        check(bindings)
        save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
            "canonical_files": expected, "release_file_count": len(files),
            "canonical_completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
            "canonical_selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json"),
            "rows": 2, "text_characters": characters, "publication_performed": False})
        return completion
    finally:
        prose.io_path = original_io


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "work_id": result["work_id"],
                      "rows": result["rows"], "text_characters": result["text_characters"],
                      "release_files": len(result["release_file_bindings"])}, sort_keys=True))
