"""Independent lxml observer for accepted OEB US/Cth witness rows."""

from __future__ import annotations

from collections import Counter
import copy
from hashlib import sha256
import re
from urllib.parse import unquote

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import make_row, row_text_hash
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets_check import observe_explicit_target
from ocd_kernel.projection.categories import bible
from .oeb_native_bible import (
    BOOK_CODES, CONTINUATIONS, IDENTITY, MASTER_SHA, N, REVISION, SOURCE_SHA,
    WITNESSES, X,
)


def _text(node, *, notes: bool = False) -> str:
    """Re-read visible source text with lxml; omitted note text stays separate."""
    def raw(current) -> str:
        chunks = [current.text or ""]
        for child in current:
            if child.tag == N + "note" and not notes or child.tag in {N + "ptr", N + "milestone"}:
                pass
            else:
                chunks.append(raw(child))
            chunks.append(child.tail or "")
        return "".join(chunks)

    return " ".join(raw(node).split())


def _note_values(node) -> list[dict[str, str]]:
    values = []
    for child in node.iter(N + "note"):
        if child.get("type") == "usfm-footnote":
            values.append({"text": _text(child, notes=True), "place": child.get("place", "unspecified"),
                           "label": child.get("n", "")})
        elif child.get("type") != "source-usfm-raw":
            raise PipelineError("OEB independent observer found unsupported verse note")
    return values


