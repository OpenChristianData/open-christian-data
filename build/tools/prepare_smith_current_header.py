"""Prepare Smith's retained electronic witness with an exact source-bound header."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "smiths-bible-dictionary"
FORM_ID = "smiths-bible-dictionary-retained-electronic"
EDITION_ID = "smiths-bible-dictionary-retained-electronic-witness"
ACQUISITION_ID = "smiths-bible-dictionary-retained-source"
WORK = Path("library/works") / WORK_ID
BASE = WORK / "integration/smith-current-v1"
OLD = Path("D:/Library/Open Christian Data/candidate-reviews/jwbickel-dictionaries-20260928-v1/smiths-bible-dictionary/package/content.tei.xml")
SOURCE = Path("raw/bible_dictionaries/smiths.jsonl")
ACQUISITION = WORK / "forms" / FORM_ID / "editions" / EDITION_ID / "acquisitions" / f"{ACQUISITION_ID}.json"
OLD_SHA = "1ad08fbda35f1445c5c5546493fd2241acbc5a7669d56a99dbf4fb02f293a690"
SOURCE_SHA = "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d"
ROOT_SOURCE_REVIEW_SHA = "67872b5d84a9dcaf43a8c5aaf3d23bdf37bd990727be6edd82b23c761d0d288a"
REVISION = "smiths-retained-electronic-technical-v1"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def put(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def text_element(parent, name: str, value: str, **attributes):
    node = etree.SubElement(parent, TEI + name, **attributes)
    node.text = value
    return node


def main() -> None:
    old = OLD.read_bytes()
    source = (ROOT / SOURCE).read_bytes()
    if digest(old) != OLD_SHA or digest(source) != SOURCE_SHA or len(source) != 2919477:
        raise ValueError("Smith original candidate or retained source drifted")
    root_review = ROOT / "reports/_logs/smith-coordinator-source-review-20261002-v1/review.json"
    if digest(root_review.read_bytes()) != ROOT_SOURCE_REVIEW_SHA:
        raise ValueError("Smith coordinator whole-source review drifted")
    acquisition = json.loads((ROOT / ACQUISITION).read_text(encoding="utf-8"))
    scope = acquisition["source_scope"]
    if scope != acquisition["retained_files"][0]["scope"] or acquisition["source_sha256"] != SOURCE_SHA:
        raise ValueError("Smith acquisition source scope/hash differ")
    marker_open, marker_close = b"<teiHeader", b"</teiHeader>"
    start, close = old.find(marker_open), old.find(marker_close)
    if start < 0 or close <= start or old.find(marker_open, start + 1) >= 0:
        raise ValueError("Smith original TEI header is not unique")
    end = close + len(marker_close)
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    old_tree = etree.fromstring(old, parser)
    header = old_tree.find(TEI + "teiHeader")
    if header is None:
        raise ValueError("Smith TEI header missing")
    desc = header.find(TEI + "fileDesc/" + TEI + "sourceDesc")
    availability = header.find(TEI + "fileDesc/" + TEI + "publicationStmt/" + TEI + "availability")
    if desc is None or availability is None or len(availability) != 1:
        raise ValueError("Smith historical source or availability header differs")
    if desc.xpath("./tei:bibl[@type='ocd-acceptance-binding']", namespaces={"tei": TEI[1:-1]}):
        raise ValueError("Smith candidate is already acceptance-bound")
    availability.set("status", "restricted")
    availability[0].text = (
        "Evidence-backed technical master of the retained electronic JSONL witness only. "
        "The structured JWBickel source license, print-edition identity, human textual review, "
        "and public publication authorization remain unresolved; no rights grant is implied."
    )
    binding = etree.SubElement(desc, TEI + "bibl", type="ocd-acceptance-binding")
    etree.SubElement(binding, TEI + "ptr", target=acquisition["url"])
    fields = {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_sha256": SOURCE_SHA,
        "source_bytes": str(len(source)),
        "representation_revision": REVISION,
        "sha256": SOURCE_SHA,
    }
    for name, value in fields.items():
        text_element(binding, "idno", value, type=name)
    text_element(binding, "note", SOURCE.as_posix(), type="source-location")
    text_element(binding, "note", scope, type="source-scope")
    revision_desc = header.find(TEI + "revisionDesc")
    if revision_desc is None:
        revision_desc = etree.SubElement(header, TEI + "revisionDesc")
    if list(revision_desc):
        raise ValueError("Smith original revision history differs")
    note = "Bind unchanged 4,560 native lexical entries and 5,362 ordered definitions to the retained electronic witness for technical adoption; qualify rights and edition uncertainty."
    change = etree.SubElement(revision_desc, TEI + "change", when=datetime.now(timezone.utc).date().isoformat())
    change.set(XML + "id", REVISION)
    change.text = note
    fresh_header = etree.tostring(header, encoding="UTF-8", with_tail=False)
    fresh = old[:start] + fresh_header + old[end:]
    if fresh.split(marker_close, 1)[1] != old.split(marker_close, 1)[1]:
        raise ValueError("Smith native lexical body changed")
    new_tree = etree.fromstring(fresh, parser)
    if etree.tostring(old_tree.find(TEI + "text")) != etree.tostring(new_tree.find(TEI + "text")):
        raise ValueError("Smith parsed text tree changed")
    xsd_tree = etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"), parser)
    xsd = etree.XMLSchema(xsd_tree)
    if not xsd.validate(etree.ElementTree(new_tree)):
        raise ValueError(f"Smith current TEI fails P5 XSD: {xsd.error_log.last_error}")
    private_credit = (
        "# Smith's Bible Dictionary: retained electronic witness and credit\n\n"
        "This technical master represents all 4,560 ordered records and 5,362 ordered definition blocks of the retained Smith's Bible Dictionary JSONL member from "
        "[JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries). "
        f"Source member: `{SOURCE.as_posix()}` (SHA-256 `{SOURCE_SHA}`). Citation-looking text remains literal; no cross-references or alternate terms are invented.\n\n"
        "The retained member establishes an electronic witness, not an identified print edition, author, or bibliographic lineage. The historic work's age and the modern structured JSONL are distinct rights questions; the modern reuse terms remain unresolved. This credit does not claim permission, human textual acceptance, rights clearance, or public publication authorization.\n"
    ).encode("utf-8")
    public_credit = (
        "# Smith's Bible Dictionary: retained electronic witness\n\n"
        "This dataset contains 4,560 ordered entries and 5,362 definition blocks from the retained Smith's Bible Dictionary member of "
        "[JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries). The source's literal citation-looking text is preserved without inventing structured references.\n\n"
        "The retained member establishes an electronic witness, not an identified print edition or historical authorship. Reuse terms for the modern structured source remain unresolved. This notice credits JWBickel/BibleDictionaries without asserting a license, rights clearance, or public publication authorization.\n"
    ).encode("utf-8")
    source_notice = (
        "# Smith's Bible Dictionary source-directed notice\n\n"
        "The complete retained electronic dictionary member is credited to JWBickel/BibleDictionaries. Its structured-source reuse terms, print-edition identity, human textual acceptance, and public publication authorization remain unresolved.\n\n"
        "Show the human-visible credit and qualifications at `data/reference_entries/smiths-bible-dictionary/README.md` in every selected private release. The work-local source credit retains exact source member identity and digest for private audit.\n"
    ).encode("utf-8")
    put(ROOT / BASE / "historical-header.xml", old[start:end])
    put(ROOT / BASE / "fresh-header.xml", fresh_header)
    put(ROOT / BASE / "candidate.tei.xml", fresh)
    put(ROOT / BASE / "header-renewal.json", canonical({
        "contract": "ocd-smith-current-header-renewal-v1",
        "status": "pass",
        "work_id": WORK_ID,
        "retained_candidate_sha256": OLD_SHA,
        "source_sha256": SOURCE_SHA,
        "candidate_sha256": digest(fresh),
        "body_bytes_identical": True,
        "parsed_text_tree_identical": True,
        "tei_p5_valid": True,
        "source_scope": scope,
        "source_scope_authority": ACQUISITION.as_posix(),
        "coordinator_source_review_sha256": ROOT_SOURCE_REVIEW_SHA,
        "representation_revision": {"id": REVISION, "date": change.get("when"), "note": note},
        "historical_candidate_unchanged": True,
        "remaining": ["human review", "structured-source rights", "print-edition identity", "public publication"],
    }))
    put(ROOT / WORK / "SOURCE_CREDIT.md", private_credit)
    put(ROOT / "data/reference_entries/smiths-bible-dictionary/README.md", public_credit)
    put(ROOT / "sources/reference-entries/smiths-bible-dictionary/README.source.md", source_notice)
    print(json.dumps({"status": "pass", "candidate_sha256": digest(fresh), "body_bytes_identical": True, "source_sha256": SOURCE_SHA, "public_notice_sha256": digest(public_credit)}, sort_keys=True))


if __name__ == "__main__":
    main()
