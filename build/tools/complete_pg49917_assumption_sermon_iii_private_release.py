"""Complete the installed PG49917 Assumption Sermon III as a private offline release."""

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
WID = "pg49917-assumption-sermon-iii"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/pg49917-assumption-sermon-iii-english/editions/pg49917-assumption-sermon-iii-pg49917-edition"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
SOURCE = ROOT / "raw/gutenberg/49917/html/pg49917-images.html"
PROFILE = WORK / "integration/pg49917-html-v1/profile.json"
JOURNAL = ROOT / ".tmp_audit/accepted-install-b537860d973c420c/operation.json"
SOURCE_NOTE = ROOT / "sources/gutenberg" / WID / "README.source.md"
NOTICE = ROOT / "data/structured-text" / WID / "README.md"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
LOG = ROOT / "reports/_logs/pg49917-assumption-sermon-iii-private-release-20261003-v1"
MASTER_SHA = "c9c18fcd3e9fe550a691b303506dc925c63ec81f7c340c6faabca05333206d2b"
ACCEPTANCE_SHA = "61c5d7fb81605c86c9f2c63ca461bf411383e25737a337018c718b43120f7df6"
SOURCE_SHA = "a517174360b8c13609b74c005965f1386e6a0cc0f97fd795d248ccb496944204"
LICENSE_SHA = "9df13869f294cf8b9625debae7b80846b71ebd015287cc3971435f98f0cae046"
TEXT_SHA = "705f843ed9ee21e97062efde6cc0c8a5caf8cadcd42747b1f61685a79d0409ff"


