"""Unapplied Nave topical profile: direct native projection and independent check.

Public rows are readable topical projections, not XML serializations. The master
and complete private inventory preserve exact native hierarchy and whitespace.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import jsonschema
from lxml import etree
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/v2/categories/topical-indexes.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
NS = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
IDENTITY = {"work_id": "naves-topical-bible", "textual_form_id": "naves-topical-bible-retained-electronic", "edition_id": "naves-topical-bible-retained-electronic-witness"}
TITLE = "Nave SWORD module v3 retained electronic witness"
PROFILE = "ocd-topical-indexes-nave-native-v1"
SOURCE_SHA = "0b83eb74adf00b56987e49e7f00731bc8b4be5e7daa3828d62ec6a3943884f17"
SOURCE_SET = "8c5cf1cc42248214ba0d9e0fda51c99925b9a06760a71dd2a33a5750e09afc6d"
CONF_SHA = "0a52fe9e016a8900434118be0cb021deed1dfb02b7d2b829bb0e094ff92049e9"
HEADER_CHILDREN = {"teiHeader": ["fileDesc", "encodingDesc", "revisionDesc"], "fileDesc": ["titleStmt", "publicationStmt", "sourceDesc"], "titleStmt": ["title"], "publicationStmt": ["publisher", "availability"], "availability": ["p"], "sourceDesc": ["bibl"], "encodingDesc": ["p"], "revisionDesc": ["change"], "bibl": ["ptr"] + ["idno"] * 12 + ["note"] * 9, "title": [], "publisher": [], "p": [], "change": [], "ptr": [], "idno": [], "note": []}
HEADER_ATTRS = {"availability": {"status"}, "bibl": {"type"}, "ptr": {"target"}, "idno": {"type"}, "note": {"type"}, "change": {"when", XML + "id"}}
NOTES = ["source-scope", "source-location", "native-text-scope", "source-credit", "literal-module-description", "literal-module-about", "source-metadata-qualification", "source-format-control", "historical-header-context"]
COUNTS = {"entryFree": 5322, "form": 5322, "orth": 5322, "def": 5322, "lb": 17018, "list": 2346, "item": 12361, "ref": 82303}


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _validator():
    schema = json.loads(SCHEMA.read_bytes()); common = json.loads(COMMON.read_bytes())
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _context(identity, language, edition_title):
    if identity != IDENTITY or language != "en" or edition_title != TITLE:
        raise PipelineError("unsupported-visible: Nave exact native identity/context")


def _raw(path):
    raw = Path(path).read_bytes()
    if any(token in raw.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")) or re.search(br"<\?(?!xml(?:\s|\?>))", raw, re.I):
        raise PipelineError("unsupported-visible: Nave declarations/comments/instructions")
    return raw


def _header_et(header, revision):
    for node in header.iter():
        tag = node.tag.removeprefix(NS)
        if not node.tag.startswith(NS) or tag not in HEADER_CHILDREN or [c.tag for c in node] != [NS + t for t in HEADER_CHILDREN[tag]] or set(node.attrib) != HEADER_ATTRS.get(tag, set()):
            raise PipelineError("unsupported-visible: Nave header shape/attributes")
        if tag not in ("title", "publisher", "p", "change", "idno", "note") and ((node.text or "").strip() or any((c.tail or "").strip() for c in node)):
            raise PipelineError("unsupported-visible: Nave header loose text")
    if header.find("./" + NS + "fileDesc/" + NS + "titleStmt/" + NS + "title").text != "Nave's Topical Bible":
        raise PipelineError("unsupported-visible: Nave title")
    availability = header.find("./" + NS + "fileDesc/" + NS + "publicationStmt/" + NS + "availability")
    if availability.get("status") != "restricted" or "unresolved" not in "".join(availability.itertext()):
        raise PipelineError("unsupported-visible: Nave rights qualification")
    change = header.find("./" + NS + "revisionDesc/" + NS + "change")
    if change.get(XML + "id") != revision or not change.get("when") or not change.text:
        raise PipelineError("unsupported-visible: Nave revision binding")
    bibl = header.find("./" + NS + "fileDesc/" + NS + "sourceDesc/" + NS + "bibl")
    expected = dict(IDENTITY, acquisition_id="naves-topical-bible-retained-source-set", representation_revision=revision, source_sha256=SOURCE_SHA, retained_sha256=SOURCE_SHA, transformation_source_set_sha256=SOURCE_SET, module_config_sha256=CONF_SHA, source_bytes="2744", source_kind="retained-member-set", sha256=SOURCE_SHA)
    ids = bibl.findall(NS + "idno")
    if bibl.get("type") != "ocd-acceptance-binding" or bibl[0].attrib != {"target": "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/Nave.zip"} or {n.get("type"): n.text for n in ids} != expected or len({n.get("type") for n in ids}) != len(ids) or [n.get("type") for n in bibl.findall(NS + "note")] != NOTES:
        raise PipelineError("unsupported-visible: Nave bound source/header identity")


def _inventory_et(root):
    nodes, excluded = [], []
    header_nodes = set(root[0].iter())
    for ordinal, node in enumerate(root.iter(), 1):
        disposition = "header-context" if node in header_nodes else "projected-or-structural"
        nodes.append({"ordinal": ordinal, "tag": node.tag.removeprefix(NS), "attributes": dict(node.attrib), "text_sha256": _hash((node.text or "").encode()), "tail_sha256": _hash((node.tail or "").encode()), "disposition": disposition})
        if disposition == "header-context": excluded.append({"ordinal": ordinal, "reason": disposition})
    return nodes, excluded


def _render_et(node, depth=0):
    tag = node.tag.removeprefix(NS)
    if tag not in ("def", "lb", "ref", "list", "item") or (tag != "ref" and node.attrib):
        raise PipelineError("unsupported-visible: Nave definition element/attribute")
    if tag == "ref":
        if set(node.attrib) not in ({"target"}, {"type", "target"}) or ("type" in node.attrib and node.get("type") != "osisRef") or not node.get("target") or len(node) or not node.text:
            raise PipelineError("unsupported-visible: Nave literal reference")
    if tag == "lb" and (len(node) or node.text): raise PipelineError("unsupported-visible: Nave line-break content")
    if tag == "list" and ((node.text or "").strip() or any(c.tag != NS + "item" for c in node) or not len(node)):
        raise PipelineError("unsupported-visible: Nave list boundary")
    allowed = {"def": {"lb", "ref", "list"}, "item": {"lb", "ref", "list"}, "list": {"item"}, "ref": set(), "lb": set()}[tag]
    if any(c.tag not in {NS + t for t in allowed} for c in node): raise PipelineError("unsupported-visible: Nave mixed child")
    if tag == "lb": return "\n" + "  " * depth
    result = ("\n" + "  " * depth if tag == "item" else "") + (node.text or "")
    for child in node:
        result += _render_et(child, depth + 1 if tag == "list" else depth) + (child.tail or "")
    return result


def project_nave_native(path, *, identity, language, representation_revision, edition_title):
    _context(identity, language, edition_title)
    raw = _raw(path); root = ET.fromstring(raw)
    if root.tag != NS + "TEI" or root.attrib != {XML + "id": "naves-topical-bible-candidate"} or [c.tag for c in root] != [NS + "teiHeader", NS + "text"]:
        raise PipelineError("unsupported-visible: Nave document envelope")
    _header_et(root[0], representation_revision)
    text = root[1]
    if text.attrib or text.text or text.tail or [c.tag for c in text] != [NS + "body"] or text[0].attrib or text[0].text or text[0].tail or len(text[0]) != 5322:
        raise PipelineError("unsupported-visible: Nave complete text/body")
    rows, anchors = [], []; validator = _validator(); counts = Counter(); ref_counts = Counter()
    for sequence, entry in enumerate(text[0], 1):
        entry_id = f"naves-topical-bible-entry-{sequence:05d}"
        if entry.tag != NS + "entryFree" or set(entry.attrib) != {XML + "id", "n"} or entry.get(XML + "id") != entry_id or not entry.get("n") or (entry.text or "").strip() or entry.tail or [c.tag for c in entry] != [NS + "form", NS + "def"]:
            raise PipelineError("unsupported-visible: Nave ordered native entry")
        form, definition = entry
        if form.attrib != {"type": "dictionary-key"} or form.text or form.tail or len(form) != 1 or form[0].tag != NS + "orth" or form[0].attrib or len(form[0]) or not form[0].text or form[0].tail or (definition.tail or "").strip():
            raise PipelineError("unsupported-visible: Nave literal dictionary key")
        visible = (entry.text or "") + _render_et(definition) + (definition.tail or "")
        if not visible.strip(): raise PipelineError("unsupported-visible: Nave empty definition")
        references = []
        for ref in definition.iter(NS + "ref"):
            kind = "scripture" if ref.get("type") == "osisRef" else "topic"
            ref_counts[kind] += 1
            references.append({"kind": kind, "label": ref.text, "target": ref.get("target")})
        for node in entry.iter(): counts[node.tag.removeprefix(NS)] += 1
        row = dict(identity, record_id=identity["edition_id"] + ":topic:" + _hash(entry_id.encode())[:20], sequence=sequence, category="topical_indexes", language=language, representation_revision=representation_revision, provenance={"edition_title": edition_title}, topic=form[0].text, locator={"kind": "topic", "heading": form[0].text}, items=[{"text": visible, "references": references}], text=visible)
        errors = list(validator.iter_errors(row))
        if errors: raise PipelineError("invalid Nave topical row: " + errors[0].message)
        rows.append(row); anchors.append({"unit_id": entry_id, "record_id": row["record_id"], "text_sha256": _hash(visible.encode())})
    if dict(counts) != COUNTS or ref_counts != {"scripture": 77935, "topic": 4368}: raise PipelineError("unsupported-visible: Nave complete native census")
    inventory, exclusions = _inventory_et(root)
    receipt = {"scope": "tei-document; caller-supplied context", "mapping_version": PROFILE, "master_sha256": _hash(raw), "schema_sha256": _hash(SCHEMA.read_bytes()), "common_schema_sha256": _hash(COMMON.read_bytes()), "output_sha256": _hash(_canonical(rows)), "row_count": len(rows), "anchors": anchors, "inventory": inventory, "warnings": [{"reason": "Source OSIS/topic targets and labels remain literal, without normalization or independent validation. Public readable text inserts line-break and depth-indented list-item boundaries; exact XML hierarchy/text/tails remain master/private evidence."}], "exclusions": exclusions, "unsupported": [], "independent_check": {"status": "pending"}}
    return {"rows": rows, "receipt": receipt}


def verify_nave_native(path, rows, receipt, *, identity, language, representation_revision, edition_title):
    """Independent lxml source traversal; producer and renderer are not invoked."""
    try:
        if identity != IDENTITY or language != "en" or edition_title != TITLE: raise ValueError("unsupported-visible: Nave checker identity/context")
        raw = Path(path).read_bytes(); root = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)); ns = {"t": NS[1:-1]}
        if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"): raise ValueError("unsupported-visible: Nave checker declarations")
        if root.tag != NS + "TEI" or dict(root.attrib) != {XML + "id": "naves-topical-bible-candidate"} or [c.tag for c in root] != [NS + "teiHeader", NS + "text"]: raise ValueError("unsupported-visible: Nave checker envelope")
        header = root[0]
        for node in header.iter():
            name = etree.QName(node).localname
            if etree.QName(node).namespace != ns["t"] or name not in HEADER_CHILDREN or [c.tag for c in node] != [NS + v for v in HEADER_CHILDREN[name]] or set(node.attrib) != HEADER_ATTRS.get(name, set()): raise ValueError("unsupported-visible: Nave checker header grammar")
            if name not in ("title", "publisher", "p", "change", "idno", "note") and any(str(s).strip() for s in node.xpath("text()")): raise ValueError("unsupported-visible: Nave checker loose header text")
        if header.xpath("string(t:fileDesc/t:titleStmt/t:title)", namespaces=ns) != "Nave's Topical Bible": raise ValueError("unsupported-visible: Nave checker title")
        changes = header.xpath("t:revisionDesc/t:change", namespaces=ns)
        if changes[0].get(XML + "id") != representation_revision or not changes[0].get("when") or not changes[0].text: raise ValueError("unsupported-visible: Nave checker revision binding")
        availability = header.xpath("t:fileDesc/t:publicationStmt/t:availability", namespaces=ns)[0]
        bibl = header.xpath("t:fileDesc/t:sourceDesc/t:bibl", namespaces=ns)[0]
        expected_ids = {**IDENTITY, "acquisition_id": "naves-topical-bible-retained-source-set", "representation_revision": representation_revision, "source_sha256": SOURCE_SHA, "retained_sha256": SOURCE_SHA, "transformation_source_set_sha256": SOURCE_SET, "module_config_sha256": CONF_SHA, "source_bytes": "2744", "source_kind": "retained-member-set", "sha256": SOURCE_SHA}
        ids = bibl.xpath("t:idno", namespaces=ns)
        if availability.get("status") != "restricted" or "unresolved" not in availability.xpath("string(.)") or bibl.get("type") != "ocd-acceptance-binding" or dict(bibl[0].attrib) != {"target": "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/Nave.zip"} or len({n.get("type") for n in ids}) != len(ids) or {n.get("type"): n.text for n in ids} != expected_ids or [n.get("type") for n in bibl.xpath("t:note", namespaces=ns)] != NOTES: raise ValueError("unsupported-visible: Nave checker source/header binding")
        text = root[1]
        if text.attrib or text.text or text.tail or [c.tag for c in text] != [NS + "body"] or text[0].attrib or text[0].text or text[0].tail or len(text[0]) != 5322: raise ValueError("unsupported-visible: Nave checker complete body")
        nodes = list(root.iter()); header_nodes = set(header.iter()); inventory = []; exclusions = []; all_ids = []
        for ordinal, node in enumerate(nodes, 1):
            q = etree.QName(node)
            if q.namespace != ns["t"]: raise ValueError("unsupported-visible: Nave checker namespace")
            if node.get(XML + "id"): all_ids.append(node.get(XML + "id"))
            disposition = "header-context" if node in header_nodes else "projected-or-structural"
            inventory.append({"ordinal": ordinal, "tag": q.localname, "attributes": dict(node.attrib), "text_sha256": _hash((node.text or "").encode()), "tail_sha256": _hash((node.tail or "").encode()), "disposition": disposition})
            if disposition == "header-context": exclusions.append({"ordinal": ordinal, "reason": disposition})
        if len(all_ids) != len(set(all_ids)): raise ValueError("unsupported-visible: Nave duplicate IDs")
        counts = Counter(); ref_counts = Counter(); expected_rows = []; anchors = []
        for sequence, entry in enumerate(text[0], 1):
            key_id = "naves-topical-bible-entry-" + str(sequence).zfill(5)
            if entry.tag != NS + "entryFree" or set(entry.attrib) != {XML + "id", "n"} or entry.get(XML + "id") != key_id or not entry.get("n") or (entry.text or "").strip() or entry.tail or [n.tag for n in entry] != [NS + "form", NS + "def"]: raise ValueError("unsupported-visible: Nave checker entry/order")
            form, definition = entry
            if dict(form.attrib) != {"type": "dictionary-key"} or form.text or form.tail or len(form) != 1 or form[0].tag != NS + "orth" or form[0].attrib or len(form[0]) or not form[0].text or form[0].tail or (definition.tail or "").strip(): raise ValueError("unsupported-visible: Nave checker key")
            chunks = []
            def observe(node, depth):
                name = etree.QName(node).localname
                rules = {"def": {"lb", "ref", "list"}, "item": {"lb", "ref", "list"}, "list": {"item"}, "ref": set(), "lb": set()}
                if etree.QName(node).namespace != ns["t"] or name not in rules or any(c.tag not in {NS + x for x in rules[name]} for c in node): raise ValueError("unsupported-visible: Nave checker mixed structure")
                if name == "ref":
                    if set(node.attrib) not in ({"target"}, {"type", "target"}) or (node.get("type") is not None and node.get("type") != "osisRef") or not node.get("target") or len(node) or not node.text: raise ValueError("unsupported-visible: Nave checker reference")
                elif node.attrib: raise ValueError("unsupported-visible: Nave checker mixed attribute")
                if name == "lb":
                    if len(node) or node.text: raise ValueError("unsupported-visible: Nave checker line break")
                    chunks.append("\n" + "  " * depth); return
                if name == "list" and ((node.text or "").strip() or not len(node)): raise ValueError("unsupported-visible: Nave checker list")
                if name == "item": chunks.append("\n" + "  " * depth)
                if node.text: chunks.append(node.text)
                for child in node:
                    observe(child, depth + (1 if name == "list" else 0))
                    if child.tail: chunks.append(child.tail)
            observe(definition, 0); visible = (entry.text or "") + "".join(chunks) + (definition.tail or "")
            if not visible.strip(): raise ValueError("unsupported-visible: Nave checker empty text")
            references = []
            for ref in definition.xpath(".//t:ref", namespaces=ns):
                kind = "scripture" if ref.get("type") == "osisRef" else "topic"; ref_counts[kind] += 1
                references.append({"kind": kind, "label": ref.text, "target": ref.get("target")})
            counts.update(etree.QName(n).localname for n in entry.iter())
            row = {**identity, "record_id": identity["edition_id"] + ":topic:" + _hash(key_id.encode())[:20], "sequence": sequence, "category": "topical_indexes", "language": language, "representation_revision": representation_revision, "provenance": {"edition_title": edition_title}, "topic": form[0].text, "locator": {"kind": "topic", "heading": form[0].text}, "items": [{"text": visible, "references": references}], "text": visible}
            expected_rows.append(row); anchors.append({"unit_id": key_id, "record_id": row["record_id"], "text_sha256": _hash(visible.encode())})
        if dict(counts) != COUNTS or ref_counts != {"scripture": 77935, "topic": 4368}: raise ValueError("unsupported-visible: Nave checker complete census")
        expected_receipt = {"scope": "tei-document; caller-supplied context", "mapping_version": PROFILE, "master_sha256": _hash(raw), "schema_sha256": _hash(SCHEMA.read_bytes()), "common_schema_sha256": _hash(COMMON.read_bytes()), "output_sha256": _hash(_canonical(expected_rows)), "row_count": len(expected_rows), "anchors": anchors, "inventory": inventory, "warnings": [{"reason": "Source OSIS/topic targets and labels remain literal, without normalization or independent validation. Public readable text inserts line-break and depth-indented list-item boundaries; exact XML hierarchy/text/tails remain master/private evidence."}], "exclusions": exclusions, "unsupported": [], "independent_check": {"status": "pending"}}
        errors = []
        if rows != expected_rows: errors.append("Nave rows differ from independent native traversal")
        if receipt != expected_receipt: errors.append("Nave saved receipt differs from independent complete inventory")
        validator = _validator()
        for row in rows: errors.extend("schema: " + e.message for e in validator.iter_errors(row))
        return errors
    except (OSError, ValueError, KeyError, TypeError, IndexError, etree.XMLSyntaxError) as exc:
        return [str(exc)]
