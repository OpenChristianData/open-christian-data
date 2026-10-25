"""Build a faithful, line-bound TEI candidate for Luther's Large Catechism."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-lib077-luthers-large-catechism-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
START_LINE = 30
END_LINE = 4536

_PART_RE = re.compile(r"^Part\s+(?:First|Second|Third|Fourth)\.", re.IGNORECASE)
_SECTION_RE = re.compile(
    r"^(?:PREFACE|SHORT PREFACE OF DR\. MARTIN LUTHER|"
    r"The\s+(?:First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\s+"
    r"(?:Commandment|Article|Petition|Sacrament)\.?|"
    r"Article\s+(?:I|II|III|IV|V|VI)\.?|"
    r"The\s+(?:Introduction|Conclusion|Close of the Commandments|Baptism)\.?|"
    r"OF\s+(?:THE\s+)?(?:BAPTISM|SACRAMENT(?:\s+OF\s+THE\s+ALTAR)?)\.?|"
    r"CONFESSION)$",
    re.IGNORECASE,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _q(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    path = source_manifest.authority_path("reconstruction-profile")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("work_id") != "luthers-large-catechism":
        raise ValueError("Large Catechism profile scope mismatch")
    return value


def _source(source_manifest: SourceManifest) -> tuple[bytes, list[bytes]]:
    members = source_manifest.record.get("source_members")
    if not isinstance(members, tuple) or len(members) != 1:
        raise ValueError("Large Catechism requires exactly one retained source member")
    member = members[0]
    if not isinstance(member, Mapping):
        raise ValueError("Large Catechism source member is invalid")
    path = source_manifest.repository_root / str(member["path"])
    content = path.read_bytes()
    if len(content) != int(member["bytes"]) or _sha(content) != str(member["sha256"]):
        raise ValueError("Large Catechism source member drifted")
    if not content.startswith(b"\xef\xbb\xbf") or not content.endswith(b"\r\n"):
        raise ValueError("Large Catechism source framing drifted")
    lines = content.split(b"\r\n")[:-1]
    if len(lines) != int(member["lines"]):
        raise ValueError("Large Catechism physical-line count drifted")
    return content, lines


def _decode(number: int, line: bytes) -> str:
    return line.decode("utf-8-sig" if number == 1 else "utf-8", errors="strict")


def _category(number: int) -> str:
    if number < START_LINE:
        return "gutenberg-header"
    if number == START_LINE:
        return "gutenberg-start-marker"
    if number < END_LINE:
        return "work-content"
    if number == END_LINE:
        return "gutenberg-end-marker"
    return "gutenberg-license"


def _kind(category: str, text: str) -> str:
    stripped = text.strip()
    if category in {"gutenberg-start-marker", "gutenberg-end-marker"}:
        return "marker"
    if category != "work-content":
        return "wrapper"
    if not stripped:
        return "blank"
    if _PART_RE.match(stripped):
        return "part"
    if _SECTION_RE.fullmatch(stripped):
        return "section"
    return "content"


def _records(content: bytes, lines: list[bytes]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    for number, line in enumerate(lines, 1):
        raw_record = line + b"\r\n"
        text = _decode(number, line)
        category = _category(number)
        kind = _kind(category, text)
        line_id = f"luthers-large-catechism-line-{number:05d}"
        records.append(
            {
                "id": line_id,
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(raw_record),
                "record_sha256": _sha(raw_record),
                "text_sha256": _sha(text.encode("utf-8")),
                "category": category,
                "kind": kind,
                "disposition": "represented",
                "target": f"#{line_id}",
                "text": text,
            }
        )
        offset += len(raw_record)
    if offset != len(content):
        raise ValueError("Large Catechism source byte accounting does not close")
    return records


def _node(parent: etree._Element, name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    node = etree.SubElement(parent, _q(name))
    for key, value in (attrs or {}).items():
        node.set(f"{{{XML_NS}}}id" if key == "xml:id" else key, value)
    node.text = text
    return node


def _tei(profile: Mapping[str, object], records: list[dict[str, object]]) -> bytes:
    root = etree.Element(_q("TEI"), nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", "luthers-large-catechism-candidate")
    header = _node(root, "teiHeader")
    file_desc = _node(header, "fileDesc")
    title_stmt = _node(file_desc, "titleStmt")
    _node(title_stmt, "title", text=str(profile["title"]))
    _node(title_stmt, "author", text=str(profile["creator"]))
    resp_stmt = _node(title_stmt, "respStmt")
    _node(resp_stmt, "resp", text="Exact physical-line transcription")
    _node(resp_stmt, "name", text="Open Christian Data")
    publication = _node(file_desc, "publicationStmt")
    _node(publication, "publisher", text="Open Christian Data")
    availability = _node(publication, "availability", {"status": "restricted"})
    _node(availability, "p", text="Nonaccepted candidate; technical validation is not human acceptance or publication authorization.")
    source_desc = _node(file_desc, "sourceDesc")
    bibl = _node(source_desc, "bibl")
    _node(bibl, "title", text=str(profile["title"]))
    _node(bibl, "author", text=str(profile["creator"]))
    _node(bibl, "note", {"type": "contributor-statement"}, str(profile["contributor_statement"]))
    _node(bibl, "idno", {"type": "URI"}, str(profile["source_url"]))
    _node(bibl, "idno", {"type": "SHA-256"}, str(profile["source_sha256"]))
    _node(bibl, "extent", text=f"{profile['source_bytes']} bytes; {profile['physical_lines']} UTF-8 CRLF physical lines")
    project_desc = _node(_node(header, "encodingDesc"), "projectDesc")
    _node(project_desc, "p", text="Every retained physical line is represented exactly once, verbatim after BOM and CRLF framing removal, and in source order.")
    _node(project_desc, "p", text="Source header, Gutenberg markers, work content, and license/support material remain separately classified.")
    _node(_node(header, "revisionDesc"), "change", {"status": "candidate"}, "Deterministic nonaccepted LIB-077 candidate generated from the pinned Project Gutenberg witness.")

    transcription = _node(_node(_node(root, "text"), "body"), "div", {"xml:id": "luthers-large-catechism-retained-lines", "type": "catechism", "subtype": "gutenberg-source-transcription"})
    current_part: etree._Element | None = None
    current_section: etree._Element | None = None
    for record in records:
        kind = str(record["kind"])
        number = int(record["line"])
        if kind == "part":
            current_part = _node(transcription, "div", {"xml:id": f"part-{number:05d}", "type": "part"})
            current_section = None
        elif kind == "section":
            parent = current_part if current_part is not None else transcription
            current_section = _node(parent, "div", {"xml:id": f"section-{number:05d}", "type": "section"})
        parent = current_section if current_section is not None else current_part if current_part is not None else transcription
        line_div = _node(parent, "div", {"xml:id": str(record["id"]), "type": "source-line", "n": str(number)})
        carrier_name = "head" if kind in {"part", "section"} else "ab"
        _node(line_div, carrier_name, {"xml:id": str(record["id"]) + "-carrier", "n": str(number), "type": kind, "ana": f"#source-line #{record['category']} #{kind}"}, str(record["text"]))
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    profile = _profile(source_manifest)
    content, lines = _source(source_manifest)
    records = _records(content, lines)
    source_member = source_manifest.record["source_members"][0]
    census = [{"path": source_member["path"], "bytes": source_member["bytes"], "sha256": source_member["sha256"], "included": True, "reason": "The current LIB-077 manifest binds this sole exact retained Gutenberg member."}]
    crosswalk = [{key: value for key, value in record.items() if key != "text"} for record in records]
    accountability = {
        "contract": "ocd-lib077-source-accountability-v1",
        "work_id": "luthers-large-catechism",
        "source_sha256": str(source_member["sha256"]),
        "source_bytes": len(content),
        "physical_lines": len(lines),
        "represented_lines": len(lines),
        "omitted_lines": 0,
        "duplicated_lines": 0,
        "member_census": census,
        "excluded_members": [],
        "crosswalk_sha256": _sha(_canonical(crosswalk)),
        "crosswalk": crosswalk,
    }
    provenance = {
        "contract": "ocd-lib077-provenance-v1",
        "work_id": "luthers-large-catechism",
        "title": profile["title"],
        "creator": profile["creator"],
        "contributor_statement": profile["contributor_statement"],
        "source_format": "Project Gutenberg UTF-8 text with BOM and CRLF framing",
        "source_url": profile["source_url"],
        "source_sha256": profile["source_sha256"],
        "candidate_status": "nonaccepted",
        "publication_authorized": False,
        "technical_validation_is_human_acceptance": False,
        "rights": {"retained_statement": "Project Gutenberg wrapper states a United States public-domain basis and requires users outside the United States to check local law and the included license.", "worldwide": "unresolved", "publication": "not authorized"},
    }
    unresolved = [
        {"id": "luthers-large-catechism-identity", "kind": "identity", "status": "human-review-required", "scope": "title, creator, and contributor roles", "detail": "Retained header role assertions are preserved but not human-accepted."},
        {"id": "luthers-large-catechism-edition", "kind": "edition-witness", "status": "human-review-required", "scope": "whole retained Gutenberg witness", "detail": "Edition and witness identity remain unaccepted."},
        {"id": "luthers-large-catechism-readings", "kind": "substantive-reading-editorial", "status": "human-review-required", "scope": "all retained physical lines", "detail": "No silent correction, modernization, or editorial acceptance was performed."},
        {"id": "luthers-large-catechism-rights", "kind": "rights", "status": "human-review-required", "scope": "jurisdiction, Project Gutenberg license, and trademark terms", "detail": "Worldwide rights and publication permission remain unresolved."},
        {"id": "luthers-large-catechism-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance or publication authorization."},
    ]
    return {
        "content.tei.xml": _tei(profile, records),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": source_manifest.authority_path("source-readme").read_bytes(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(source_manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(source_manifest, destination, _convert)

