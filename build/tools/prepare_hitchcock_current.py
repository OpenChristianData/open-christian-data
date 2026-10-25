"""Renew only Hitchcock's header; independently conserve the retained lexical body."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.library._common import io_path


ROOT = Path(__file__).resolve().parents[2]
WORK_ID = "hitchcocks-bible-names-dictionary"
FORM_ID = WORK_ID + "-retained-electronic"
EDITION_ID = WORK_ID + "-retained-electronic-witness"
ACQUISITION_ID = WORK_ID + "-retained-source"
WORK = ROOT / "library/works" / WORK_ID
BASE = WORK / "integration/hitchcock-current-v1"
LOG = ROOT / "reports/_logs/hitchcocks-bible-names-dictionary-current-reconciliation-20261002-v1"
HISTORICAL = LOG / "historical-package"
SOURCE = ROOT / "raw/bible_dictionaries/hitchcocks.jsonl"
SOURCE_SHA = "e25b127cfc9c6f6f14eb9aa059ea0b3ed7ceaf97e2fd88c192d74387c3e904a5"
OLD_SHA = "19f0cd4db853f16f8321b5001f6f7ab189aa9888f0085a733e6d9a33052afc4b"
REVISION = "hitchcocks-retained-electronic-technical-v1"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, raw: bytes) -> None:
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f"Existing prepared evidence differs: {path}")
    else:
        path.write_bytes(raw)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate source field: {key}")
        result[key] = value
    return result


def verify_body(raw_source: bytes, raw_tei: bytes) -> list[dict]:
    """Source-derived expectations; neither historical producer nor oracle imported."""
    root = etree.fromstring(raw_tei, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True))
    if root.tag != TEI + "TEI" or root.get(XML_ID) != WORK_ID + "-candidate":
        raise ValueError("Hitchcock root identity mismatch")
    texts = root.findall(TEI + "text")
    if len(texts) != 1 or texts[0].attrib != {XML_ID: WORK_ID + "-text", "type": "dictionary"} or len(texts[0]) != 1:
        raise ValueError("Hitchcock complete text envelope mismatch")
    body = texts[0][0]
    if body.tag != TEI + "body" or body.attrib != {XML_ID: WORK_ID + "-body"}:
        raise ValueError("Hitchcock body identity mismatch")
    lines = raw_source.splitlines(keepends=True)
    if len(lines) != 2622 or len(body) != 2622 or not raw_source.endswith(b"\n"):
        raise ValueError("Hitchcock complete record/body count mismatch")
    census: list[dict] = []
    for ordinal, (line, entry) in enumerate(zip(lines, body), 1):
        record = json.loads(line.decode("utf-8"), object_pairs_hook=unique_object)
        if list(record) != ["term", "definitions"] or not isinstance(record["term"], str):
            raise ValueError(f"Hitchcock source fields/order mismatch: {ordinal}")
        definitions = record["definitions"]
        if not isinstance(definitions, list) or len(definitions) != 1 or not all(isinstance(value, str) and value for value in definitions):
            raise ValueError(f"Hitchcock source definitions mismatch: {ordinal}")
        prefix = f"{WORK_ID}-entry-{ordinal:05d}"
        if entry.tag != TEI + "entry" or entry.attrib != {"n": str(ordinal), XML_ID: prefix} or [node.tag for node in entry] != [TEI + "form", TEI + "sense"]:
            raise ValueError(f"Hitchcock entry identity/hierarchy/order mismatch: {ordinal}")
        form, sense = entry
        if form.attrib or len(form) != 1 or form[0].tag != TEI + "orth" or form[0].attrib != {"type": "headword"} or len(form[0]) or form[0].text != record["term"]:
            raise ValueError(f"Hitchcock literal source term mismatch: {ordinal}")
        if sense.attrib != {XML_ID: prefix + "-sense"} or len(sense) != len(definitions):
            raise ValueError(f"Hitchcock sense attachment mismatch: {ordinal}")
        for number, (node, value) in enumerate(zip(sense, definitions), 1):
            if node.tag != TEI + "def" or node.attrib != {"n": str(number), XML_ID: f"{prefix}-definition-{number:03d}"} or len(node) or node.text != value:
                raise ValueError(f"Hitchcock literal definition/order mismatch: {ordinal}/{number}")
        for node in (body, entry, form, sense):
            if (node.text or "").strip():
                raise ValueError(f"Hitchcock invented framing text: {ordinal}")
        for node in entry.iter():
            if (node.tail or "").strip():
                raise ValueError(f"Hitchcock invented framing tail: {ordinal}")
        census.append({"id": prefix, "source_order": ordinal, "source_record_sha256": digest(line), "definition_count": len(definitions)})
    return census


def main() -> None:
    old = (HISTORICAL / "content.tei.xml").read_bytes()
    source = SOURCE.read_bytes()
    if digest(old) != OLD_SHA or digest(source) != SOURCE_SHA or len(source) != 164940:
        raise ValueError("Retained Hitchcock candidate/source drifted")
    manifest = json.loads((HISTORICAL / "manifest.json").read_text())
    for member in manifest["members"]:
        member_raw = (HISTORICAL / member["name"]).read_bytes()
        if len(member_raw) != member["bytes"] or digest(member_raw) != member["sha256"]:
            raise ValueError(f"Historical package member mismatch: {member['name']}")
    acquisition_path = WORK / f"forms/{FORM_ID}/editions/{EDITION_ID}/acquisitions/{ACQUISITION_ID}.json"
    acquisition = json.loads(io_path(acquisition_path).read_text(encoding="utf-8"))
    scope = acquisition["source_scope"]
    if len(acquisition["retained_files"]) != 1 or acquisition["retained_files"][0]["scope"] != scope:
        raise ValueError("Hitchcock acquisition member scope mismatch")
    census = verify_body(source, old)
    start, end = old.index(b"<teiHeader"), old.index(b"</teiHeader>") + len(b"</teiHeader>")
    tree = etree.fromstring(old)
    header = tree.find(TEI + "teiHeader")
    desc = header.find(TEI + "fileDesc/" + TEI + "sourceDesc")
    availability = header.find(TEI + "fileDesc/" + TEI + "publicationStmt/" + TEI + "availability")
    availability[0].text = (
        "Evidence-backed technical master of the complete retained electronic JSONL witness only. "
        "The structured JWBickel source license, print-edition identity, human textual review, "
        "and public publication authorization remain unresolved; no rights grant is implied."
    )
    binding = etree.SubElement(desc, TEI + "bibl", type="ocd-acceptance-binding")
    etree.SubElement(binding, TEI + "ptr", target=acquisition["url"])
    for key, value in {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID, "source_sha256": SOURCE_SHA, "source_bytes": str(len(source)), "representation_revision": REVISION, "sha256": SOURCE_SHA}.items():
        etree.SubElement(binding, TEI + "idno", type=key).text = value
    etree.SubElement(binding, TEI + "note", type="source-location").text = SOURCE.relative_to(ROOT).as_posix()
    etree.SubElement(binding, TEI + "note", type="source-scope").text = scope
    etree.SubElement(binding, TEI + "note", type="identity-and-rights-qualification").text = (
        "The source member and current catalog identify this electronic witness, not an independently established print edition. "
        "No author, editor, print publication date, source license, or bibliographic lineage is inferred. "
        "Historical rights-policy and review warnings remain preserved; current agent technical adoption does not settle them."
    )
    revision = etree.SubElement(header, TEI + "revisionDesc")
    change = etree.SubElement(revision, TEI + "change", when=datetime.now(timezone.utc).date().isoformat())
    change.set(XML_ID, REVISION)
    change.text = "Renew current electronic identity and technical scope bindings; conserve all 2,622 native records and definitions unchanged."
    fresh_header = etree.tostring(header, encoding="UTF-8", with_tail=False)
    fresh = old[:start] + fresh_header + old[end:]
    if old[end:] != fresh[fresh.index(b"</teiHeader>") + len(b"</teiHeader>"):] or etree.tostring(tree.find(TEI + "text")) != etree.tostring(etree.fromstring(fresh).find(TEI + "text")):
        raise ValueError("Hitchcock native text changed during header renewal")
    save(BASE / "candidate.tei.xml", fresh)
    save(BASE / "historical-header.xml", old[start:end])
    save(BASE / "fresh-header.xml", fresh_header)
    accounting = {"contract": "ocd-hitchcock-current-source-accounting-v1", "entry_kind": "dictionary-entry", "projection_context": {"entry_kind": "dictionary-entry", "source_selector": {"tei_entry_profile": "hitchcock-native-lexical-v1"}, "source_scope": scope, "source_unit_count": len(census), "source_selected_units": [item["id"] for item in census], "source_census": census, "source_excerpt_sha256": SOURCE_SHA}, "candidate_master_sha256": digest(fresh), "source_path": SOURCE.relative_to(ROOT).as_posix(), "source_sha256": SOURCE_SHA, "historical_crosswalk": {"path": (HISTORICAL / "source-accountability.json").relative_to(ROOT).as_posix(), "sha256": digest((HISTORICAL / "source-accountability.json").read_bytes())}, "technical_scope": "Whole retained JSONL witness; exact source field order, literal terms/definition blocks and duplicate occurrences. No print or rights claim."}
    save(BASE / "source-accounting.json", json_bytes(accounting))
    terms = [json.loads(line)["term"] for line in source.splitlines()]
    proof = {"status": "pass", "source_sha256": SOURCE_SHA, "source_bytes": len(source), "historical_candidate_sha256": OLD_SHA, "candidate_sha256": digest(fresh), "entry_count": 2622, "definition_count": 2622, "checked_observations": 5244, "native_body_bytes_identical": True, "parsed_text_tree_identical": True, "duplicate_terms": {term: count for term, count in Counter(terms).items() if count > 1}, "source_scope": scope, "method": "Independent JSONL decoding and exact lxml term/definition/IDs/attributes/hierarchy/order/framing checks; historical converter and oracle not imported.", "human_review": "unresolved", "rights_clearance": "unresolved", "publication_authorized": False}
    save(BASE / "source-proof.json", json_bytes(proof))
    notice = (
        "# Hitchcock's Bible Names Dictionary: retained electronic witness and credit\n\n"
        "This dataset is derived from the complete 2,622-record Hitchcock's Bible Names Dictionary JSONL member of "
        "[JWBickel/BibleDictionaries](https://huggingface.co/datasets/JWBickel/BibleDictionaries). "
        "All 2,622 ordered definition blocks, repeated headwords, literal whitespace, and citation-looking text are retained. "
        f"Source member: `raw/bible_dictionaries/hitchcocks.jsonl` (SHA-256 `{SOURCE_SHA}`).\n\n"
        "The retained member establishes an electronic witness. Its title does not independently establish an author, "
        "print edition, publication date, or bibliographic lineage. The historic work and modern JWBickel structured JSONL "
        "are distinct rights questions; the structured source's reuse license remains unresolved. "
        "Credit to JWBickel/BibleDictionaries records provenance without claiming permission or rights clearance. "
        "Historical source-policy warnings remain preserved. Technical adoption and private offline verification "
        "do not establish human textual approval or authorize public publication.\n"
    ).encode()
    save(BASE / "README.source.md", notice)
    save(BASE / "README.data.md", notice)
    pins = {}
    for path in (WORK / "work.json", WORK / "state.json", acquisition_path, SOURCE, ROOT / "raw/bible_dictionaries/manifest.json", HISTORICAL / "manifest.json", HISTORICAL / "content.tei.xml", ROOT / "sources" / WORK_ID / (WORK_ID + ".source-manifest.json")):
        pins[path.relative_to(ROOT).as_posix()] = digest(io_path(path).read_bytes())
    save(LOG / "preflight.json", json_bytes({"status": "pass", "identity": {"work_id": WORK_ID, "textual_form_id": FORM_ID, "edition_id": EDITION_ID, "acquisition_id": ACQUISITION_ID}, "current_owner": "Prayers", "preexisting_stage": "acquired", "physical_accepted_master": None, "historical_package_reused": True, "input_hashes": pins, "candidate_sha256": digest(fresh), "source_proof_sha256": digest(json_bytes(proof)), "remaining_technical_gap": "Exact Hitchcock native lexical profile support; prepared unapplied proposal. Current source/header/package/stage gates still separate."}))
    print(json.dumps({"status": "pass", "candidate_sha256": digest(fresh), "source_proof_sha256": digest(json_bytes(proof)), "entries": 2622, "definitions": 2622, "native_body_bytes_identical": True}))


if __name__ == "__main__":
    main()
