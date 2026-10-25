"""Independent lxml observer for exact accepted WEB Classic verse rows."""

from __future__ import annotations

from collections import Counter
import copy
from hashlib import sha256
import json
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.envelope import make_row, row_text_hash
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets_check import observe_explicit_target
from ocd_kernel.projection.categories import bible
from .web_classic_native_bible import (
    CAPTION, CONTINUATIONS, EMPTY_MARKERS, HEADING, IDENTITY, MAPPING_VERSION,
    MASTER_SHA, N, REVISION, SOURCE_SHA, X,
)


class _Paths(dict):
    def __missing__(self, node):
        return node.get("corresp") or node.get(X) or etree.QName(node).localname


def _paths(body):
    paths = _Paths()
    for number, member in enumerate(body, 1):
        base = f"/TEI[1]/text[1]/body[1]/div[{number}]"
        counts = Counter()
        for child in member:
            kind = etree.QName(child).localname
            counts[kind] += 1
            label = f"{base}/{kind}[{counts[kind]}]"
            if kind == "ab":
                paths[child] = label
            elif kind == "div":
                inner = Counter()
                for line in child:
                    tag = etree.QName(line).localname
                    inner[tag] += 1
                    paths[line] = f"{label}/{tag}[{inner[tag]}]"
    return paths


def _members(body, metadata):
    included = metadata["acceptance"]["scope"]["included_members"]
    if len(included) != 83 or len(body) != 83:
        raise PipelineError("WEB Classic independent member count differs")
    for source, section in zip(included, body, strict=True):
        filename = Path(source["path"]).name
        match = re.fullmatch(r"[0-9]+-([A-Z0-9]+)eng-web\.usfm", filename)
        if (match is None or section.tag != N + "div" or section.get("n") != match.group(1)
                or section.get(X) != "web-" + match.group(1)
                or section.get("type") != ("paratext" if match.group(1) in {"FRT", "GLO"} else "book")
                or section.get("corresp") != "source-usfm:eng-web/" + filename):
            raise PipelineError(f"WEB Classic independent member crosswalk differs: {filename}")
        yield filename, section


def _visible(line, paths, policy):
    try:
        return bible._checker_render(line, paths, policy=policy), False
    except bible.UnsupportedStructure as exc:
        if "omitted inline boundary" not in str(exc):
            raise
    marker = "\x00"

    def read(node):
        text = node.text or ""
        if node.tag == N + "seg" and node.get("type") == "usfm-qs" and ("\\" in text or "|" in text):
            match = re.fullmatch(r'(\s*)\\\+w\s+([^\\|]+)\|strong="[HG][0-9]+"\\\+w\*(\s*)', text)
            if match is None or not match.group(2).strip():
                raise PipelineError("WEB Classic independent unsupported quoted word")
            text = "".join(match.groups())
        chunks = [text]
        for child in node:
            chunks.append(marker if child.tag == N + "note" else read(child))
            chunks.append(child.tail or "")
        return "".join(chunks)

    raw = read(line)
    clean = []
    for index, char in enumerate(raw):
        if char == marker:
            if index and index + 1 < len(raw) and raw[index - 1].isalnum() and raw[index + 1].isalnum():
                clean.append(" ")
        else:
            clean.append(char)
    return " ".join("".join(clean).split()), True