def _observe(path, metadata):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != MASTER_SHA:
        raise PipelineError("OEB independent observer master digest differs")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False)
    doc = etree.fromstring(raw, parser=parser)
    if doc.getroottree().docinfo.doctype or doc.xpath("//comment() | //processing-instruction()"):
        raise PipelineError("OEB independent observer found declaration or comment")
    paths = {doc: "/TEI[1]"}
    for parent in doc.iter():
        names = Counter()
        for child in parent:
            name = etree.QName(child).localname
            names[name] += 1
            paths[child] = f"{paths[parent]}/{name}[{names[name]}]"
    ns = {"t": bible.TEI_NS}
    header = bible._checker_header(doc, {})
    bible._validate_accepted_header(header, metadata)
    expected_label = bible._checker_accepted_versification(header, metadata)
    if expected_label != f"source-native:retained-member-set:{SOURCE_SHA}":
        raise PipelineError("OEB independent observer versification source differs")
    public_label = f"source-native:retained-member-set:{IDENTITY['edition_id']}:{REVISION}"
    if doc.tag != N + "TEI" or [child.tag for child in doc] != [N + "teiHeader", N + "text"]:
        raise PipelineError("OEB independent observer TEI root differs")
    branches = doc.xpath("./t:text/t:group/t:text", namespaces=ns)
    if len(branches) != 2 or len(doc.xpath("./t:text/t:group", namespaces=ns)) != 1:
        raise PipelineError("OEB independent observer witness group differs")
    accepted_members = metadata["acceptance"]["scope"]["included_members"]
    expected_members = []
    for item in accepted_members:
        match = re.fullmatch(r"raw/ebible/open-english-bible-2025\.6/(US|Cth)/usfm/usfm/([^/]+\.usfm)", item["path"])
        if match is None:
            raise PipelineError("OEB independent observer accepted member path differs")
        expected_members.append((match.group(1), match.group(2)))
    observed_members = []
    rows, anchors = [], []
    counts = Counter()
    book_codes = load_book_codes(BOOK_CODES_PATH)
    for branch, witness in zip(branches, WITNESSES, strict=True):
        if (dict(branch.attrib) != {"type": "witness", "n": witness,
                                    X: f"oeb-2025-6-{witness.lower()}"}
                or len(branch) != 1 or branch[0].tag != N + "body"):
            raise PipelineError(f"OEB independent observer {witness} witness identity differs")
        body = branch[0]
        if len(body) != 45:
            raise PipelineError(f"OEB independent observer {witness} member count differs")
        for unit in body:
            if unit.tag != N + "div" or unit.get("type") not in {"book", "front-matter"}:
                raise PipelineError("OEB independent observer member carrier differs")
            match = re.fullmatch(r"source-usfm:(US|Cth)/([^/#]+)", unit.get("corresp") or "")
            if match is None or match.group(1) != witness:
                raise PipelineError("OEB independent observer member source pointer differs")
            observed_members.append((witness, unquote(match.group(2))))
            counts[unit.get("type")] += 1
            if unit.get("type") == "front-matter":
                continue
            code = unit.get("n")
            if code not in BOOK_CODES or unit.get(X) != f"{witness}-{code}":
                raise PipelineError("OEB independent observer book identity differs")
            osis = BOOK_CODES[code]
            if osis not in book_codes:
                raise PipelineError("OEB independent observer book normalization differs")
            verse_ids = {}
            for chapter in unit.xpath(".//t:div[@type='chapter']", namespaces=ns):
                chapter_label = chapter.get("n") or ""
                if not re.fullmatch(r"[1-9][0-9]*", chapter_label):
                    raise PipelineError("OEB independent observer chapter label differs")
                counts["chapters"] += 1
                preceding = None
                for child in chapter.iter():
                    if child.tag != N + "ab":
                        continue
                    if child.get("type") == "verse":
                        label = child.get("n") or ""
                        if not re.fullmatch(r"[1-9][0-9]*", label):
                            raise PipelineError("OEB independent observer verse label differs")
                        wording = _text(child)
                        notes = _note_values(child)
                        if not wording:
                            if (len(child) != 1 or child[0].tag != N + "note"
                                    or child[0].get("type") != "usfm-footnote" or not notes):
                                raise PipelineError("OEB independent observer blank verse differs")
                            counts["blank_footnote_verses"] += 1
                        sequence = len(rows) + 1
                        locator = {"kind": "verse", "book": code, "book_osis": osis,
                                   "chapter": int(chapter_label), "verse": label,
                                   "versification": public_label, "source_order": sequence,
                                   "witness": witness, "reference_origin": "tei-verse-components"}
                        try:
                            locator["reference"] = observe_explicit_target(
                                f"{osis}.{chapter_label}.{label}", book_codes=book_codes)
                        except PipelineError:
                            locator["reference_status"] = "unsupported-verse-components"
                        else:
                            locator["reference_status"] = "normalized-verse-components"
                        record_id = f"{IDENTITY['edition_id']}:{witness}:verse-{sequence:06d}"
                        row = make_row(record_id=record_id, sequence=sequence, **IDENTITY,
                                       category="bible", language="en", text=wording,
                                       locator=locator, provenance={"edition_title": metadata["edition"].title},
                                       representation_revision=REVISION)
                        row.update(notes=notes, references=[], versification=public_label)
                        rows.append(row)
                        anchors.append({"record_id": record_id,
                                        "tei_path": paths[child],
                                        "text_sha256": row_text_hash(wording),
                                        "source_order": sequence, "locator": copy.deepcopy(locator)})
                        if not child.get(X) or child.get(X) in verse_ids:
                            raise PipelineError("OEB independent observer verse XML IDs differ")
                        verse_ids[child.get(X)] = sequence - 1
                        preceding = sequence - 1
                        counts["verses"] += 1
                    elif child.get("type") in CONTINUATIONS:
                        wording = _text(child)
                        if wording:
                            if preceding is None:
                                raise PipelineError("OEB independent observer unbound continuation")
                            target_index = preceding
                            if child.get("type") == "source-continuation":
                                pointers = child.xpath("./t:ptr[@type='preceding-verse']", namespaces=ns)
                                if len(pointers) != 1 or not re.fullmatch(
                                    rf"#{witness}-[A-Z0-9]+-line-[1-9][0-9]*", pointers[0].get("target") or ""
                                ):
                                    raise PipelineError("OEB independent observer continuation pointer differs")
                                target_index = verse_ids.get(pointers[0].get("target")[1:], -1)
                                if target_index < 0 or rows[target_index]["locator"]["chapter"] != int(chapter_label):
                                    raise PipelineError("OEB independent observer continuation target differs")
                            row = rows[target_index]
                            row["text"] = " ".join((row["text"], wording)).strip()
                            row["notes"].extend(_note_values(child))
                            anchors[target_index]["text_sha256"] = row_text_hash(row["text"])
                            counts["continuation_blocks"] += 1
                    elif _text(child):
                        raise PipelineError("OEB independent observer found unaccounted nonverse wording")
            for node in unit.iter():
                pointer = node.get("corresp")
                if pointer is not None and not pointer.startswith(f"source-usfm:{witness}/"):
                    raise PipelineError("OEB independent observer source pointer crosses witness")
    if observed_members != expected_members or len(set(observed_members)) != 90:
        raise PipelineError("OEB independent observer source member order differs")
    if counts != Counter({"book": 88, "front-matter": 2, "chapters": 1130,
                          "verses": 27828, "continuation_blocks": 12164,
                          "blank_footnote_verses": 38}):
        raise PipelineError(f"OEB independent observer carrier inventory differs: {counts}")
    inventory = {"witnesses": 2, "textual_members": 90, "books": 88, "front_members": 2,
                 "chapters": 1130, "verses": 27828, "continuation_blocks": 12164,
                 "blank_footnote_verses": 38, "nonverse_carriers": {"front-member": 2}}
    projection = {"mapping_version": "ocd-oeb-two-witness-source-native-v1",
                  "assembler_version": bible.ASSEMBLER_VERSION, "master_sha256": MASTER_SHA,
                  "scope_id": None, "rows": rows, "anchors": anchors, "inventory": inventory,
                  "references": [], "warnings": [{"reason": "Source US/Cth witnesses remain distinct; headings, front pages, source markers, and electronic support remain in accepted master."},
                                                 {"reason": "38 source-native footnote-only verse carriers retain their source footnotes."}],
                  "exclusions": [{"reason": "nonverse source carriers retained in accepted master", "counts": {"front-member": 2}}],
                  "unsupported": [], "source_binding": bible._source_binding(header),
                  "authority": copy.deepcopy(metadata["authority"])}
    return projection


def check_document(path, rows, receipt, *, metadata) -> list[str]:
    try:
        expected = _observe(path, metadata)
        if rows != expected["rows"]:
            raise PipelineError("OEB independent source-derived row fields, witness, or order differ")
        bible._validate_rows(rows)
        wanted = bible.build_bible_receipt(expected, identity=IDENTITY,
                                           authority=metadata["authority"])
        if receipt != wanted:
            raise PipelineError("OEB independent source-derived receipt differs")
        return []
    except (PipelineError, OSError, KeyError, TypeError, ValueError,
            etree.XMLSyntaxError) as exc:
        return [str(exc)]
