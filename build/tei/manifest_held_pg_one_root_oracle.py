"""Independent retained-source oracle for direct one-root held PG candidates."""

from __future__ import annotations

from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import sys
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
ORACLE_ID = "ocd-manifest-held-pg-direct-one-root-independent-oracle"
ORACLE_VERSION = "1"
_MAPPING = "One direct TEI root represents the source title boundary. Included HTML direct-child ranges are mapped once in order with nested text, tails, headings, lists, tables, inline roles, source IDs, local links, and retained image targets. Every excluded source range, opening text segment, archive member, and sibling-work disposition remains explicit in source accounting."


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class _IndependentHTMLInventory(HTMLParser):
    """Cross-check source text and literal tag inventory without lxml recovery."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.parts: list[str] = []
        self.tags: Counter[str] = Counter()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.in_body = True
        if self.in_body:
            self.tags[tag] += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.in_body:
            self.tags[tag] += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "body":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        if self.in_body:
            self.parts.append(data)


def _closure(root: Path) -> str:
    paths = (
        "build/tei/manifest_held_pg_one_root_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    )
    return _sha(_canonical([{"path": name, "sha256": _sha((root / name).read_bytes())} for name in paths]))


def _source(manifest: SourceManifest, profile: dict[str, object], base: dict[str, object]) -> tuple[etree._Element, list[dict[str, object]], str]:
    archive_path = manifest.authority_path("retained-archive")
    archive_bytes = archive_path.read_bytes()
    receipt = json.loads(manifest.authority_path("acquisition-receipt").read_text(encoding="utf-8"))
    if _sha(archive_bytes) != base["archive_sha256"] or receipt["package"]["sha256"] != base["archive_sha256"]:
        raise ValueError("retained archive/receipt identity failure")
    with ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("retained archive CRC failure")
        members = [
            {"path": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}", "sha256": _sha(archive.read(item))}
            for item in archive.infolist() if not item.is_dir()
        ]
        if members != base["archive_members"]:
            raise ValueError("source archive member inventory mismatch")
        raw = archive.read(str(base["html_member"]))
    if _sha(raw) != base["html_sha256"] or receipt["html"]["sha256"] != base["html_sha256"]:
        raise ValueError("HTML member/receipt identity failure")
    if raw != manifest.authority_path("extracted-html").read_bytes():
        raise ValueError("retained extracted HTML differs from archive member")
    text = raw.decode("utf-8", errors="strict")
    independent = _IndependentHTMLInventory()
    independent.feed(text)
    root = html.fromstring(text)
    body = root.find(".//body")
    if body is None or len(body) != base["body_direct_children"]:
        raise ValueError("source body boundary/count differs")
    body_text = "".join(body.itertext())
    if "".join(independent.parts) != body_text or _sha(body_text.encode("utf-8")) != base["body_text_sha256"]:
        raise ValueError("independent HTML text reader disagrees with source body/profile")
    if dict(independent.tags) != base["source_tag_counts"]:
        raise ValueError("independent HTML literal-tag inventory disagrees with source profile")
    return body, members, body_text


def _tag_name(node: etree._Element) -> str:
    return etree.QName(node).localname


def _compare_sequence(sources: list[etree._Element], targets: list[etree._Element], paths: list[str], *, strict: bool) -> int:
    position = 0
    for source, path in zip(sources, paths, strict=True):
        tag = source.tag.lower() if isinstance(source.tag, str) else ""
        if tag in {"tbody", "thead", "tfoot", "colgroup", "col"}:
            if position >= len(targets):
                raise ValueError(f"source table wrapper omitted at {path}")
            opening = targets[position]
            if (_tag_name(opening) != "milestone" or opening.get("unit") != f"source-{tag}-start"
                    or opening.get("n") != path or opening.get(XML_ID) != (source.get("id") or f"source-node-{path}")
                    or opening.tail != source.text):
                raise ValueError(f"source table wrapper start mutation at {path}")
            position += 1
            children = list(source)
            position += _compare_sequence(children, targets[position:], [f"{path}.{index}" for index in range(1, len(children) + 1)], strict=False)
            if position >= len(targets):
                raise ValueError(f"source table wrapper end omitted at {path}")
            closing = targets[position]
            if (_tag_name(closing) != "milestone" or closing.get("unit") != f"source-{tag}-end"
                    or closing.get("n") != f"{path}.end" or closing.tail != source.tail):
                raise ValueError(f"source table wrapper end mutation at {path}")
            position += 1
        else:
            if position >= len(targets):
                raise ValueError(f"source carrier omitted at {path}")
            _compare_node(source, targets[position], path, top=False)
            position += 1
    if strict and position != len(targets):
        raise ValueError("source child count/invention mutation")
    return position


def _compare_node(source: etree._Element, target: etree._Element, path: str, *, top: bool) -> None:
    if target.get("n") != path or target.tail != source.tail:
        raise ValueError(f"source carrier order/tail mutation at {path}")
    if not isinstance(source.tag, str):
        if (_tag_name(target) != "milestone" or target.get("unit") != "source-comment"
                or target.get("rend") != "comment-sha256:" + _sha((source.text or "").encode("utf-8"))):
            raise ValueError(f"source comment mutation at {path}")
        return
    if target.text != source.text:
        raise ValueError(f"source carrier text mutation at {path}")
    tag = source.tag.lower()
    expected = (
        "table" if tag == "table" else "row" if tag == "tr" else
        "cell" if tag in {"td", "th"} else "ab" if top else
        "ref" if tag == "a" else "graphic" if tag == "img" else "lb" if tag == "br" else
        "milestone" if tag == "hr" else "hi" if tag in {"i", "em", "strong", "b", "small", "sup", "sub"} else
        "title" if tag == "cite" else "add" if tag == "ins" else "seg"
    )
    if _tag_name(target) != expected:
        raise ValueError(f"source carrier role mutation at {path}: {tag}")
    if expected in {"ab", "seg"} and target.get("type") != f"source-{tag}":
        raise ValueError(f"source structural role mutation at {path}: {tag}")
    if tag == "th" and target.get("role") != "label":
        raise ValueError(f"source table heading role mutation at {path}")
    if tag in {"td", "th"} and target.get("cols") != source.get("colspan"):
        raise ValueError(f"source table span mutation at {path}")
    if target.get(XML_ID) != (source.get("id") or f"source-node-{path}"):
        raise ValueError(f"source ID mutation at {path}")
    if target.get(XML_LANG) != source.get("lang"):
        raise ValueError(f"source language mutation at {path}")
    if tag == "a" and target.get("target") != source.get("href"):
        raise ValueError(f"source link target mutation at {path}")
    if tag == "img" and target.get("url") != source.get("src"):
        raise ValueError(f"source image target mutation at {path}")
    render = target.get("rend") or ""
    for key, prefix in (("class", "source-class:"), ("style", "source-style:"), ("alt", "source-alt:")):
        value = source.get(key)
        if value and prefix + value not in render:
            raise ValueError(f"source {key} mutation at {path}")
    _compare_sequence(list(source), list(target), [f"{path}.{index}" for index in range(1, len(source) + 1)], strict=True)


def _unit_text(body: etree._Element, unit: dict[str, object]) -> str:
    return "".join(
        "".join(body[index].itertext()) + (body[index].tail or "")
        for index in range(int(unit["start"]), int(unit["end"]) + 1)
    )


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    root = source_manifest.repository_root
    profile_bytes = source_manifest.authority_path("profile").read_bytes()
    profile = json.loads(profile_bytes)
    base_bytes = source_manifest.authority_path("base-profile").read_bytes()
    base = json.loads(base_bytes)
    if _sha(base_bytes) != profile["base_profile_sha256"]:
        raise ValueError("PG base feature profile identity differs")
    body, members, body_text = _source(source_manifest, profile, base)
    units = base["units"]
    if not units or units[0]["start"] != 0 or units[-1]["end"] != len(body) - 1 or any(a["end"] + 1 != b["start"] for a, b in zip(units, units[1:])):
        raise ValueError("source unit ranges do not partition the complete body")
    selected = profile["selected_unit_ids"]
    unit_by_id = {str(unit["id"]): unit for unit in units}
    if not selected or len(selected) != len(set(selected)) or any(unit_id not in unit_by_id for unit_id in selected):
        raise ValueError("candidate selected-unit boundary is not source-profile grounded")
    selected_units = [unit_by_id[unit_id] for unit_id in selected]
    mode = profile["selection_mode"]
    if mode == "complete-volume":
        if selected != [unit["id"] for unit in units] or profile["title"] != base["volume_title"]:
            raise ValueError("complete-volume boundary/title does not match source profile")
    elif mode == "single-titled-work":
        if len(selected_units) != 1 or selected_units[0]["kind"] != "work" or profile["title"] != selected_units[0]["title"]:
            raise ValueError("single titled-work boundary/title does not match source profile")
    else:
        raise ValueError("unknown direct-TEI selection mode")

    xml = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    schema = compiled_schema()
    if not schema.validate(tree):
        raise ValueError("candidate is not valid TEI P5: " + str(schema.error_log[:1]))
    if _tag_name(tree) != "TEI" or tree.get(XML_ID) != profile["root_xml_id"]:
        raise ValueError("candidate must be exactly one direct TEI root for the selected source title")
    title = tree.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
    if title is None or title.text != profile["title"]:
        raise ValueError("candidate TEI title does not match the source-attested work boundary")
    body_target = tree.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if body_target is None:
        raise ValueError("candidate TEI body is missing")
    if mode == "complete-volume" and body_target.text != body.text:
        raise ValueError("complete volume source opening text changed")
    if mode == "single-titled-work" and body_target.text is not None:
        raise ValueError("shared opening source text was duplicated into a single work")
    divisions = list(body_target)
    if len(divisions) != len(selected_units):
        raise ValueError("candidate source-unit/work boundary count differs")
    included_text: list[str] = []
    for division, unit in zip(divisions, selected_units, strict=True):
        expected_type = "source-unit" if mode == "complete-volume" else "work"
        if (_tag_name(division) != "div" or division.get("type") != expected_type
                or division.get("n") != unit["id"] or division.get(XML_ID) != unit["id"]
                or division.text is not None or division.tail is not None):
            raise ValueError("candidate direct-TEI division identity/order differs from source boundary")
        expected_count = int(unit["end"]) - int(unit["start"]) + 1
        if len(division) != expected_count:
            raise ValueError(f"source unit carrier count differs for {unit['id']}")
        for index, target in zip(range(int(unit["start"]), int(unit["end"]) + 1), division, strict=True):
            _compare_node(body[index], target, str(index + 1), top=True)
        unit_text = _unit_text(body, unit)
        if "".join(division.itertext()) != unit_text:
            raise ValueError(f"source work text differs for {unit['id']}")
        included_text.append(unit_text)
    expected_text = body_text if mode == "complete-volume" else _unit_text(body, selected_units[0])
    if "".join(body_target.itertext()) != expected_text:
        raise ValueError("source body text omissions, duplication, or invention")

    ids = [element.get(XML_ID) for element in tree.iter() if element.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate contains duplicate XML IDs")
    source_ids = {element.get("id") for element in body.iter() if element.get("id")}
    for reference in tree.iter(f"{{{TEI}}}ref"):
        target = reference.get("target")
        if target and target.startswith("#") and (target[1:] not in ids or target[1:] not in source_ids):
            raise ValueError("candidate local link closure/identity failure")
    member_paths = {item["path"] for item in members}
    for graphic in tree.iter(f"{{{TEI}}}graphic"):
        if graphic.get("url") not in member_paths:
            raise ValueError("candidate image target absent from retained archive")

    disposition = profile["unit_dispositions"]
    expected_units = []
    for unit in units:
        item = disposition[str(unit["id"])]
        expected_units.append({
            "id": unit["id"], "title": unit["title"], "kind": unit["kind"],
            "start": unit["start"], "end": unit["end"],
            "disposition": item["disposition"],
            "assigned_candidate_source_id": item.get("assigned_candidate_source_id"),
            "source_direct_child_count": int(unit["end"]) - int(unit["start"]) + 1,
            "source_text_sha256": _sha(_unit_text(body, unit).encode("utf-8")),
        })
    expected_account = {
        "contract": "ocd-manifest-held-pg-one-root-source-accounting-v1",
        "source_id": source_manifest.record["source_id"],
        "scope_id": profile["scope_id"],
        "selection_mode": profile["selection_mode"], "title": profile["title"],
        "root_xml_id": profile["root_xml_id"],
        "archive_sha256": base["archive_sha256"], "html_sha256": base["html_sha256"],
        "archive_members": members,
        "source_body_direct_children": len(body),
        "source_body_text_sha256": _sha(body_text.encode("utf-8")),
        "source_body_opening_text_sha256": _sha((body.text or "").encode("utf-8")),
        "units": expected_units,
        "selected_unit_ids": selected,
        "represented_body_text_sha256": _sha("".join(body_target.itertext()).encode("utf-8")),
        "tei_sha256": _sha(xml),
        "mapping": _MAPPING,
    }
    if json.loads(candidate.member_bytes("source-accountability.json")) != expected_account:
        raise ValueError("complete source accounting or work-boundary disposition differs")
    policy_bytes = source_manifest.authority_path("policy").read_bytes()
    policy = json.loads(policy_bytes)
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("readme").read_bytes():
        raise ValueError("candidate source attribution/scope notice differs")
    if json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]:
        raise ValueError("candidate provenance or nonaccepted status differs")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(item) for item in policy["unresolved"]):
        raise ValueError("candidate unresolved status differs")

    closure = _closure(root)
    if closure != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=_sha(manifest_archive := source_manifest.authority_path("retained-archive").read_bytes()),
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
