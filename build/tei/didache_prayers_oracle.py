"""Independent source-bound oracle for the LIB-066 Didache candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-didache-prayers-independent-source-oracle"
ORACLE_VERSION = "1"
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


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} duplicate key {key!r}")
            result[key] = value
        return result
    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _plain(value: str) -> str:
    value = _LINK_RE.sub(lambda match: match.group(2) or match.group(1), value)
    return re.sub(r"\s+", " ", _TAGS_RE.sub("", value)).strip()


def _mixed_content(value: str) -> list[dict[str, str]]:
    matches = list(_REF_RE.finditer(value))
    if not matches:
        return [{"kind": "text", "text": _plain(value)}]
    marked = []
    cursor = 0
    for match in matches:
        marked.append(value[cursor : match.start()])
        marked.append(_MIXED_MARKER)
        cursor = match.end()
    marked.append(value[cursor:])
    chunks = _plain("".join(marked)).split(_MIXED_MARKER)
    parts: list[dict[str, str]] = []
    for index, chunk in enumerate(chunks):
        if chunk:
            parts.append({"kind": "text", "text": chunk})
        if index < len(matches):
            parts.append({"kind": "note", "text": _plain(matches[index].group(1))})
    return parts


def _source_model(source: bytes) -> list[dict[str, object]]:
    record = _strict(source, "retained Didache JSON")
    parse = record.get("parse")
    if not isinstance(parse, dict) or parse.get("title") != "Didache (Lake translation)" or parse.get("pageid") != 191639:
        raise ValueError("Didache source metadata drifted")
    wikitext = parse.get("wikitext")
    if not isinstance(wikitext, dict) or not isinstance(wikitext.get("*"), str):
        raise ValueError("Didache wikitext witness is missing")
    text = wikitext["*"]
    matches = list(_CHAPTER_RE.finditer(text))
    chapters = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else text.index("==Original footnotes==")
        rows = []
        for row_match in _ROW_RE.finditer(text[match.end():end]):
            primary, label = row_match.groups()
            marker_matches = list(_VERSE_RE.finditer(primary))
            verses = []
            for marker_index, marker in enumerate(marker_matches):
                segment_end = marker_matches[marker_index + 1].start() if marker_index + 1 < len(marker_matches) else len(primary)
                segment = primary[marker.end():segment_end]
                parts = _mixed_content(segment)
                verses.append({"chapter": int(marker.group(1)), "verse": int(marker.group(2)), "text": "".join(item["text"] for item in parts if item["kind"] == "text"), "notes": [item["text"] for item in parts if item["kind"] == "note"], "parts": parts})
            rows.append({"label": _plain(label), "verses": verses})
        chapters.append({"roman": match.group(1), "number": index + 1, "rows": rows})
    if len(chapters) != 16 or sum(len(item["rows"]) for item in chapters) != 30 or sum(len(row["verses"]) for item in chapters for row in item["rows"]) != 100:
        raise ValueError("Didache source census drifted")
    return chapters


def _closure(root: Path) -> str:
    paths = {Path(__file__).resolve(strict=True), (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True), (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True)}
    records = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())]
    return _sha(_canonical(records))


def _actual_mixed_content(verse: etree._Element, expected: dict[str, object]) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = []
    if verse.text:
        parts.append({"kind": "text", "text": verse.text})
    expected_notes = expected["notes"]
    for note_number, note in enumerate(verse, 1):
        if note.tag != f"{{{_TEI}}}note" or note.get("type") != "footnote" or note.get("n") != str(note_number) or note.get(_XML_ID) != f"didache-c{expected['chapter']}-v-{expected['verse']}-fn-{note_number}" or len(note) != 0:
            raise ValueError("Didache inline footnote identity or structure drifted")
        if note.text is None:
            raise ValueError("Didache inline footnote text is missing")
        parts.append({"kind": "note", "text": note.text})
        if note.tail:
            parts.append({"kind": "text", "text": note.tail})
    if parts != expected["parts"]:
        raise ValueError("Didache inline footnote placement or visible text drifted")
    if [item["text"] for item in parts if item["kind"] == "note"] != expected_notes:
        raise ValueError("Didache inline footnote text drifted")
    return parts


def _tei_tag(name: str) -> str:
    return f"{{{_TEI}}}{name}"


def _assert_element(node: etree._Element, name: str, *, attributes: Mapping[str, str] | None = None, text: str | None = "") -> None:
    expected_attributes = {} if attributes is None else dict(attributes)
    if node.tag != _tei_tag(name) or dict(node.attrib) != expected_attributes or (text is not None and (node.text or "") != text) or (node.tail or "") != "":
        raise ValueError(f"Didache {name} element drifted")


def _assert_children(parent: etree._Element, names: list[str], label: str) -> None:
    if [child.tag for child in parent] != [_tei_tag(name) for name in names]:
        raise ValueError(f"Didache {label} child order drifted")


def _verify_tei(candidate: CandidatePackage, chapters: list[dict[str, object]], title: str) -> None:
    try:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    except etree.XMLSyntaxError as exc:
        raise ValueError("Didache TEI is not well-formed") from exc
    _assert_element(root, "TEI", attributes={_XML_ID: "didache-prayers-candidate"})
    _assert_children(root, ["teiHeader", "text"], "TEI")
    header = root[0]
    _assert_element(header, "teiHeader")
    _assert_children(header, ["fileDesc", "encodingDesc", "revisionDesc"], "teiHeader")
    file_desc = header[0]
    _assert_element(file_desc, "fileDesc")
    _assert_children(file_desc, ["titleStmt", "publicationStmt", "sourceDesc"], "fileDesc")
    title_stmt = file_desc[0]
    _assert_element(title_stmt, "titleStmt")
    _assert_children(title_stmt, ["title", "author", "respStmt"], "titleStmt")
    _assert_element(title_stmt[0], "title", text=title)
    _assert_element(title_stmt[1], "author", text="Unknown")
    resp_stmt = title_stmt[2]
    _assert_element(resp_stmt, "respStmt")
    _assert_children(resp_stmt, ["resp", "name"], "respStmt")
    _assert_element(resp_stmt[0], "resp", text="Translator")
    _assert_element(resp_stmt[1], "name", text="Kirsopp Lake")
    publication = file_desc[1]
    _assert_element(publication, "publicationStmt")
    _assert_children(publication, ["publisher", "availability"], "publicationStmt")
    _assert_element(publication[0], "publisher", text="Open Christian Data")
    availability = publication[1]
    _assert_element(availability, "availability", attributes={"status": "restricted"})
    _assert_children(availability, ["p"], "availability")
    _assert_element(availability[0], "p", text="Nonaccepted candidate; publication is not authorized.")
    source_desc = file_desc[2]
    _assert_element(source_desc, "sourceDesc")
    _assert_children(source_desc, ["bibl"], "sourceDesc")
    bibl = source_desc[0]
    _assert_element(bibl, "bibl")
    _assert_children(bibl, ["title", "title", "note", "idno", "idno"], "source bibl")
    _assert_element(bibl[0], "title", attributes={"type": "source-header"}, text="Didache, or Teaching of the Twelve Apostles")
    _assert_element(bibl[1], "title", text="Didache (Lake translation)")
    _assert_element(bibl[2], "note", attributes={"type": "source-header"}, text="For other translations, see Didache.")
    _assert_element(bibl[3], "idno", attributes={"type": "wikisource-pageid"}, text="191639")
    _assert_element(bibl[4], "idno", attributes={"type": "sha256"}, text=_SOURCE_SHA256)
    encoding = header[1]
    _assert_element(encoding, "encodingDesc")
    _assert_children(encoding, ["p"], "encodingDesc")
    _assert_element(encoding[0], "p", text="MediaWiki chapter tables, verse markers, side labels, and inline footnotes are represented in source order. Unsupported templates are accounted for in source-local evidence.")
    revision = header[2]
    _assert_element(revision, "revisionDesc", attributes={"status": "candidate"})
    _assert_children(revision, ["change"], "revisionDesc")
    _assert_element(revision[0], "change", attributes={"when": "2026-08-31"}, text="Generated as a nonaccepted source-bound candidate.")
    text_node = root[1]
    _assert_element(text_node, "text", attributes={_XML_ID: "didache-prayers-text"})
    _assert_children(text_node, ["body"], "text")
    body = text_node[0]
    _assert_element(body, "body")
    _assert_children(body, ["head"] + ["div"] * len(chapters) + ["div"], "body")
    _assert_element(body[0], "head", text="The Lord's teaching to the heathen by the Twelve Apostles.")
    titles = root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces={"t": _TEI})
    if len(titles) != 1 or titles[0].text != title:
        raise ValueError("Didache title identity drifted")
    source_titles = root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:title[@type='source-header']", namespaces={"t": _TEI})
    source_notes = root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:sourceDesc/t:bibl/t:note[@type='source-header']", namespaces={"t": _TEI})
    if len(source_titles) != 1 or source_titles[0].text != "Didache, or Teaching of the Twelve Apostles" or len(source_notes) != 1 or source_notes[0].text != "For other translations, see Didache.":
        raise ValueError("Didache source-header evidence drifted")
    divs = root.xpath("/t:TEI/t:text/t:body/t:div[@type='chapter']", namespaces={"t": _TEI})
    if len(divs) != len(chapters):
        raise ValueError("Didache chapter omission or duplication")
    seen: set[str] = set()
    for chapter, div in zip(chapters, divs):
        _assert_element(div, "div", attributes={"type": "chapter", "n": str(chapter["number"]), _XML_ID: f"didache-chapter-{chapter['number']}"})
        _assert_children(div, ["head"] + ["div"] * len(chapter["rows"]), f"chapter {chapter['number']}")
        _assert_element(div[0], "head", text=f"Chapter {chapter['roman']}")
        if div.tail:
            raise ValueError("Didache chapter order or identity drifted")
        rows = div.xpath("./t:div[@type='row']", namespaces={"t": _TEI})
        if len(rows) != len(chapter["rows"]):
            raise ValueError("Didache row omission or duplication")
        for row_index, (expected_row, row) in enumerate(zip(chapter["rows"], rows), 1):
            _assert_element(row, "div", attributes={"type": "row", "n": str(row_index), _XML_ID: f"didache-c{chapter['number']}-row-{row_index}"})
            _assert_children(row, ["ab"] * len(expected_row["verses"]) + ["note"], f"row {chapter['number']}.{row_index}")
            if row.tail:
                raise ValueError("Didache row order or identity drifted")
            verses = row.xpath("./t:ab[@type='verse']", namespaces={"t": _TEI})
            if len(verses) != len(expected_row["verses"]):
                raise ValueError("Didache verse omission or duplication")
            for expected, verse in zip(expected_row["verses"], verses):
                key = f"{expected['chapter']}.{expected['verse']}"
                if verse.get(_XML_ID) in seen:
                    raise ValueError("Didache verse order, identity, or visible text drifted")
                _assert_element(verse, "ab", attributes={"type": "verse", "n": key, _XML_ID: f"didache-c{expected['chapter']}-v-{expected['verse']}"}, text=None)
                seen.add(verse.get(_XML_ID) or "")
                _actual_mixed_content(verse, expected)
            labels = row.xpath("./t:note[@type='side-label']", namespaces={"t": _TEI})
            if len(labels) != 1:
                raise ValueError("Didache side-label drifted")
            _assert_element(labels[0], "note", attributes={"type": "side-label"}, text=str(expected_row["label"]))
    apparatus = body[-1]
    _assert_element(apparatus, "div", attributes={"type": "original-footnotes", _XML_ID: "didache-original-footnotes"})
    _assert_children(apparatus, ["head"], "original footnotes")
    _assert_element(apparatus[0], "head", text="Original footnotes")
    if len(seen) != 100:
        raise ValueError("Didache verse identity duplication")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify(); candidate.verify_integrity()
    if source_manifest.record.get("ticket_id") != "LIB-066" or source_manifest.record.get("work_id") != "didache-prayers":
        raise ValueError("Didache source identity drifted")
    converter = source_manifest.record.get("converter"); validator = source_manifest.record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("Didache callable bindings are invalid")
    manifest_path = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_manifest") != {"path": manifest_path, "sha256": source_manifest.sha256} or candidate.manifest.get("converter") != dict(converter) or candidate.manifest.get("package_schema") != dict(source_manifest.record["package_schema"]):
        raise ValueError("Didache candidate binding drifted")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes(); policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Didache profile"); policy = _strict(policy_bytes, "Didache policy")
    if profile.get("profile_id") != "didache-prayers-retained-wikisource-v1" or policy.get("policy_id") != "didache-prayers-retained-wikisource-policy-v1" or policy.get("oracle_id") != ORACLE_ID:
        raise ValueError("Didache profile or policy drifted")
    source = source_manifest.authority_path("retained-json").read_bytes()
    if len(source) != _SOURCE_BYTES or _sha(source) != _SOURCE_SHA256:
        raise ValueError("Didache retained source bytes drifted")
    chapters = _source_model(source)
    expected = {"contract": "ocd-didache-prayers-source-accountability-v1", "profile_id": profile["profile_id"], "work_id": "didache-prayers", "source_id": source_manifest.record["source_id"], "source_bytes": len(source), "source_sha256": _sha(source), "chapter_count": 16, "row_count": 30, "verse_count": 100, "footnote_count": sum(len(v["notes"]) for c in chapters for r in c["rows"] for v in r["verses"]), "side_label_count": 30, "unsupported_constructs": ["header", "chapter-template", "verse-template", "table-layout", "reflist", "translation-license", "category-link", "br"], "omitted_count": 0, "duplicate_count": 0, "unresolved_count": 3}
    account_bytes = candidate.member_bytes("source-accountability.json")
    if _strict(account_bytes, "Didache accountability") != expected or account_bytes != _canonical(expected):
        raise ValueError("Didache source accountability drifted")
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "Didache accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(expected), key=str)
    if errors: raise ValueError(f"Didache accountability schema failure: {errors[0].message}")
    _verify_tei(candidate, chapters, str(profile["identity"]["title"]))
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(etree.fromstring(candidate.member_bytes("content.tei.xml"))): raise ValueError(f"Didache TEI schema failure: {xsd.error_log}")
    authorities = {str(item["name"]): {key: item[key] for key in ("path", "bytes", "sha256", "role")} for item in source_manifest.record["authorities"]}
    expected_provenance = {"contract": "ocd-didache-prayers-candidate-provenance-v1", "status": "nonaccepted", "ticket_id": "LIB-066", "work_id": "didache-prayers", "source_id": source_manifest.record["source_id"], "source_manifest_sha256": source_manifest.sha256, "identity": profile["identity"], "rights": profile["rights"], "candidate_boundary": {"acceptance_status": "nonaccepted", "publication_status": "not-authorized", "canonical_data_or_ir_written": False}, "authorities": authorities}
    provenance = _strict(candidate.member_bytes("provenance.json"), "Didache provenance")
    if provenance != expected_provenance:
        raise ValueError("Didache provenance or metadata drifted")
    expected_unresolved = [
        {"id": "didache-prayers-identity-review", "status": "unresolved", "kind": "identity", "detail": "Human review is required for the Lake translation and bounded source identity."},
        {"id": "didache-prayers-rights-review", "status": "unresolved", "kind": "rights", "detail": "The source license templates require human rights accountability before publication."},
        {"id": "didache-prayers-human-acceptance", "status": "unresolved", "kind": "acceptance", "detail": "This candidate has not received human textual acceptance."},
    ]
    unresolved = [_strict(line, "Didache unresolved record") for line in candidate.member_bytes("unresolved.jsonl").splitlines() if line.strip()]
    if unresolved != expected_unresolved:
        raise ValueError("Didache unresolved ledger drifted")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes(): raise ValueError("Didache attribution evidence drifted")
    closure = _closure(source_manifest.repository_root)
    if closure != validator.get("import_closure_sha256"): raise ValueError("Didache oracle import closure drifted")
    result: dict[str, object] = {"status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION, "implementation_sha256": _sha(Path(__file__).read_bytes()), "import_closure_sha256": closure, "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})", "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256, "profile_sha256": _sha(profile_bytes), "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()), "source_sha256": _sha(source), "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()), "policy_sha256": _sha(policy_bytes), "findings": []}
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
