"""Build a faithful, line-bound TEI candidate for Schaff History volume 5."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct


CONVERTER_ID = "ocd-lib058-schaff-history-vol5-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
_STRUCTURAL_START_RE = re.compile(r"^<(?:ThML|ThML\.head|ThML\.body|div[123])(?:\s|>)", re.IGNORECASE)
_STRUCTURAL_END_RE = re.compile(r"^</(?:ThML|ThML\.head|ThML\.body|div[123])>", re.IGNORECASE)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _q(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _node(parent: etree._Element, name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    node = etree.SubElement(parent, _q(name))
    for key, value in (attrs or {}).items():
        node.set(f"{{{XML_NS}}}id" if key == "xml:id" else key, value)
    node.text = text
    return node


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    value = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if not isinstance(value, dict) or value.get("work_id") != "schaff-history-vol-5":
        raise ValueError("Schaff volume 5 profile scope mismatch")
    return value


def _source(source_manifest: SourceManifest) -> tuple[bytes, list[bytes], Mapping[str, object]]:
    members = source_manifest.record.get("source_members")
    if not isinstance(members, tuple) or len(members) != 1 or not isinstance(members[0], Mapping):
        raise ValueError("Schaff volume 5 requires exactly one retained source member")
    member = members[0]
    content = (source_manifest.repository_root / str(member["path"])).read_bytes()
    if len(content) != int(member["bytes"]) or _sha(content) != str(member["sha256"]):
        raise ValueError("Schaff volume 5 source member drifted")
    lines = content.splitlines(keepends=True)
    if len(lines) != int(member["lines"]) or b"".join(lines) != content or any(b"\r" in line for line in lines):
        raise ValueError("Schaff volume 5 physical-line accounting drifted")
    return content, lines, member


def _source_structure(content: bytes) -> dict[str, object]:
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False))
    if root.tag != "ThML":
        raise ValueError("Schaff volume 5 root drifted")
    head, body = root.find("ThML.head"), root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("Schaff volume 5 head/body envelope drifted")
    top = list(body.findall("div1"))
    if [item.get("id") for item in top] != ["i", "ii", "iii"]:
        raise ValueError("Schaff volume 5 body carrier order drifted")
    content_carrier, index_carrier = top[1], top[2]
    content_div2 = list(content_carrier.findall("div2"))
    return {
        "root": root.tag,
        "head": head.tag,
        "body": body.tag,
        "body_top_level": [{"id": item.get("id"), "type": item.get("type"), "source_line": int(item.sourceline or 0), "elements": sum(1 for _ in item.iter())} for item in top],
        "content_div2": len(content_div2),
        "content_sections": sum(1 for item in content_div2 if item.get("type") == "Section"),
        "content_chapters": sum(1 for item in content_div2 if item.get("type") == "Chapter"),
        "content_div3": sum(1 for _ in content_carrier.iter("div3")),
        "index_div2": sum(1 for _ in index_carrier.iter("div2")),
        "tag_counts": dict(sorted(Counter(element.tag for element in root.iter()).items())),
    }


def _line_kind(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "blank"
    if stripped.startswith("<?xml"):
        return "xml-declaration"
    if stripped.startswith("<!DOCTYPE") or stripped.startswith('"-//CCEL/') or stripped.startswith('"http://www.ccel.org/'):
        return "doctype"
    if "<!--" in stripped or stripped.startswith("-->"):
        return "comment"
    if _STRUCTURAL_START_RE.match(stripped):
        return "structural-start"
    if _STRUCTURAL_END_RE.match(stripped):
        return "structural-end"
    if re.match(r"^<(?:div1|div2|div3)\b", stripped, re.IGNORECASE):
        return "division-start"
    if re.match(r"^</(?:div1|div2|div3)>", stripped, re.IGNORECASE):
        return "division-end"
    if re.match(r"^<DC(?:\.|\s|>)", stripped) or re.match(r"^</?generalInfo\b", stripped):
        return "metadata"
    if re.search(r"<(?:p|note|scripRef|a|li|ul|index|verse|l|unclear|br)\b", stripped, re.IGNORECASE):
        return "textual-carrier"
    return "xml-content"


def _records(content: bytes, lines: list[bytes]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    for number, raw in enumerate(lines, 1):
        line = raw[:-1] if raw.endswith(b"\n") else raw
        text = line.decode("utf-8", errors="strict")
        line_id = f"schaff-history-vol-5-line-{number:05d}"
        records.append({"id": line_id, "line": number, "byte_start": offset, "byte_end": offset + len(raw), "record_sha256": _sha(raw), "text_sha256": _sha(line), "line_ending": "LF" if raw.endswith(b"\n") else "EOF", "kind": _line_kind(text), "disposition": "represented", "target": f"#{line_id}", "text": text})
        offset += len(raw)
    if offset != len(content):
        raise ValueError("Schaff volume 5 source byte accounting does not close")
    return records


def _tei(profile: Mapping[str, object], structure: Mapping[str, object], records: list[dict[str, object]]) -> bytes:
    root = etree.Element(_q("TEI"), nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", "schaff-history-vol-5-candidate")
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
    bibl = _node(_node(file_desc, "sourceDesc"), "bibl")
    _node(bibl, "title", text=str(profile["title"]))
    _node(bibl, "author", text=str(profile["creator"]))
    _node(bibl, "note", {"type": "contributor-statement"}, str(profile["contributor_statement"]))
    _node(bibl, "idno", {"type": "URI"}, str(profile["source_url"]))
    _node(bibl, "idno", {"type": "SHA-256"}, str(profile["source_sha256"]))
    _node(bibl, "extent", text=f"{profile['source_bytes']} bytes; {profile['physical_lines']} UTF-8 LF physical lines; final line has no line ending")
    project_desc = _node(_node(header, "encodingDesc"), "projectDesc")
    _node(project_desc, "p", text="Every retained physical source line is represented exactly once, in source order, after removing only its LF transport framing.")
    _node(project_desc, "p", text="The candidate preserves the parsed ThML envelope as an independently counted source topology; it does not normalize, correct, or silently exclude source carriers.")
    _node(_node(header, "revisionDesc"), "change", {"status": "candidate"}, "Deterministic nonaccepted LIB-058 candidate generated from the pinned CCEL ThML witness.")
    transcription = _node(_node(_node(root, "text"), "body"), "div", {"xml:id": "schaff-history-vol-5-retained-lines", "type": "source-xml-transcription"})
    envelope = _node(transcription, "div", {"xml:id": "schaff-history-vol-5-envelope-summary", "type": "source-envelope"})
    _node(envelope, "head", text="Retained CCEL ThML envelope and source-native carrier census")
    _node(envelope, "p", text=f"Root {structure['root']}; head {structure['head']}; body {structure['body']}; body carriers {len(structure['body_top_level'])}; div1/div2/div3 {structure['tag_counts']['div1']}/{structure['tag_counts']['div2']}/{structure['tag_counts']['div3']}; content sections/chapters {structure['content_sections']}/{structure['content_chapters']}; index roots {structure['index_div2']}.")
    for record in records:
        kind = str(record["kind"])
        line_div = _node(transcription, "div", {"xml:id": str(record["id"]), "type": "source-line", "n": str(record["line"])})
        carrier = "head" if kind in {"structural-start", "division-start"} else "ab"
        _node(line_div, carrier, {"xml:id": str(record["id"]) + "-carrier", "n": str(record["line"]), "type": kind, "ana": f"#source-line #{kind}"}, str(record["text"]))
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    profile = _profile(source_manifest)
    content, lines, member = _source(source_manifest)
    structure = _source_structure(content)
    if structure != profile["source_structure"]:
        raise ValueError("Schaff volume 5 source topology does not match its pinned profile")
    records = _records(content, lines)
    crosswalk = [{key: value for key, value in record.items() if key != "text"} for record in records]
    accountability = {"contract": "ocd-lib058-source-accountability-v1", "work_id": "schaff-history-vol-5", "source_sha256": str(member["sha256"]), "source_bytes": len(content), "physical_lines": len(records), "represented_lines": len(records), "omitted_lines": 0, "duplicated_lines": 0, "member_census": [{"path": member["path"], "bytes": member["bytes"], "sha256": member["sha256"], "included": True, "reason": "The current LIB-058 manifest binds this sole exact retained CCEL ThML member."}], "excluded_members": [], "source_structure": structure, "crosswalk_sha256": _sha(_canonical(crosswalk)), "crosswalk": crosswalk}
    provenance = {"contract": "ocd-lib058-provenance-v1", "work_id": "schaff-history-vol-5", "title": profile["title"], "creator": profile["creator"], "contributor_statement": profile["contributor_statement"], "source_format": "CCEL ThML XML", "source_url": profile["source_url"], "source_sha256": profile["source_sha256"], "source_manifest_sha256": source_manifest.sha256, "candidate_status": "nonaccepted", "publication_authorized": False, "technical_validation_is_human_acceptance": False, "rights": {"retained_statement": "The retained ThML header has an empty DC.Rights element; source config records public-domain metadata, but rights clearance remains unresolved.", "worldwide": "unresolved", "publication": "not authorized"}}
    unresolved = [{"id": "schaff-history-vol-5-identity", "kind": "identity", "status": "human-review-required", "scope": "work, volume, and retained ThML envelope", "detail": "The exact retained member is bound technically; human identity and boundary acceptance remain open."}, {"id": "schaff-history-vol-5-edition", "kind": "edition-witness", "status": "human-review-required", "scope": "CCEL electronic witness and Charles Scribner's Sons source statement", "detail": "Observed source/header statements remain unaccepted edition evidence."}, {"id": "schaff-history-vol-5-readings", "kind": "substantive-reading-editorial", "status": "human-review-required", "scope": "all retained physical lines and ThML carrier classes", "detail": "No silent correction, modernization, entity expansion, or editorial acceptance was performed."}, {"id": "schaff-history-vol-5-rights", "kind": "rights", "status": "human-review-required", "scope": "CCEL header rights statement and publication", "detail": "Worldwide rights and publication authorization remain unresolved."}, {"id": "schaff-history-vol-5-acceptance", "kind": "acceptance-publication", "status": "human-review-required", "scope": "whole candidate", "detail": "Technical validation is not human acceptance, accepted IR, CVW review, or publication authorization."}]
    return {"content.tei.xml": _tei(profile, structure, records), "source-accountability.json": _canonical(accountability), "provenance.json": _canonical(provenance), "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved), "README.source.md": source_manifest.authority_path("source-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


def build_candidate(source_manifest: SourceManifest, destination: str | Path) -> CandidatePackage:
    return reconstruct(source_manifest, destination, _convert)
