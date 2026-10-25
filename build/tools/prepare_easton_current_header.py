"""Prepare an exact header-only Easton technical adoption candidate."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "eastons-bible-dictionary"
FORM_ID = "eastons-bible-dictionary-retained-electronic"
EDITION_ID = "eastons-bible-dictionary-retained-electronic-witness"
ACQUISITION_ID = "eastons-bible-dictionary-retained-source"
WORK = Path("library/works") / WORK_ID
BASE = WORK / "integration/easton-current-v1"
OLD = Path("D:/Library/Open Christian Data/candidate-reviews/jwbickel-dictionaries-20260928-v1/eastons-bible-dictionary/package/content.tei.xml")
SOURCE = Path("raw/bible_dictionaries/eastons.jsonl")
SOURCE_SHA = "978e09fdb66e9c6b722085f868c0cc84030df9e15c6188a06390f3822888082a"
OLD_SHA = "79ed9b76699611e8816ca713ac1c645083d73ea06fb6f19e5f2a1faceeee3240"
REVISION = "eastons-retained-electronic-technical-v1"
SCOPE = (
    "The complete retained JWBickel/BibleDictionaries Easton's Bible Dictionary JSONL electronic witness: "
    "all 3,963 ordered source records and all 7,464 ordered definition blocks, including duplicate headword "
    "occurrences. No identified print edition, inferred author, alternate terms, normalized references, "
    "rights clearance, or public publication claim."
)
TEI = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def put(relative, payload):
    path = io_path(ROOT / relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"Existing Easton preparation differs: {path}")
    else:
        path.write_bytes(payload)


def text_element(parent, name, value, **attributes):
    element = etree.SubElement(parent, TEI + name, **attributes)
    element.text = value
    return element


def main():
    old = io_path(OLD).read_bytes()
    if sha256(old).hexdigest() != OLD_SHA:
        raise ValueError("Retained Easton TEI candidate changed")
    source = io_path(ROOT / SOURCE).read_bytes()
    if len(source) != 2690740 or sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError("Retained Easton JSONL changed")
    marker_open, marker_close = b"<teiHeader", b"</teiHeader>"
    start, close = old.find(marker_open), old.find(marker_close)
    if start < 0 or close <= start or old.find(marker_open, start + 1) >= 0:
        raise ValueError("Easton TEI does not have one unambiguous header")
    end = close + len(marker_close)
    old_tree = etree.fromstring(old)
    header = old_tree.find(TEI + "teiHeader")
    if header is None:
        raise ValueError("Easton TEI header is missing")
    desc = header.find(TEI + "fileDesc/" + TEI + "sourceDesc")
    availability = header.find(TEI + "fileDesc/" + TEI + "publicationStmt/" + TEI + "availability")
    if desc is None or availability is None or len(availability) != 1:
        raise ValueError("Easton retained header has unexpected source or availability shape")
    if desc.xpath("./tei:bibl[@type='ocd-acceptance-binding']", namespaces={"tei": TEI[1:-1]}):
        raise ValueError("Easton header is already acceptance-bound")
    availability.set("status", "restricted")
    availability[0].text = (
        "Evidence-backed technical master of the retained electronic JSONL witness only. "
        "The structured JWBickel source license, print-edition identity, human textual review, "
        "and public publication authorization remain unresolved; no rights grant is implied."
    )
    binding = etree.SubElement(desc, TEI + "bibl", type="ocd-acceptance-binding")
    etree.SubElement(binding, TEI + "ptr", target="https://huggingface.co/datasets/JWBickel/BibleDictionaries")
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
    text_element(binding, "note", SCOPE, type="source-scope")
    revision_desc = header.find(TEI + "revisionDesc")
    if revision_desc is None:
        revision_desc = etree.SubElement(header, TEI + "revisionDesc")
    if list(revision_desc):
        raise ValueError("Unexpected preexisting Easton revision history")
    note = (
        "Bind the unchanged 3,963 native lexical entries and 7,464 ordered definitions to the "
        "retained electronic witness for technical adoption; qualify rights and edition uncertainty."
    )
    change = etree.SubElement(revision_desc, TEI + "change", when=datetime.now(timezone.utc).date().isoformat())
    change.set(XML + "id", REVISION)
    change.text = note
    fresh_header = etree.tostring(header, encoding="UTF-8", with_tail=False)
    fresh = old[:start] + fresh_header + old[end:]
    if fresh.split(marker_close, 1)[1] != old.split(marker_close, 1)[1]:
        raise ValueError("Easton lexical body changed during header renewal")
    new_tree = etree.fromstring(fresh)
    if etree.tostring(old_tree.find(TEI + "text")) != etree.tostring(new_tree.find(TEI + "text")):
        raise ValueError("Easton parsed text tree changed during header renewal")
    put(BASE / "historical-header.xml", old[start:end])
    put(BASE / "fresh-header.xml", fresh_header)
    put(BASE / "candidate.tei.xml", fresh)
    put(BASE / "header-renewal.json", canonical({
        "status": "pass", "work_id": WORK_ID, "retained_candidate_sha256": OLD_SHA,
        "source_sha256": SOURCE_SHA, "candidate_sha256": sha256(fresh).hexdigest(),
        "body_bytes_identical": True, "parsed_text_tree_identical": True,
        "representation_revision": {"id": REVISION, "date": change.get("when"), "note": note},
        "scope": SCOPE, "historical_candidate_unchanged": True,
        "changes": ["source-bound acceptance header", "restricted technical availability", "representation revision"],
        "remaining": ["human review", "structured-source rights", "print-edition identity", "public publication"],
    }))
    notice = (
        "# Easton's Bible Dictionary: retained electronic witness and credit\n\n"
        "This dataset is derived from the complete 3,963-record Easton's Bible Dictionary JSONL member of "
        "[JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries). "
        "Its 7,464 ordered definition blocks, repeated headwords, and literal citation-looking text "
        "are retained. Source member: `raw/bible_dictionaries/eastons.jsonl` "
        f"(SHA-256 `{SOURCE_SHA}`).\n\n"
        "The retained member identifies an electronic witness. It does not establish a print edition, "
        "author, or bibliographic lineage. The historic work's age and the modern JWBickel structured "
        "JSONL are distinct rights questions; the latter's reuse license is unresolved. "
        "Credit to JWBickel/BibleDictionaries is included here without claiming permission, "
        "rights clearance, or public publication authorization.\n"
    ).encode("utf-8")
    put(WORK / "SOURCE_CREDIT.md", notice)
    put(Path("data/reference_entries") / WORK_ID / "README.md", notice)
    print(json.dumps({"status": "pass", "candidate_sha256": sha256(fresh).hexdigest(),
                      "source_sha256": SOURCE_SHA, "body_bytes_identical": True,
                      "source_data_notice_sha256": sha256(notice).hexdigest()}))


if __name__ == "__main__":
    main()
