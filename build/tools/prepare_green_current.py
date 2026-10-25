"""Compose a constrained active header and reversible existing-TEI aliases."""

import copy
import json
from pathlib import Path

from lxml import etree

from build.tools.preflight_green_current import ROOT, LOG, WORK_ID, WORK, SOURCE, digest, save
from build.tei.green_header_archive import encode, decode, serialize_decoded, T
from ocd_kernel.library._common import io_path
from ocd_kernel.projection.categories.prose import project_prose_document

FORM_ID = "green-docsouth-retained"
EDITION_ID = "green-docsouth-electronic"
ACQUISITION_ID = "green-docsouth-acquired"
REVISION = "green-retained-native-technical-v1"
BASE = WORK / "integration/green-current-v3"


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def add(parent, tag, text=None, **attributes):
    node = etree.SubElement(parent, T + tag, **attributes)
    node.text = text
    return node


def main():
    historical = etree.fromstring((LOG / "historical-package/content.tei.xml").read_bytes())
    adapted = etree.fromstring((LOG / "body-adapter-v2.tei.xml").read_bytes())
    old_header = historical.find(T + "teiHeader")
    original_header_bytes = etree.tostring(old_header)
    archive = encode(old_header)
    if serialize_decoded(decode(etree.tostring(archive))) != original_header_bytes:
        raise ValueError("Complete 99-node archived header inverse differs")
    acquisition_path = WORK / "forms" / FORM_ID / "editions" / EDITION_ID / "acquisitions" / (ACQUISITION_ID + ".json")
    acquisition = json.loads(io_path(acquisition_path).read_bytes())
    work = json.loads(io_path(WORK / "work.json").read_bytes())
    old_desc = old_header.find(T + "fileDesc")
    old_title = old_desc.find(T + "titleStmt")
    source_print = old_desc.find(T + "sourceDesc/" + T + "biblFull")
    header = etree.Element(T + "teiHeader", nsmap={None: T[1:-1]})
    desc = add(header, "fileDesc")
    title_stmt = add(desc, "titleStmt")
    add(title_stmt, "title", "".join(old_title.find(T + "title").itertext()))
    add(title_stmt, "author", old_title.find(T + "author").text)
    for role in old_title.findall(T + "respStmt"):
        current = add(title_stmt, "respStmt")
        add(current, "resp", role.find(T + "resp").text)
        add(current, "name", "".join(role.find(T + "name").itertext()))
    pub = add(desc, "publicationStmt")
    add(pub, "publisher", "Open Christian Data: technical adoption of the retained electronic witness")
    availability = add(pub, "availability", status="restricted")
    add(availability, "p", "DocSouth's No Copyright - United States statement is a provider belief under U.S. law, not worldwide clearance. Human acceptance, independent rights clearance, image/print collation and public publication remain separate and unresolved.")
    source_desc = add(desc, "sourceDesc")
    binding = add(source_desc, "bibl", type="ocd-acceptance-binding")
    add(binding, "ptr", target=acquisition["url"])
    identity = {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID, "representation_revision": REVISION, "source_sha256": acquisition["source_sha256"], "retained_sha256": acquisition["source_sha256"], "sha256": acquisition["source_sha256"], "source_bytes": str(acquisition["source_bytes"]), "source_kind": acquisition.get("source_kind", "retained-file")}
    # The existing singular-XML acquisition supplies no source_kind field.
    # Do not invent an extra acceptance kind while renewing the header.
    identity.pop("source_kind")
    for kind, value in identity.items():
        add(binding, "idno", value, type=kind)
    add(binding, "note", acquisition["source_scope"], type="source-scope")
    add(binding, "note", acquisition["source_path"], type="source-location")
    add(binding, "note", "Complete one-volume retained electronic text, front and body; source has no back. All 64 page markers, ten headings, twelve note/ref pairs, twelve sic/corr choices and three source image URLs are conserved. External image binaries are unretained; no newly identified physical print witness or image-content verification is claimed.", type="native-text-scope")
    electronic = add(source_desc, "bibl", type="source-electronic-edition")
    add(electronic, "title", "".join(old_title.find(T + "title").itertext()))
    add(electronic, "publisher", old_desc.find(T + "publicationStmt/" + T + "publisher").text)
    add(electronic, "edition", "".join(old_desc.find(T + "editionStmt/" + T + "edition").itertext()))
    add(electronic, "date", old_desc.find(T + "publicationStmt/" + T + "date").text)
    add(electronic, "note", old_title.find(T + "funder").text, type="source-funding-statement")
    add(electronic, "note", "".join(old_desc.find(T + "publicationStmt/" + T + "availability").itertext()), type="literal-provider-rights-statement")
    printed = add(source_desc, "bibl", type="source-described-print-edition")
    add(printed, "title", "".join(source_print.find(T + "titleStmt/" + T + "title").itertext()), type="title-page")
    add(printed, "author", source_print.find(T + "titleStmt/" + T + "author").text)
    add(printed, "publisher", source_print.find(T + "publicationStmt/" + T + "publisher").text)
    add(printed, "date", source_print.find(T + "publicationStmt/" + T + "date").text)
    add(printed, "pubPlace", source_print.find(T + "sourceDesc/" + T + "bibl/" + T + "pubPlace").text)
    add(printed, "note", "".join(source_print.find(T + "notesStmt").itertext()), type="literal-source-call-number")
    add(printed, "note", "These are the retained source's print-description fields; they are distinct from the 2001 electronic edition and do not establish new physical print collation.", type="print-metadata-qualification")
    archived = add(source_desc, "bibl", type="retained-historical-header-evidence")
    holder = add(archived, "note", type="source-header-archive")
    holder.append(archive)
    add(archived, "note", "The segment tree is a canonical annotated archival representation of the exact historical P5 header, not literal source TEI serialization. A separately checked inverse restores every QName, ordered expanded-name attribute, child, text and tail, including the root tail. It preserves provider/editorial/classification/revision details outside authored text.", type="archive-representation-qualification")
    encoding = add(header, "encodingDesc")
    add(encoding, "p", "Existing P5 body reused; exactly 21 reversible work-local aliases conserve source title-page roles, note back-references and one empty standalone source correction marker. No new source conversion. The archival header and complete retained XML remain evidence; readable attribution/rights notices accompany the data.")
    revision = add(header, "revisionDesc")
    change = add(revision, "change", "Technical adoption of complete retained Green electronic volume, with exact historical body inverse and qualified archived-header/current-source bindings.", when="2026-10-02")
    change.set("{http://www.w3.org/XML/1998/namespace}id", REVISION)
    header.tail = historical.find(T + "teiHeader").tail
    adapted.replace(adapted.find(T + "teiHeader"), header)
    candidate = etree.tostring(adapted, xml_declaration=True, encoding="UTF-8")
    save(BASE / "candidate.tei.xml", candidate)
    save(BASE / "historical-header.xml", original_header_bytes)
    save(BASE / "fresh-header.xml", etree.tostring(header))
    save(BASE / "archival-header-carrier.xml", etree.tostring(archive))
    profile = {"contract": "ocd-green-current-retained-native-adoption-v1", "identity": identity, "historical_candidate_sha256": digest((LOG / "historical-package/content.tei.xml").read_bytes()), "candidate_sha256": digest(candidate), "header_archive": {"nodes": len(list(old_header.iter())), "historical_header_sha256": digest(original_header_bytes), "canonical_archive_sha256": digest(etree.tostring(archive)), "inverse_serialization_sha256": digest(serialize_decoded(decode(etree.tostring(archive)))), "byte_exact": True}, "text_alias_proof": {"path": (LOG / "body-adapter-inverse-v1.json").relative_to(ROOT).as_posix(), "sha256": digest((LOG / "body-adapter-inverse-v1.json").read_bytes())}, "metadata_prerequisites": ["form.language absent -> en", "edition.language absent -> en", "edition.category absent -> prose"], "scope": acquisition["source_scope"], "source_kind_qualification": "Default retained-file acquisition; _source_binding/current _tei_facts will check exact current kind before staging", "archive_closed_grammar": "Only TEI seg, exactly type/subtype/n/corresp; type source-header-element; preorder n=1..99; subtype equals encoded original TEI QName localname; versioned URI contains canonical ordered qname/attributes JSON, duplicate keys/attributes forbidden. Decoder-generated envelope preserves root tail; full serialization hash additionally rejects changed otherwise-valid text/tail/attributes/hierarchy."}
    profile["source_kind_qualification"] = "The acquisition binds one retained XML file; no member-set or other source_kind is supplied or invented."
    profile["text_alias_proof"] = {"path": (LOG / "body-adapter-inverse-v2.json").relative_to(ROOT).as_posix(), "sha256": digest((LOG / "body-adapter-inverse-v2.json").read_bytes())}
    save(BASE / "profile.json", json_bytes(profile))
    try:
        actual = project_prose_document(BASE / "candidate.tei.xml", identity={k: identity[k] for k in ("work_id", "textual_form_id", "edition_id")}, language="en", representation_revision=REVISION, edition_title=work["textual_forms"][0]["editions"][0]["title"], _allow_acceptance_metadata=True)
        save(LOG / "current-projection-probe-v3.json", json_bytes({"status": "pass", "rows": len(actual["rows"]), "text_characters": sum(len(row["text"]) for row in actual["rows"]), "candidate_sha256": digest(candidate)}))
        save(LOG / "current-projection-v3.json", json_bytes(actual))
        print(json.dumps({"status": "pass", "candidate_sha256": digest(candidate), "rows": len(actual["rows"]), "text_characters": sum(len(row["text"]) for row in actual["rows"])}))
    except RuntimeError as exc:
        save(LOG / "current-projection-probe-v3.json", json_bytes({"status": "rejected", "candidate_sha256": digest(candidate), "reason": str(exc)}))
        raise


if __name__ == "__main__":
    main()