def _observe(path: Path, metadata: dict) -> dict:
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != MASTER_SHA:
        raise PipelineError("WEB Classic independent master digest differs")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False)
    doc = etree.fromstring(raw, parser=parser)
    if doc.getroottree().docinfo.doctype or doc.xpath("//comment() | //processing-instruction()"):
        raise PipelineError("WEB Classic independent master contains unsupported declaration or comment")
    if doc.tag != N + "TEI":
        raise PipelineError("WEB Classic independent single TEI root differs")
    body = doc.find(N + "text/" + N + "body")
    if body is None or len(doc.findall(N + "text")) != 1:
        raise PipelineError("WEB Classic independent body differs")
    paths = _paths(body)
    header = bible._checker_header(doc, {})
    bible._validate_accepted_header(header, metadata)
    bible._checker_validate_accepted_member_set(doc, header, metadata)
    source_native = bible._checker_accepted_versification(header, metadata)
    if source_native != "source-native:retained-member-set:" + SOURCE_SHA:
        raise PipelineError("WEB Classic independent source-native label differs")
    public_label = f"source-native:retained-member-set:{IDENTITY['edition_id']}:{REVISION}"
    policy = json.loads(bible.COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
    known_books = load_book_codes(BOOK_CODES_PATH)
    rows, anchors = [], []
    line_types, note_types, inline_tags, excluded, attached = Counter(), Counter(), Counter(), Counter(), Counter()
    words = chapters = blanks = note_boundaries = 0
    raw_hash, strong_hash = sha256(), sha256()
    for filename, section in _members(body, metadata):
        all_lines = [element for element in section.iter(N + "ab")]
        for line_number, line in enumerate(all_lines, 1):
            pointer = f"source-usfm:eng-web/{filename}#line={line_number}"
            if (line.get("corresp") != pointer or len(line) < 1 or line[0].tag != N + "note"
                    or line[0].get("type") != "source-usfm-raw" or not (line[0].text or "").startswith("\\")):
                raise PipelineError(f"WEB Classic independent raw source line differs: {pointer}")
            line_types[line.get("type")] += 1
            raw_hash.update(json.dumps([pointer, line[0].text], ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            for node in line.iter():
                kind = etree.QName(node).localname
                if kind == "note":
                    note_types[node.get("type") or ""] += 1
                elif kind in {"term", "title"}:
                    inline_tags[kind] += 1
                elif kind == "w":
                    words += 1
                    strong = node.get("n") or ""
                    if node.get("type") not in {"w", "+w"} or not re.fullmatch(r"[HG][0-9]+(?:[ ,;/]+[HG][0-9]+)*", strong):
                        raise PipelineError("WEB Classic independent Strong annotation differs")
                    strong_hash.update(json.dumps([pointer, node.get("type"), strong, "".join(node.itertext())], ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        if section.get("type") == "paratext":
            excluded["paratext-member"] += 1
            continue
        code = section.get("n")
        for part in section:
            if part.tag == N + "ab":
                excluded[part.get("type") or "untyped"] += 1
                continue
            if part.tag != N + "div" or part.get("type") != "chapter":
                raise PipelineError("WEB Classic independent book-child shape differs")
            chapter = part.get("n") or ""
            if not re.fullmatch(r"[1-9][0-9]*", chapter):
                raise PipelineError("WEB Classic independent chapter label differs")
            chapters += 1
            last = None
            for line in part:
                if line.tag != N + "ab":
                    raise PipelineError("WEB Classic independent chapter child differs")
                kind = line.get("type") or ""
                visible, repaired_boundary = _visible(line, paths, policy)
                note_boundaries += repaired_boundary
                if kind == "verse":
                    label = line.get("n") or ""
                    if not re.fullmatch(r"[1-9][0-9]*(?:-[1-9][0-9]*)?", label):
                        raise PipelineError("WEB Classic independent verse label differs")
                    notes = [{"text": bible._checker_render(note, paths, omit_notes=False, policy=policy),
                              "place": note.get("place", "unspecified"), "label": note.get("n", "")}
                             for note in line.iter(N + "note") if note.get("type") != "source-usfm-raw"]
                    if not visible:
                        if not notes:
                            raise PipelineError("WEB Classic independent blank verse without source note")
                        blanks += 1
                    seq = len(rows) + 1
                    locator = {"kind": "verse", "book": code, "book_osis": section.get(X),
                               "chapter": int(chapter), "verse": label,
                               "versification": public_label, "source_order": seq,
                               "reference_origin": "tei-verse-components"}
                    try:
                        locator["reference"] = observe_explicit_target(f"{section.get(X)}.{chapter}.{label}", book_codes=known_books)
                    except (ValueError, TypeError):
                        locator["reference_status"] = "unsupported-verse-components"
                    else:
                        locator["reference_status"] = "normalized-verse-components"
                    record_id = f"{IDENTITY['edition_id']}:verse-{seq:06d}"
                    row = make_row(record_id=record_id, sequence=seq, **IDENTITY,
                                   category="bible", language="en", text=visible, locator=locator,
                                   provenance={"edition_title": metadata["edition"].title},
                                   representation_revision=REVISION)
                    row.update(notes=notes, references=[], versification=public_label)
                    rows.append(row)
                    anchors.append({"record_id": record_id, "tei_path": paths[line],
                                    "text_sha256": row_text_hash(visible), "source_order": seq,
                                    "locator": copy.deepcopy(locator)})
                    last = seq - 1
                elif kind in CONTINUATIONS and visible:
                    if last is None:
                        if (code, chapter, line.get("corresp"), visible) == CAPTION:
                            excluded["sirach-51-opening-caption"] += 1
                            continue
                        raise PipelineError("WEB Classic independent orphan continuation")
                    row = rows[last]
                    row["text"] = " ".join((row["text"], visible)).strip()
                    row["notes"].extend(
                        {"text": bible._checker_render(note, paths, omit_notes=False, policy=policy),
                         "place": note.get("place", "unspecified"), "label": note.get("n", "")}
                        for note in line.iter(N + "note") if note.get("type") != "source-usfm-raw")
                    anchors[last]["text_sha256"] = row_text_hash(row["text"])
                    attached[kind] += 1
                elif kind in HEADING or kind in EMPTY_MARKERS or kind in CONTINUATIONS:
                    excluded[kind] += 1
                else:
                    raise PipelineError("WEB Classic independent unaccounted source line")
    if (len(rows) != 38058 or chapters != 1402 or sum(line_types.values()) != 74297
            or words != 677690 or note_types["source-usfm-raw"] != 74297
            or inline_tags != Counter({"term": 94, "title": 47})):
        raise PipelineError("WEB Classic independent complete source inventory differs")
    inventory = {"source_members": 83, "source_lines": 74297, "verses": 38058,
                 "word_annotations": words, "line_types": dict(sorted(line_types.items())),
                 "note_types": dict(sorted(note_types.items())),
                 "inline_tags": dict(sorted(inline_tags.items())),
                 "raw_line_ledger_sha256": raw_hash.hexdigest(),
                 "strong_annotation_ledger_sha256": strong_hash.hexdigest(),
                 "chapters": chapters, "continuation_blocks": sum(attached.values()),
                 "continuation_types": dict(sorted(attached.items())),
                 "blank_note_verses": blanks, "note_boundary_spaces": note_boundaries,
                 "nonverse_carriers": dict(sorted(excluded.items()))}
    return {"mapping_version": MAPPING_VERSION, "assembler_version": bible.ASSEMBLER_VERSION,
            "master_sha256": MASTER_SHA, "scope_id": None, "rows": rows, "anchors": anchors,
            "inventory": inventory, "references": [],
            "warnings": [{"reason": "Verse rows include all visible source paragraph and poetry continuations; source headings, two paratext members, and exact private USFM/Strong markup remain in accepted master."}],
            "exclusions": [{"reason": "nonverse source carriers retained in accepted master", "counts": inventory["nonverse_carriers"]}],
            "unsupported": [], "source_binding": bible._source_binding(header),
            "authority": copy.deepcopy(metadata["authority"])}


def check_document(path: Path, rows, receipt, *, metadata: dict) -> list[str]:
    try:
        expected = _observe(path, metadata)
        if rows != expected["rows"]:
            raise PipelineError("WEB Classic independent source-derived verse text, continuation, notes, or order differ")
        bible._validate_rows(rows)
        wanted = bible.build_bible_receipt(expected, identity=IDENTITY, authority=metadata["authority"])
        if receipt != wanted:
            raise PipelineError("WEB Classic independent source-derived receipt or private inventory differs")
        return []
    except (PipelineError, OSError, KeyError, TypeError, ValueError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
