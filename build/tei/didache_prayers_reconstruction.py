"""Deterministic retained Wikisource JSON to TEI candidate route for LIB-066."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-didache-prayers-wikisource-json-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_SHA256 = "9ba0420fc2f1ef3d960335c100e31f8edbe7343b7fc5eab66dcce075744db764"
_SOURCE_BYTES = 23668
_CHAPTER_RE = re.compile(r"^==Chapter ([IVXLCDM]+)==\s*\n", re.MULTILINE)
_ROW_RE = re.compile(r"\|-valign=\"top\"\s*\n\|(.+?)\n\|<small>(.*?)</small>", re.DOTALL)
_VERSE_RE = re.compile(r"\{\{verse\|chapter=(\d+)\|verse=(\d+)\}\}")
_REF_RE = re.compile(r"<ref>(.*?)</ref>", re.DOTALL)
_TAGS_RE = re.compile(r"<[^>]+>")
_LINK_RE = re.compile(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]")
_MIXED_MARKER = "\ue000"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict(path: Path, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def load_manifest(path: str | Path, *, repository_root: str | Path) -> SourceManifest:
    return SourceManifest.load(path, repository_root=repository_root)


def _clean(value: str) -> str:
    value = _LINK_RE.sub(lambda match: match.group(2) or match.group(1), value)
    value = _TAGS_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def _mixed_content(value: str) -> list[dict[str, str]]:
    matches = list(_REF_RE.finditer(value))
    if not matches:
        return [{"kind": "text", "text": _clean(value)}]
    marked = []
    cursor = 0
    for match in matches:
        marked.append(value[cursor : match.start()])
        marked.append(_MIXED_MARKER)
        cursor = match.end()
    marked.append(value[cursor:])
    chunks = _clean("".join(marked)).split(_MIXED_MARKER)
    parts: list[dict[str, str]] = []
    for index, chunk in enumerate(chunks):
        if chunk:
            parts.append({"kind": "text", "text": chunk})
        if index < len(matches):
            parts.append({"kind": "note", "text": _clean(matches[index].group(1))})
    return parts


def _chapters(source: bytes) -> list[dict[str, object]]:
    text = json.loads(source.decode("utf-8"))["parse"]["wikitext"]["*"]
    if not isinstance(text, str):
        raise ValueError("Didache wikitext is not a string")
    matches = list(_CHAPTER_RE.finditer(text))
    chapters: list[dict[str, object]] = []
    for index, match in enumerate(matches):
        chapter = 0
        previous = 0
        for char in reversed(match.group(1)):
            value = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}[char]
            chapter += -value if value < previous else value
            previous = max(previous, value)
        end = matches[index + 1].start() if index + 1 < len(matches) else text.index("==Original footnotes==")
        rows = []
        for row_number, row_match in enumerate(_ROW_RE.finditer(text[match.end():end]), 1):
            primary, label = row_match.groups()
            verses = []
            verse_matches = list(_VERSE_RE.finditer(primary))
            for verse_index, verse_match in enumerate(verse_matches):
                segment_end = verse_matches[verse_index + 1].start() if verse_index + 1 < len(verse_matches) else len(primary)
                segment = primary[verse_match.end():segment_end]
                parts = _mixed_content(segment)
                verses.append({"chapter": int(verse_match.group(1)), "verse": int(verse_match.group(2)), "text": "".join(item["text"] for item in parts if item["kind"] == "text"), "notes": [item["text"] for item in parts if item["kind"] == "note"], "parts": parts})
            if not verses:
                raise ValueError("Didache row has no verse markers")
            if any(item["chapter"] != chapter for item in verses):
                raise ValueError("Didache verse chapter marker drifted")
            rows.append({"number": row_number, "label": _clean(label), "verses": verses})
        chapters.append({"number": chapter, "roman": match.group(1), "rows": rows})
    if [item["number"] for item in chapters] != list(range(1, 17)) or sum(len(item["rows"]) for item in chapters) != 30 or sum(len(row["verses"]) for item in chapters for row in item["rows"]) != 100:
        raise ValueError("Didache chapter, row, or verse census drifted")
    return chapters


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict(source_manifest.authority_path("reconstruction-profile"), "Didache profile")
    policy = _strict(source_manifest.authority_path("validation-policy"), "Didache policy")
    if profile.get("profile_id") != "didache-prayers-retained-wikisource-v1" or policy.get("policy_id") != "didache-prayers-retained-wikisource-policy-v1":
        raise ValueError("Didache profile or policy identity drifted")
    source = source_manifest.authority_path("retained-json").read_bytes()
    if len(source) != _SOURCE_BYTES or _sha(source) != _SOURCE_SHA256:
        raise ValueError("Didache retained JSON bytes drifted")
    chapters = _chapters(source)
    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "didache-prayers-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = str(profile["identity"]["title"])
    etree.SubElement(title_stmt, f"{{{_TEI}}}author").text = "Unknown"
    resp_stmt = etree.SubElement(title_stmt, f"{{{_TEI}}}respStmt")
    etree.SubElement(resp_stmt, f"{{{_TEI}}}resp").text = "Translator"
    etree.SubElement(resp_stmt, f"{{{_TEI}}}name").text = "Kirsopp Lake"
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    etree.SubElement(etree.SubElement(publication, f"{{{_TEI}}}availability", status="restricted"), f"{{{_TEI}}}p").text = "Nonaccepted candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{_TEI}}}bibl")
    etree.SubElement(bibl, f"{{{_TEI}}}title", type="source-header").text = "Didache, or Teaching of the Twelve Apostles"
    etree.SubElement(bibl, f"{{{_TEI}}}title").text = "Didache (Lake translation)"
    etree.SubElement(bibl, f"{{{_TEI}}}note", type="source-header").text = "For other translations, see Didache."
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="wikisource-pageid").text = "191639"
    etree.SubElement(bibl, f"{{{_TEI}}}idno", type="sha256").text = _SOURCE_SHA256
    etree.SubElement(header, f"{{{_TEI}}}encodingDesc").append(etree.Element(f"{{{_TEI}}}p"))
    header.xpath("./t:encodingDesc/t:p", namespaces={"t": _TEI})[0].text = "MediaWiki chapter tables, verse markers, side labels, and inline footnotes are represented in source order. Unsupported templates are accounted for in source-local evidence."
    revision = etree.SubElement(header, f"{{{_TEI}}}revisionDesc", status="candidate")
    etree.SubElement(revision, f"{{{_TEI}}}change", when="2026-08-31").text = "Generated as a nonaccepted source-bound candidate."
    text_node = etree.SubElement(root, f"{{{_TEI}}}text")
    text_node.set(_XML_ID, "didache-prayers-text")
    body = etree.SubElement(text_node, f"{{{_TEI}}}body")
    etree.SubElement(body, f"{{{_TEI}}}head").text = "The Lord's teaching to the heathen by the Twelve Apostles."
    for chapter in chapters:
        div = etree.SubElement(body, f"{{{_TEI}}}div", type="chapter", n=str(chapter["number"])); div.set(_XML_ID, f"didache-chapter-{chapter['number']}")
        etree.SubElement(div, f"{{{_TEI}}}head").text = f"Chapter {chapter['roman']}"
        for row in chapter["rows"]:
            row_node = etree.SubElement(div, f"{{{_TEI}}}div", type="row", n=str(row["number"])); row_node.set(_XML_ID, f"didache-c{chapter['number']}-row-{row['number']}")
            for verse in row["verses"]:
                ab = etree.SubElement(row_node, f"{{{_TEI}}}ab", type="verse", n=f"{verse['chapter']}.{verse['verse']}")
                ab.set(_XML_ID, f"didache-c{verse['chapter']}-v-{verse['verse']}")
                last: etree._Element | None = None
                for part_index, part in enumerate(verse["parts"]):
                    if part["kind"] == "text":
                        if last is None:
                            ab.text = part["text"]
                        else:
                            last.tail = part["text"]
                        continue
                    note_number = sum(1 for previous in verse["parts"][: part_index + 1] if previous["kind"] == "note")
                    note = etree.SubElement(ab, f"{{{_TEI}}}note", type="footnote", n=str(note_number)); note.set(_XML_ID, f"didache-c{verse['chapter']}-v-{verse['verse']}-fn-{note_number}"); note.text = part["text"]
                    last = note
            side = etree.SubElement(row_node, f"{{{_TEI}}}note", type="side-label"); side.text = str(row["label"])
    apparatus = etree.SubElement(body, f"{{{_TEI}}}div", type="original-footnotes"); apparatus.set(_XML_ID, "didache-original-footnotes")
    etree.SubElement(apparatus, f"{{{_TEI}}}head").text = "Original footnotes"
    accountability = {"contract": "ocd-didache-prayers-source-accountability-v1", "profile_id": profile["profile_id"], "work_id": "didache-prayers", "source_id": source_manifest.record["source_id"], "source_bytes": len(source), "source_sha256": _sha(source), "chapter_count": 16, "row_count": 30, "verse_count": 100, "footnote_count": 10, "side_label_count": 30, "unsupported_constructs": ["header", "chapter-template", "verse-template", "table-layout", "reflist", "translation-license", "category-link", "br"], "omitted_count": 0, "duplicate_count": 0, "unresolved_count": 3}
    provenance = {"contract": "ocd-didache-prayers-candidate-provenance-v1", "status": "nonaccepted", "ticket_id": "LIB-066", "work_id": "didache-prayers", "source_id": source_manifest.record["source_id"], "source_manifest_sha256": source_manifest.sha256, "identity": profile["identity"], "rights": profile["rights"], "candidate_boundary": {"acceptance_status": "nonaccepted", "publication_status": "not-authorized", "canonical_data_or_ir_written": False}}
    unresolved = ({"id": "didache-prayers-identity-review", "status": "unresolved", "kind": "identity", "detail": "Human review is required for the Lake translation and bounded source identity."}, {"id": "didache-prayers-rights-review", "status": "unresolved", "kind": "rights", "detail": "The source license templates require human rights accountability before publication."}, {"id": "didache-prayers-human-acceptance", "status": "unresolved", "kind": "acceptance", "detail": "This candidate has not received human textual acceptance."})
    authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in source_manifest.record["authorities"]}
    provenance["authorities"] = authorities
    return {"content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False), "source-accountability.json": _canonical(accountability), "provenance.json": _canonical(provenance), "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved), "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
