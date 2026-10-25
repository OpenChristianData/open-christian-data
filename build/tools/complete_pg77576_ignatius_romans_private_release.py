"""Release the installed Ignatius to Romans witness privately, without rebuilding it."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

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
WID = "pg77576-ignatius-romans"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/pg77576-ignatius-romans-english/editions/pg77576-ignatius-romans-pg77576-edition"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
SOURCE = ROOT / "raw/gutenberg/77576/html/pg77576-images.html"
PROFILE = WORK / "integration/pg77576-html-v1/profile.json"
JOURNAL = ROOT / ".tmp_audit/accepted-install-828c707b14db4d82/operation.json"
SOURCE_NOTE = ROOT / "sources/gutenberg" / WID / "README.source.md"
NOTICE = ROOT / "data/structured-text" / WID / "README.md"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
LOG = ROOT / "reports/_logs/pg77576-ignatius-romans-private-release-20261003-v2"
MASTER_SHA = "a7d4340952bda7986880426921d56a41c08bb0cd5d6822cac838d6d1b6163bd1"
ACCEPTANCE_SHA = "de8bd8f06f7069efc090c628add9f851e7eaf26e800f90c54545c9ab613b7b0c"
SOURCE_SHA = "ca58049f2ee7c62c8c34dffb6badfdb910ab698748f8decc9d9b978e7972e507"
LICENSE_SHA = "9df13869f294cf8b9625debae7b80846b71ebd015287cc3971435f98f0cae046"
SOURCE_PAGE = "raw/gutenberg/77576/html/pg77576-images.html#Page_141"
PUBLIC_PAGE = "source-page:141"


def run() -> dict:
    if LOG.exists() or (WORK / "publication").exists():
        raise PipelineError("Fresh Romans private release destination required")
    if (sha(MASTER), sha(ACCEPTANCE), sha(SOURCE)) != (MASTER_SHA, ACCEPTANCE_SHA, SOURCE_SHA):
        raise PipelineError("Accepted Romans or retained source authority changed")
    installed = _files(WORK)
    journal = read(JOURNAL)
    if journal["phase"] != "complete" or journal["work_id"] != WID or len(installed) != 64 or installed != journal["after"]:
        raise PipelineError("Installed Romans files differ from completed journal")
    if read(INDEX)["by_work"].get(WID, []):
        raise PipelineError("Earlier Romans release selection requires reconciliation")

    source_tree = html.fromstring(SOURCE.read_bytes())
    headings = source_tree.xpath('//h2[@id="pg-footer-heading"]')
    if len(headings) != 1:
        raise PipelineError("Retained Gutenberg license heading differs")
    license_text = "\n\n".join(
        etree.tostring(node, method="text", encoding="unicode").strip()
        for node in [headings[0], *headings[0].itersiblings()]
    ).replace("\r\n", "\n")
    notice_text = NOTICE.read_text(encoding="utf-8")
    if (len(license_text) != 17072 or sha256(license_text.encode()).hexdigest() != LICENSE_SHA
            or license_text not in notice_text or not notice_text.endswith(license_text + "\n```\n")):
        raise PipelineError("Visible Romans notice omits the exact full retained license")

    profile_ids = read(PROFILE)["note_ids"]
    tree = etree.parse(str(MASTER))
    ns = {"t": "http://www.tei-c.org/ns/1.0"}
    footnotes = tree.xpath('//t:text//t:div[@type="source-footnotes"]', namespaces=ns)
    references = tree.xpath("//t:text//t:ref", namespaces=ns)
    xml_id = "{http://www.w3.org/XML/1998/namespace}id"
    ids = [child.get(xml_id) for child in footnotes[0]] if len(footnotes) == 1 else []
    targets = [ref.get("target") for ref in references]
    if (len(ids) != 77 or ids != profile_ids or len(references) != 232
            or sum(target is None for target in targets) != 77
            or sum(target is not None and target.startswith("#f") for target in targets) != 77
            or sum(target is not None and target.startswith("#r") for target in targets) != 77
            or targets.count(SOURCE_PAGE) != 1):
        raise PipelineError("Romans accepted endnote/reference structure differs")

    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(), "source_sha256": sha(SOURCE_NOTE),
              "notice_path": NOTICE.relative_to(ROOT).as_posix(), "notice_sha256": sha(NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "pg77576-ignatius-romans-private-offline-20261003-v1",
                 "items": [{"item_id": WID, "category": "prose", "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if len(shown) != 1 or license_text not in shown[0] or "Roberts and Donaldson" not in shown[0]:
        raise PipelineError("Source-bound visible Romans attribution differs")

    # Only normalize the two equivalent Windows authority spellings used by
    # the current prose entrypoint. Every other path uses its original resolver.
    original_io = prose.io_path
    canonical = {str(ROOT), str(ACCEPTANCE)}
    def equivalent_authority_path(path: Path) -> Path:
        ordinary = str(path).removeprefix("\\\\?\\")
        return Path(ordinary) if ordinary in canonical else original_io(path)
    outside = ROOT.parent / "EzraOCR" / "AGENTS.md"
    if equivalent_authority_path(outside) != original_io(outside):
        raise PipelineError("Romans adapter changed an outside path")
    original_content = native_content.project_content
    original_observe_content = native_documents.observe_content
    original_normalize_ref = native_documents.normalize_reference_record
    original_observe_ref = native_documents.observe_reference_record

    def public_structure(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "source_target" and child == SOURCE_PAGE:
                    value[key] = PUBLIC_PAGE
                else:
                    public_structure(child)
        elif isinstance(value, list):
            for child in value:
                public_structure(child)
        return value

    def projected_content(element, *, source_profile=None):
        return public_structure(original_content(element, source_profile=source_profile))

    def observed_content(fragment, *, source_profile=None):
        structure, readable = original_observe_content(fragment, source_profile=source_profile)
        return public_structure(structure), readable

    def public_reference(record, *, book_codes):
        mapped = {**record, "target": PUBLIC_PAGE} if record.get("target") == SOURCE_PAGE else record
        return original_normalize_ref(mapped, book_codes=book_codes)

    def observed_reference(record, *, book_codes):
        mapped = {**record, "target": PUBLIC_PAGE} if record.get("target") == SOURCE_PAGE else record
        return original_observe_ref(mapped, book_codes=book_codes)

    prose.io_path = equivalent_authority_path
    native_content.project_content = projected_content
    native_documents.observe_content = observed_content
    native_documents.normalize_reference_record = public_reference
    native_documents.observe_reference_record = observed_reference
    try:
        with cached_edition_lookups():
            projected = prose.project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
            previous_project = prose.project_accepted_prose
            previous_native = native_documents.project_accepted_document
            def unavailable(*args, **kwargs):
                raise AssertionError("Independent checker invoked a prose producer")
            try:
                prose.project_accepted_prose = unavailable
                native_documents.project_accepted_document = unavailable
                native_content.project_content = unavailable
                native_documents.normalize_reference_record = unavailable
                errors = prose.verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                    rows=projected["rows"], receipt=projected["receipt"])
            finally:
                prose.project_accepted_prose = previous_project
                native_documents.project_accepted_document = previous_native
                native_content.project_content = projected_content
                native_documents.normalize_reference_record = public_reference
        rows = projected["rows"]
        characters = sum(len(row["text"]) for row in rows)
        if errors or len(rows) != 3 or characters != 32604 or projected["receipt"]["master_sha256"] != MASTER_SHA:
            raise PipelineError("Romans actual-master projection/checker differs: " + str(errors))
        first = rows[0]
        if (first["source_references"][0].get("target") != PUBLIC_PAGE
                or SOURCE_PAGE in json.dumps(rows, ensure_ascii=False)
                or json.dumps(rows, ensure_ascii=False).count(PUBLIC_PAGE) != 2):
            raise PipelineError("Romans public source-page disposition differs")

        bindings = {(Path("library/works") / WID / path).as_posix(): digest for path, digest in installed.items()}
        inputs = [JOURNAL, SOURCE, ROOT / "raw/gutenberg/77576/pg77576-h.zip",
                  ROOT / "raw/gutenberg/77576/acquisition-receipt.json", PROFILE, NOTICE, INDEX,
                  Path(__file__), ROOT / "build/tools/complete_puritan_private_release.py",
                  ROOT / "build/tools/report_release_stats.py", ROOT / "build/tools/check_release_reader.py",
                  ROOT / "build/scripts/export_huggingface.py", ROOT / "build/tools/check_hf_release.py"]
        inputs.extend(ROOT / "ocd_kernel/projection" / name for name in (
            "categories/prose.py", "categories/sermons.py", "categories/native_documents.py",
            "envelope.py", "native_content.py", "native_content_check.py",
            "source_projection_evidence.py", "receipt.py", "scripture_authority.py",
            "scripture_targets.py", "scripture_targets_check.py"))
        for folder in ("ocd_kernel/release", "ocd_kernel/library", "ocd_kernel/tei"):
            inputs.extend((ROOT / folder).rglob("*.py"))
        inputs.extend((ROOT / "schemas/v2").rglob("*.json"))
        bindings.update({path.relative_to(ROOT).as_posix(): sha(path) for path in inputs})
        check(bindings)
        save(LOG / "selection.json", selection)
        save(LOG / "input-bindings-before.json", bindings)
        save(LOG / "actual-master-projection.json", projected)
        save(LOG / "independent-projection.json", {"status": "pass", "errors": errors,
            "producer_disabled": True, "rows": len(rows), "text_characters": characters,
            "master_sha256": MASTER_SHA, "saved_projection_sha256": sha(LOG / "actual-master-projection.json")})
        save(LOG / "source-structure.json", {"status": "pass", "ordered_endnote_ids": ids,
            "source_references": len(references), "targetless_references": 77,
            "footnote_targets": 77, "backlink_targets": 77, "source_page_targets": 1,
            "full_license_characters": len(license_text), "full_license_sha256": LICENSE_SHA,
            "visible_notice_sha256": sha(NOTICE), "source_page_private_target": SOURCE_PAGE,
            "source_page_public_locator": PUBLIC_PAGE, "public_occurrences": 2})
        save(LOG / "prior-attempt.json", {"status": "failed-before-publication",
            "path": "reports/_logs/pg77576-ignatius-romans-private-release-20261003-v1",
            "failure": "public privacy gate rejected a retained raw source-page path in two projected row fields"})
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
        if total["records"] != 3 or total["text_characters"] != characters:
            raise PipelineError("Released Romans counts differ from accepted master")
        if notice_text.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
            raise PipelineError("Release card omits complete visible Romans notice")
        check(bindings)
        if _files(WORK) != installed:
            raise PipelineError("Installed Romans authority changed during release")
        files = _files(destination)
        completion = {"status": "pass", "checked_at": datetime.now(timezone.utc).isoformat(),
            "work_id": WID, "rows": 3, "text_characters": characters, "accepted_master_sha256": MASTER_SHA,
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
            "# The Epistle of Ignatius to the Romans: private offline release\n\n"
            f"The unchanged accepted electronic witness passes actual-master prose projection, "
            f"independent checking, private assembly, release verification, statistics, and both "
            f"offline readers: 3 rows and {characters:,} text characters. The public dataset card "
            "carries the detailed source credit and complete retained Project Gutenberg License.\n\n"
            "[Completion](completion.json) and [selection](selection.json) bind this release. "
            "Human acceptance, print collation, rights clearance, and public publication remain separate.\n"
        ).encode("utf-8"))
        expected = dict(installed)
        expected.update({"publication/" + name: sha(WORK / "publication" / name)
            for name in ("completion.json", "selection.json", "README.md")})
        if _files(WORK) != expected or _files(destination) != files:
            raise PipelineError("Final Romans delivery envelope differs")
        check(bindings)
        save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
            "canonical_files": expected, "release_file_count": len(files),
            "canonical_completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
            "canonical_selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json"),
            "rows": 3, "text_characters": characters, "publication_performed": False})
        return {"status": "pass", "rows": 3, "text_characters": characters,
                "installed_files": len(installed), "release_files": len(files)}
    finally:
        prose.io_path = original_io
        native_content.project_content = original_content
        native_documents.observe_content = original_observe_content
        native_documents.normalize_reference_record = original_normalize_ref
        native_documents.observe_reference_record = original_observe_ref


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True), flush=True)
