"""Close the installed Assumption Sermon I as a private offline prose release."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote

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
WID = "pg49917-assumption-sermon-i"
WORK = ROOT / "library/works" / WID
EDITION = WORK / "forms/pg49917-assumption-sermon-i-english/editions/pg49917-assumption-sermon-i-pg49917-edition"
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"
SOURCE = ROOT / "raw/gutenberg/49917/html/pg49917-images.html"
PROFILE = WORK / "integration/pg49917-html-v1/profile.json"
JOURNAL = ROOT / ".tmp_audit/accepted-install-792d2324b3c04eb2/operation.json"
SOURCE_NOTE = ROOT / "sources/gutenberg" / WID / "README.source.md"
NOTICE = ROOT / "data/structured-text" / WID / "README.md"
INDEX = ROOT / "reports/_logs/retained-release-selection-index-20261002-v2/index.json"
LOG = ROOT / "reports/_logs/pg49917-assumption-sermon-i-private-release-20261003-v3"
MASTER_SHA = "d888df20a5eaf43429bd0f52c3369b6f1abc79936007d4921cf94e91a99c426b"
ACCEPTANCE_SHA = "314e485edc0267fec02773dc41b7f09f1d8e2fbd4b7059747d8d92005b1d7b11"
SOURCE_SHA = "a517174360b8c13609b74c005965f1386e6a0cc0f97fd795d248ccb496944204"
LICENSE_SHA = "9df13869f294cf8b9625debae7b80846b71ebd015287cc3971435f98f0cae046"
PRIVATE_STYLES = {
    "comment-digest:2e9da984f99e53da97f60626aee67570dd4ea219018ca9726e6ad946315c992f": "source-comment-retained-privately",
    "presentation-style-omitted-sha256:4d524dc3cba160cd5649028baa7d4174cf30a15278a4d08504d2d3baaf2db8bc": "source-presentation-style-omitted",
}
MARKER_STYLES = {"1221": (next(iter(PRIVATE_STYLES)), "source-html-comment")}
MARKER_STYLES.update({number: (list(PRIVATE_STYLES)[1], "source-html-tbody")
                      for number in ("2538", "2550", "2562", "2574", "2586", "2598", "2610", "2622")})
ANNOTATION_PREFIX = "urn:ocd:pg49917:source-marker:"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def run() -> dict:
    if (LOG.exists() and {p.name for p in LOG.iterdir()} != {"prior-canonical-publication"}) or (WORK / "publication").exists():
        raise PipelineError("Fresh Sermon I private release destination required")
    if (sha(MASTER), sha(ACCEPTANCE), sha(SOURCE)) != (MASTER_SHA, ACCEPTANCE_SHA, SOURCE_SHA):
        raise PipelineError("Sermon I authority changed")
    installed = _files(WORK)
    journal = read(JOURNAL)
    if (journal["phase"] != "complete" or journal["work_id"] != WID
            or len(installed) != 75 or installed != journal["after"]):
        raise PipelineError("Sermon I installed files differ from completed journal")
    if read(INDEX)["by_work"].get(WID, []):
        raise PipelineError("Earlier Sermon I release selection requires reconciliation")

    source_tree = html.fromstring(SOURCE.read_bytes())
    headings = source_tree.xpath('//h2[@id="pg-footer-heading"]')
    if len(headings) != 1:
        raise PipelineError("Retained PG49917 license heading differs")
    license_text = "\n\n".join(etree.tostring(node, method="text", encoding="unicode").strip()
                             for node in [headings[0], *headings[0].itersiblings()]).replace("\r\n", "\n")
    notice_text = NOTICE.read_text(encoding="utf-8")
    if (len(license_text) != 17072 or sha256(license_text.encode()).hexdigest() != LICENSE_SHA
            or license_text not in notice_text or not notice_text.endswith(license_text + "\n```\n")):
        raise PipelineError("Visible Sermon I notice omits full retained license")

    profile = read(PROFILE)
    master = etree.parse(str(MASTER))
    ns = {"xml": "http://www.w3.org/XML/1998/namespace"}
    for item_id in [profile["sermon_id"], *profile["note_ids"], *profile["pages"]]:
        if len(master.xpath('//*[@xml:id=$id]', id=item_id, namespaces=ns)) != 1:
            raise PipelineError("Sermon I accepted source attachment differs: " + item_id)
    if (len(profile["note_ids"]) != 8 or len(profile["pages"]) != 24
            or profile["body_intervals"] != [[22, 23]] or profile["source_sha256"] != SOURCE_SHA):
        raise PipelineError("Sermon I source profile differs")
    style_positions = {token: [node.get("n") for node in master.iter() if token in node.attrib.values()]
                       for token in PRIVATE_STYLES}
    if list(style_positions.values()) != [["1221"],
            ["2538", "2550", "2562", "2574", "2586", "2598", "2610", "2622"]]:
        raise PipelineError("Sermon I private source-style positions differ")

    notice = {"source_path": SOURCE_NOTE.relative_to(ROOT).as_posix(), "source_sha256": sha(SOURCE_NOTE),
              "notice_path": NOTICE.relative_to(ROOT).as_posix(), "notice_sha256": sha(NOTICE)}
    selection = {"schema_version": "2.0", "release_id": "pg49917-assumption-sermon-i-private-offline-20261003-v3",
                 "items": [{"item_id": WID, "category": "prose", "acceptance_path": ACCEPTANCE.relative_to(ROOT).as_posix(),
                            "public_notices": [notice]}]}
    shown = notice_texts_for_item(ROOT, selection["items"][0], ACCEPTANCE)
    if len(shown) != 1 or license_text not in shown[0] or "Mary H. Allies" not in shown[0]:
        raise PipelineError("Source-bound Sermon I attribution differs")

    # Normalize only equivalent Windows spellings for these two validated authorities.
    original_io = prose.io_path
    canonical = {str(ROOT), str(ACCEPTANCE)}
    def equivalent_authority_path(path: Path) -> Path:
        ordinary = str(path).removeprefix("\\\\?\\")
        return Path(ordinary) if ordinary in canonical else original_io(path)
    outside = ROOT.parent / "EzraOCR" / "AGENTS.md"
    if equivalent_authority_path(outside) != original_io(outside):
        raise PipelineError("Sermon I adapter changed an outside path")
    original_content = native_content.project_content
    original_observe_content = native_documents.observe_content

    def public_styles(value):
        if isinstance(value, dict):
            if value.get("kind") == "source-marker":
                attributes = value.get("attributes")
                if not isinstance(attributes, dict):
                    raise PipelineError("Sermon I source marker lacks attributes")
                number = attributes.get("number")
                if number in MARKER_STYLES:
                    token, unit = MARKER_STYLES[number]
                    annotation = attributes.get("source_annotations")
                    if (attributes.get("style") != token or not isinstance(annotation, str)
                            or not annotation.startswith(ANNOTATION_PREFIX)):
                        raise PipelineError("Sermon I source marker style/annotation differs")
                    try:
                        detail = json.loads(unquote(annotation[len(ANNOTATION_PREFIX):]))
                    except (ValueError, UnicodeError) as exc:
                        raise PipelineError("Sermon I source marker annotation is invalid") from exc
                    expected = {"unit", "n", "rend"} if unit == "source-html-comment" else {
                        "unit", "n", "rend", XML_ID}
                    if (not isinstance(detail, dict) or set(detail) != expected
                            or detail["unit"] != unit or detail["n"] != number
                            or detail["rend"] != token
                            or unit == "source-html-tbody" and detail[XML_ID] != "source-node-" + number):
                        raise PipelineError("Sermon I source marker annotation differs")
                    detail["rend"] = PRIVATE_STYLES[token]
                    attributes["style"] = PRIVATE_STYLES[token]
                    attributes["source_annotations"] = ANNOTATION_PREFIX + quote(
                        json.dumps(detail, ensure_ascii=False, separators=(",", ":")), safe="")
            for key, child in value.items():
                public_styles(child)
        elif isinstance(value, list):
            for child in value:
                public_styles(child)
        return value

    def projected_content(element, *, source_profile=None):
        return public_styles(original_content(element, source_profile=source_profile))

    def observed_content(fragment, *, source_profile=None):
        structure, readable = original_observe_content(fragment, source_profile=source_profile)
        return public_styles(structure), readable

    prose.io_path = equivalent_authority_path
    native_content.project_content = projected_content
    native_documents.observe_content = observed_content
    try:
        with cached_edition_lookups():
            print("actual-master-projection: START", flush=True)
            projected = prose.project_accepted_prose(ROOT, acceptance_path=ACCEPTANCE)
            previous_project = prose.project_accepted_prose
            previous_native = native_documents.project_accepted_document
            def unavailable(*args, **kwargs):
                raise AssertionError("Independent checker invoked a producer")
            try:
                prose.project_accepted_prose = unavailable
                native_documents.project_accepted_document = unavailable
                native_content.project_content = unavailable
                errors = prose.verify_accepted_prose(ROOT, acceptance_path=ACCEPTANCE,
                    rows=projected["rows"], receipt=projected["receipt"])
            finally:
                prose.project_accepted_prose = previous_project
                native_documents.project_accepted_document = previous_native
                native_content.project_content = projected_content
        rows = projected["rows"]
        characters = sum(len(row["text"]) for row in rows)
        if errors or len(rows) != 2 or characters != 27265 or projected["receipt"]["master_sha256"] != MASTER_SHA:
            raise PipelineError("Sermon I actual-master projection/checker differs: " + str(errors))
        public_rows = json.dumps(rows, ensure_ascii=False)
        if (any(token in public_rows for token in PRIVATE_STYLES)
                or public_rows.count("source-comment-retained-privately") != 2
                or public_rows.count("source-presentation-style-omitted") != 16
                or re.search(r"(?i)\b[0-9a-f]{64}\b", public_rows)
                or [sha256(row["text"].encode()).hexdigest() for row in rows] != [
                    "b4a228ac77b448e886994ee3b85eb5924ba76ff46abd84756f226ce3c577a860",
                    "e89df22a964153cb4a4fa244fdd544c3032b0fc1a4e9cf4445037c75b7da02b9"]):
            raise PipelineError("Sermon I public source-style disposition differs")
        print("actual-master-projection: PASS", flush=True)

        bindings = {(Path("library/works") / WID / path).as_posix(): digest for path, digest in installed.items()}
        inputs = [JOURNAL, SOURCE, ROOT / "raw/gutenberg/49917/pg49917-h.zip",
                  ROOT / "raw/gutenberg/49917/acquisition-receipt.json", PROFILE, SOURCE_NOTE,
                  NOTICE, INDEX, Path(__file__), ROOT / "build/tools/complete_puritan_private_release.py",
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
        save(LOG / "source-structure.json", {"status": "pass", "sermon_id": profile["sermon_id"],
            "ordered_linked_note_ids": profile["note_ids"], "ordered_page_ids": profile["pages"],
            "full_license_characters": len(license_text), "full_license_sha256": LICENSE_SHA,
            "visible_notice_sha256": sha(NOTICE), "private_source_style_positions": style_positions,
            "public_style_disposition": PRIVATE_STYLES, "public_style_and_annotation_occurrences": [2, 16]})
        save(LOG / "prior-attempts.json", {"status": "failed-independent-privacy-review-before-publication",
            "attempts": [
                {"path": "reports/_logs/pg49917-assumption-sermon-i-private-release-20261003-v1",
                 "failure": "privacy gate rejected one comment digest and eight omitted-style digests"},
                {"path": "reports/_logs/pg49917-assumption-sermon-i-private-release-20261003-v2",
                 "failure": "percent-encoded annotation payloads still exposed nine source digests"}]})
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
        if total["records"] != 2 or total["text_characters"] != characters:
            raise PipelineError("Released Sermon I counts differ from accepted master")
        public_jsonl = (destination / "public/data/prose/train.jsonl").read_text(encoding="utf-8")
        if (re.search(r"(?i)\b[0-9a-f]{64}\b", public_jsonl)
                or any(token in public_jsonl for token in PRIVATE_STYLES)):
            raise PipelineError("Sermon I public JSONL still exposes source digests")
        if notice_text.rstrip() not in (destination / "public/README.md").read_text(encoding="utf-8"):
            raise PipelineError("Release card omits complete visible Sermon I notice")
        check(bindings)
        if _files(WORK) != installed:
            raise PipelineError("Installed Sermon I authority changed during release")
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
            "# Sermon I. On the Assumption: private offline release\n\n"
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
            raise PipelineError("Final Sermon I delivery envelope differs")
        check(bindings)
        save(LOG / "final-audit.json", {"status": "pass", "input_binding_count": len(bindings),
            "canonical_files": expected, "release_file_count": len(files),
            "canonical_completion_byte_identical": sha(WORK / "publication/completion.json") == sha(LOG / "completion.json"),
            "canonical_selection_byte_identical": sha(WORK / "publication/selection.json") == sha(LOG / "selection.json"),
            "rows": 2, "text_characters": characters, "publication_performed": False})
        return completion
    finally:
        prose.io_path = original_io
        native_content.project_content = original_content
        native_documents.observe_content = original_observe_content


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "work_id": result["work_id"],
                      "rows": result["rows"], "text_characters": result["text_characters"],
                      "release_files": len(result["release_file_bindings"])}, sort_keys=True))