def run() -> dict:
    if LOG.exists() or (WORK / "publication").exists():
        raise PipelineError("Fresh Sermon III private release destination required")
    if (sha(MASTER), sha(ACCEPTANCE), sha(SOURCE)) != (MASTER_SHA, ACCEPTANCE_SHA, SOURCE_SHA):
        raise PipelineError("Sermon III accepted/source authority changed")
    installed = _files(WORK)
    journal = read(JOURNAL)
    if (journal["phase"] != "complete" or journal["work_id"] != WID
            or len(installed) != 49 or installed != journal["after"]):
        raise PipelineError("Sermon III installed files differ from completed journal")
    if read(INDEX)["by_work"].get(WID, []):
        raise PipelineError("Earlier Sermon III selection requires reconciliation")

    tree = html.fromstring(SOURCE.read_bytes())
    headings = tree.xpath('//h2[@id="pg-footer-heading"]')
    if len(headings) != 1:
        raise PipelineError("Retained PG49917 license heading differs")
    license_text = "\n\n".join(etree.tostring(node, method="text", encoding="unicode").strip()
                             for node in [headings[0], *headings[0].itersiblings()]).replace("\r\n", "\n")
    notice_text = NOTICE.read_text(encoding="utf-8")
    if (len(license_text) != 17072 or sha256(license_text.encode()).hexdigest() != LICENSE_SHA
            or not notice_text.endswith(license_text + "\n```\n")):
        raise PipelineError("Visible Sermon III notice omits exact full retained license")
    profile = read(PROFILE)
    if (profile["body_intervals"] != [[24, 25]] or profile["source_sha256"] != SOURCE_SHA
            or profile["note_ids"] != []
            or profile["pages"] != [f"page-{number}" for number in range(201, 212)]
            or profile["sermon_id"] != "sermon-iii-nl-on-the-assumption"):
        raise PipelineError("Sermon III source profile differs")
    master = etree.parse(str(MASTER))
    for item_id in [profile["sermon_id"], *profile["pages"]]:
        if len(master.xpath('//*[@xml:id=$id]', id=item_id,
                            namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})) != 1:
            raise PipelineError("Sermon III source attachment differs: " + item_id)
    if any("comment-digest:" in value or "presentation-style-omitted-sha256:" in value
           or "urn:ocd:pg49917:source-marker:" in value
           for node in master.iter() for value in node.attrib.values()):
        raise PipelineError("Sermon III unexpectedly needs private source-marker aliases")

    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(), "source_sha256": sha(SOURCE_NOTE),
              "notice_path": NOTICE.relative_to(ROOT).as_posix(), "notice_sha256": sha(NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "pg49917-assumption-sermon-iii-private-offline-20261003-v1",
                 "items": [{"item_id": WID, "category": "prose", "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if (len(shown) != 1 or license_text not in shown[0] or "Mary H. Allies" not in shown[0]
            or "page markers 201–211" not in shown[0] or "no linked source notes" not in shown[0]):
        raise PipelineError("Source-bound Sermon III notice differs")

    original_io = prose.io_path
    canonical = {str(ROOT), str(ACCEPTANCE)}
    def equivalent_authority_path(path: Path) -> Path:
        ordinary = str(path).removeprefix("\\\\?\\")
        return Path(ordinary) if ordinary in canonical else original_io(path)
    outside = ROOT.parent / "EzraOCR" / "AGENTS.md"
    if equivalent_authority_path(outside) != original_io(outside):
        raise PipelineError("Sermon III adapter changed an outside path")
    prose.io_path = equivalent_authority_path
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
                prose.project_accepted_prose = prior_prose
                native_documents.project_accepted_document = prior_native
                native_content.project_content = prior_content
        rows = projected["rows"]
        characters = sum(len(row["text"]) for row in rows)
        if (errors or len(rows) != 1 or characters != 11668 or projected["receipt"]["master_sha256"] != MASTER_SHA
                or sha256(rows[0]["text"].encode()).hexdigest() != TEXT_SHA
                or re.search(r"(?i)[0-9a-f]{64}", json.dumps(rows, ensure_ascii=False))):
            raise PipelineError("Sermon III actual-master projection/checker/privacy differs: " + str(errors))
        print("actual-master-projection: PASS", flush=True)

        bindings = {(Path("library/works") / WID / path).as_posix(): digest for path, digest in installed.items()}
        inputs = [JOURNAL, SOURCE, ROOT / "raw/gutenberg/49917/pg49917-h.zip",
                  ROOT / "raw/gutenberg/49917/acquisition-receipt.json", PROFILE, SOURCE_NOTE, NOTICE,
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
            "producer_disabled": True, "rows": 1, "text_characters": characters,
            "master_sha256": MASTER_SHA, "saved_projection_sha256": sha(LOG / "actual-master-projection.json")})
        save(LOG / "source-structure.json", {"status": "pass", "sermon_id": profile["sermon_id"],
            "ordered_linked_note_ids": [], "ordered_page_ids": profile["pages"],
            "private_source_marker_count": 0, "full_license_characters": len(license_text),
            "full_license_sha256": LICENSE_SHA, "visible_notice_sha256": sha(NOTICE)})
        save(LOG / "prior-attempt.json", {"status": "failed-before-release-log-or-publication",
            "failure": "The first runner invocation checked for 'pages 201–211'; the exact visible notice says 'page markers 201–211'.",
            "authority_or_gate_failure": False})
        del projected, rows

        destination = LOG / "release"
        gates = {}
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
        if (total["records"] != 1 or total["text_characters"] != characters
                or re.search(r"(?i)[0-9a-f]{64}", public_jsonl)):
            raise PipelineError("Released Sermon III counts/privacy differ")
        if notice_text.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
            raise PipelineError("Release card omits complete visible Sermon III notice")
        check(bindings)
        if _files(WORK) != installed:
            raise PipelineError("Installed Sermon III authority changed during release")
        files = _files(destination)
        completion = {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
            "work_id": WID, "rows": 1, "text_characters": characters, "accepted_master_sha256": MASTER_SHA,
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
            "# Sermon III. On the Assumption: private offline release\n\n"
            f"The unchanged accepted electronic witness passes actual-master prose projection, "
            f"independent checking, private assembly, release verification, statistics, and both "
            f"offline readers: 1 row and {characters:,} text characters. The public dataset card "
            "carries source credit and the complete retained Project Gutenberg License.\n\n"
            "[Completion](completion.json) and [selection](selection.json) bind this release. "
            "Human acceptance, print collation, rights clearance, and public publication remain separate.\n"
        ).encode("utf-8"))
        expected = dict(installed)
        expected.update({"publication/" + name: sha(WORK / "publication" / name)
            for name in ("completion.json", "selection.json", "README.md")})
        if _files(WORK) != expected or _files(destination) != files:
            raise PipelineError("Final Sermon III delivery envelope differs")
        check(bindings)
        save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
            "canonical_files": expected, "release_file_count": len(files),
            "canonical_completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
            "canonical_selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json"),
            "rows": 1, "text_characters": characters, "publication_performed": False})
        return completion
    finally:
        prose.io_path = original_io


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "work_id": result["work_id"],
                      "rows": result["rows"], "text_characters": result["text_characters"],
                      "release_files": len(result["release_file_bindings"])}, sort_keys=True))
