"""Source-local retained-CCEL ThML reconstruction for J. C. Ryle's Holiness."""

from __future__ import annotations

import base64
from collections import Counter
import html
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-ryle-holiness-retained-ccel-thml-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
SOURCE_AUTHORITY = "retained-ryle-holiness"
FORMAT_ONLY = frozenset({"style", "selector", "property", "colgroup", "col"})
LANG_MAP = {"EL": "grc", "HE": "he", "LA": "la", "FR": "fr", "DE": "de"}
SAFE_XML_ENTITIES = frozenset({"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"})


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _replace_entity(match: re.Match[str]) -> str:
    entity = match.group(0)
    if entity in SAFE_XML_ENTITIES:
        return entity
    unescaped = html.unescape(entity)
    if unescaped == entity:
        raise ValueError(f"unmapped named XML entity {entity!r}")
    return unescaped


def _prepared_source(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("retained Holiness source is not UTF-8") from exc
    text = re.sub(r"<!DOCTYPE\s[\s\S]*?>", "", text, flags=re.IGNORECASE)
    return re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text).encode("utf-8")


def _parse(content: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=True,
        remove_comments=False,
        remove_pis=False,
    )
    try:
        return etree.fromstring(_prepared_source(content), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Holiness ThML is not parseable") from exc


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _selector(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{_local(node)}[1]"
    peers = [
        child
        for child in parent
        if isinstance(child.tag, str) and child.tag == node.tag
    ]
    return f"{_selector(parent)}/{_local(node)}[{peers.index(node) + 1}]"


def _features(root: etree._Element) -> list[dict[str, object]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    features: list[dict[str, object]] = []
    for ordinal, element in enumerate(elements, 1):
        parent = element.getparent()
        siblings = (
            [
                child
                for child in parent
                if isinstance(child.tag, str)
            ]
            if parent is not None
            else [element]
        )
        features.append(
            {
                "feature_id": f"ryle-holiness-feature-{ordinal:05d}",
                "source_selector": _selector(element),
                "source_qname": str(element.tag),
                "source_attributes": [
                    {"qname": str(name), "value": value}
                    for name, value in element.attrib.items()
                ],
                "source_direct_text": element.text or "",
                "source_tail_text": element.tail or "",
                "source_parent_selector": _selector(parent) if parent is not None else None,
                "source_child_ordinal": siblings.index(element) + 1,
                "disposition": (
                    "formatting-only-excluded"
                    if _local(element) in FORMAT_ONLY
                    else "represented"
                ),
            }
        )
    return features


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    counts = dict(sorted(Counter(_local(node) for node in elements).items()))
    counts.setdefault("sup", 0)
    counts = dict(sorted(counts.items()))
    census = {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in elements),
        "tail_nodes": sum(node.tail is not None for node in elements),
        "characters": sum(
            len(node.text or "") + len(node.tail or "") for node in elements
        ),
    }
    return counts, census


def _lexical_events(root: etree._Element) -> dict[str, int]:
    tree = root.getroottree()
    doctype = 1 if tree.docinfo.doctype else 0
    return {
        "comments": len(tree.xpath("//comment()")),
        "processing_instructions": len(tree.xpath("//processing-instruction()")),
        "doctype_declarations": doctype,
    }


def _first_text(root: etree._Element, localname: str) -> str:
    for node in root.iter():
        if isinstance(node.tag, str) and _local(node) == localname:
            return "".join(node.itertext()).strip()
    return ""


def _tei(
    localname: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    nsmap = {None: TEI_NS} if localname == "TEI" else None
    node = etree.Element(f"{{{TEI_NS}}}{localname}", nsmap=nsmap)
    for name, value in (attrs or {}).items():
        if value is not None:
            node.set(name, value)
    if text is not None:
        node.text = text
    return node


def _append_text(target: etree._Element, text: str | None) -> None:
    if not text:
        return
    if len(target):
        last = target[-1]
        last.tail = (last.tail or "") + text
    else:
        target.text = (target.text or "") + text


def _bound_attrs(source: etree._Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    if source.get("id"):
        attrs[XML_ID] = str(source.get("id"))
    attrs["corresp"] = "urn:source-xpath:" + quote(_selector(source), safe="")
    if source.get("class"):
        attrs["rend"] = str(source.get("class"))
    elif source.get("style"):
        attrs["rend"] = str(source.get("style"))
    if source.get("lang"):
        code = str(source.get("lang"))
        attrs[XML_LANG] = LANG_MAP.get(code.upper(), code)
    return attrs


def _division_type(source: etree._Element) -> str:
    localname = _local(source)
    source_id = source.get("id") or ""
    title = (source.get("title") or "").casefold()
    if localname == "div1":
        return {"i": "titlePage", "ii": "front-matter", "iii": "work", "iv": "indexes"}.get(
            source_id, "section"
        )
    if localname == "div2":
        if source_id == "ii.ii" or title == "contents":
            return "contents"
        if source_id == "ii.iii" or title == "introduction":
            return "introduction"
        if source_id.startswith("iii."):
            return "chapter"
        if source_id.startswith("iv."):
            return "index"
        return "section"
    if (source.get("class") or "").casefold() == "index":
        return "index"
    if any(_local(child) == "verse" for child in source.iterdescendants()):
        return "poetry"
    return "source-div"


def _heading_is_post_content(source: etree._Element) -> bool:
    parent = source.getparent()
    if parent is None:
        return False
    for sibling in parent:
        if sibling is source:
            break
        if not isinstance(sibling.tag, str):
            continue
        sibling_name = _local(sibling)
        if sibling_name in FORMAT_ONLY or sibling_name in {"pb", "hr"}:
            continue
        if sibling_name in {"h1", "h2", "h3", "h4"}:
            continue
        return True
    return False


def _map_node(source: etree._Element) -> etree._Element:
    localname = _local(source)
    if localname in FORMAT_ONLY:
        raise ValueError(f"formatting-only source node reached mapping: {localname}")
    attrs = _bound_attrs(source)
    if localname in {"div", "div1", "div2"}:
        attrs["type"] = _division_type(source)
        if source.get("title"):
            attrs["n"] = str(source.get("title"))
        target = _tei(
            "ab"
            if localname == "div"
            and (source.get("class") or "").casefold() != "index"
            and any(_local(child) == "verse" for child in source.iterdescendants())
            else "div",
            attrs,
        )
    elif localname in {"h1", "h2", "h3", "h4"}:
        if _heading_is_post_content(source):
            attrs.setdefault("rend", "heading")
            target = _tei("p", attrs)
        else:
            target = _tei("head", attrs)
    elif localname == "p":
        target = _tei("p", attrs)
    elif localname == "i":
        attrs["rend"] = "italic"
        target = _tei("hi", attrs)
    elif localname == "br":
        target = _tei("lb", attrs)
    elif localname == "scripRef":
        attrs["type"] = "scripture"
        values = [
            item.removeprefix("Bible:")
            for item in (source.get("osisRef") or "").split()
            if item.strip()
        ]
        if values:
            attrs["cRef"] = " ".join(values)
        if source.get("passage"):
            attrs["n"] = str(source.get("passage"))
        target = _tei("ref", attrs)
    elif localname == "note":
        if source.get("place"):
            attrs["place"] = str(source.get("place"))
        if source.get("n"):
            attrs["n"] = str(source.get("n"))
        target = _tei("note", attrs)
    elif localname == "pb":
        if source.get("n"):
            attrs["n"] = str(source.get("n"))
        target = _tei("pb", attrs)
    elif localname == "span":
        if (source.get("class") or "").casefold() == "sc":
            attrs["rend"] = "smallcaps"
            target = _tei("hi", attrs)
        elif source.get("lang"):
            target = _tei("foreign", attrs)
        else:
            target = _tei("seg", attrs)
    elif localname == "sup":
        attrs["rend"] = "superscript"
        target = _tei("hi", attrs)
    elif localname == "a":
        if source.get("href"):
            attrs["target"] = str(source.get("href"))
        target = _tei("ref", attrs)
    elif localname == "table":
        target = _tei("table", attrs)
    elif localname == "tr":
        target = _tei("row", attrs)
    elif localname == "td":
        target = _tei("cell", attrs)
    elif localname == "th":
        attrs["role"] = "label"
        target = _tei("cell", attrs)
    elif localname == "verse":
        attrs["type"] = str(source.get("type") or "stanza")
        target = _tei("lg", attrs)
    elif localname == "l":
        target = _tei("l", attrs)
    elif localname == "hr":
        attrs["unit"] = "horizontal-rule"
        target = _tei("milestone", attrs)
    elif localname == "insertIndex":
        source_type = source.get("type") or "marker"
        attrs["type"] = f"insert-index-{source_type}"
        target = _tei("anchor", attrs)
    else:
        raise ValueError(f"No source-local TEI mapping for <{localname}>")

    if source.text:
        target.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            _append_text(target, child.tail)
            continue
        if _local(child) in FORMAT_ONLY:
            _append_text(target, child.tail)
            continue
        target.append(_map_node(child))
        _append_text(target, child.tail)
    return target


def _header(
    root: etree._Element,
    source_bytes: bytes,
    source_sha256: str,
    source_url: str,
) -> etree._Element:
    title = _first_text(root, "DC.Title") or "Holiness"
    author = _first_text(root, "DC.Creator") or "J. C. Ryle"
    publisher = _first_text(root, "DC.Publisher")
    print_source = _first_text(root, "published") or "London: James Clarke & Co., Ltd."
    electronic_created = _first_text(root, "DC.Date")

    header = _tei("teiHeader")
    file_desc = _tei("fileDesc")
    title_stmt = _tei("titleStmt")
    title_stmt.append(_tei("title", text=title))
    title_stmt.append(_tei("author", text=author))
    resp_stmt = _tei("respStmt")
    resp_stmt.append(_tei("resp", text="retained source provider"))
    resp_stmt.append(_tei("name", text="Christian Classics Ethereal Library"))
    title_stmt.append(resp_stmt)
    file_desc.append(title_stmt)

    publication = _tei("publicationStmt")
    publication.append(_tei("publisher", text="Open Christian Data"))
    availability = _tei("availability", {"status": "unknown"})
    availability.append(
        _tei(
            "p",
            text="Nonaccepted technical reconstruction; rights review and publication authorization remain open.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)

    source_desc = _tei("sourceDesc")
    bibl = _tei("bibl", {"type": "retained-witness"})
    bibl.append(_tei("title", text=title))
    bibl.append(_tei("author", text=author))
    if publisher:
        bibl.append(_tei("publisher", text=publisher))
    bibl.append(_tei("ptr", {"target": source_url}))
    bibl.append(_tei("idno", {"type": "sha256"}, source_sha256))
    bibl.append(_tei("note", {"type": "print-source"}, print_source))
    bibl.append(_tei("note", {"type": "title-page-edition"}, "THIS EDITION 1952"))
    bibl.append(
        _tei(
            "note",
            {
                "type": "exact-retained-source-bytes",
                "subtype": "base64",
                "n": source_sha256,
            },
            base64.b64encode(source_bytes).decode("ascii"),
        )
    )
    source_desc.append(bibl)

    notes_stmt = _tei("notesStmt")
    description = _first_text(root, "description")
    if description:
        notes_stmt.append(_tei("note", {"type": "source-description"}, description))
    if electronic_created:
        notes_stmt.append(
            _tei("note", {"type": "electronic-created"}, electronic_created)
        )
    identifiers = "; ".join(
        f"{name}={_first_text(root, name)}"
        for name in ("publisherID", "authorID", "bookID", "workID", "bkgID")
        if _first_text(root, name)
    )
    if identifiers:
        notes_stmt.append(_tei("note", {"type": "source-identifiers"}, identifiers))
    file_desc.append(notes_stmt)
    file_desc.append(source_desc)
    header.append(file_desc)

    profile = _tei("profileDesc")
    lang_usage = _tei("langUsage")
    lang_usage.append(_tei("language", {"ident": "en"}, "English"))
    profile.append(lang_usage)
    header.append(profile)
    revision = _tei("revisionDesc")
    revision.append(
        _tei(
            "change",
            {"status": "partial"},
            "Technical source-to-TEI reconstruction; visual, human, rights, IR, and publication gates remain open.",
        )
    )
    header.append(revision)
    return header


def _accountability(
    source_manifest: SourceManifest,
    source_bytes: bytes,
    root: etree._Element,
    features: list[dict[str, object]],
) -> dict[str, object]:
    counts, census = _census(root)
    formatting = dict(
        sorted(
            Counter(
                str(feature["source_qname"])
                for feature in features
                if feature["disposition"] == "formatting-only-excluded"
            ).items()
        )
    )
    return {
        "contract": "ocd-ryle-holiness-source-accountability-v1",
        "source_id": str(source_manifest.record["source_id"]),
        "source_path": "raw/ccel/ryle/holiness.xml",
        "source_bytes": len(source_bytes),
        "source_sha256": _sha(source_bytes),
        "source_census": census,
        "element_counts": counts,
        "lexical_events": _lexical_events(root),
        "member_census": {"included": 1, "excluded": 0, "retained_family_total": 1},
        "features": features,
        "represented_element_count": sum(
            feature["disposition"] == "represented" for feature in features
        ),
        "formatting_only_excluded_element_count": sum(
            feature["disposition"] == "formatting-only-excluded"
            for feature in features
        ),
        "unsupported_element_count": 0,
        "formatting_only_tags": formatting,
    }


def _carrier_ledger(features: list[dict[str, object]]) -> etree._Element:
    ledger = _tei(
        "div",
        {
            XML_ID: "ryle-holiness-source-ledger",
            "type": "source-accountability",
        },
    )
    ledger.append(_tei("head", text="Complete retained source element ledger"))
    for feature in features:
        ordinal = str(feature["feature_id"]).rsplit("-", 1)[-1]
        carrier = _tei(
            "ab",
            {
                XML_ID: f"ryle-holiness-source-feature-{ordinal}",
                "type": "source-element",
                "subtype": str(feature["source_qname"]),
                "n": str(feature["source_child_ordinal"]),
                "corresp": "urn:source-xpath:"
                + quote(str(feature["source_selector"]), safe=""),
            },
        )
        carrier.append(
            _tei("seg", {"type": "direct-text"}, str(feature["source_direct_text"]))
        )
        carrier.append(
            _tei("seg", {"type": "tail-text"}, str(feature["source_tail_text"]))
        )
        carrier.append(
            _tei(
                "seg",
                {"type": "source-attributes"},
                _canonical(feature["source_attributes"]).decode("utf-8").rstrip("\n"),
            )
        )
        ledger.append(carrier)
    return ledger


def _content(
    root: etree._Element,
    source_bytes: bytes,
    source_sha256: str,
    source_url: str,
    features: list[dict[str, object]],
) -> bytes:
    tei = _tei("TEI", {XML_ID: "ryle-holiness"})
    tei.append(_header(root, source_bytes, source_sha256, source_url))
    text = _tei("text")
    front = _tei("front")
    body = _tei("body")
    back = _tei("back")
    for source_div in root.xpath("./ThML.body/*"):
        if not isinstance(source_div.tag, str):
            continue
        if _local(source_div) in FORMAT_ONLY:
            continue
        mapped = _map_node(source_div)
        source_id = source_div.get("id")
        if source_id in {"i", "ii"}:
            front.append(mapped)
        elif source_id == "iii":
            body.append(mapped)
        elif source_id == "iv":
            back.append(mapped)
        else:
            body.append(mapped)
    if len(back) == 0:
        back.append(_tei("div", {"type": "source-support"}))
    back.append(_carrier_ledger(features))
    if len(front):
        text.append(front)
    text.append(body)
    if len(back):
        text.append(back)
    tei.append(text)
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "reconstruction profile",
    )
    policy = _strict_json(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "validation policy",
    )
    schema = _strict_json(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "source accountability schema",
    )
    source_bytes = source_manifest.authority_path(SOURCE_AUTHORITY).read_bytes()
    source_sha256 = _sha(source_bytes)
    if len(source_bytes) != profile["source_bytes"] or source_sha256 != profile["source_sha256"]:
        raise ValueError("retained Holiness source binding drifted")
    config = _strict_json(
        source_manifest.authority_path("work-config").read_bytes(), "work config"
    )
    if config.get("resource_id") != "ryle-holiness" or config.get("source_hash") != f"sha256:{source_sha256}":
        raise ValueError("Holiness work config source binding drifted")
    root = _parse(source_bytes)
    if _local(root) != "ThML":
        raise ValueError("Holiness retained root is not ThML")
    counts, census = _census(root)
    if counts != profile["element_counts"] or census != profile["source_census"]:
        raise ValueError("Holiness source census drifted")
    features = _features(root)
    if len(features) != profile["source_census"]["elements"]:
        raise ValueError("Holiness source feature inventory drifted")
    accountability = _accountability(source_manifest, source_bytes, root, features)
    if accountability["represented_element_count"] != profile["represented_element_count"]:
        raise ValueError("Holiness represented element count drifted")
    if accountability["formatting_only_excluded_element_count"] != profile["formatting_only_excluded_element_count"]:
        raise ValueError("Holiness formatting exclusion count drifted")
    schema_errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if schema_errors:
        raise ValueError(f"Holiness source accountability schema failure: {schema_errors[0].message}")
    unresolved = policy.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("Holiness unresolved ledger is invalid")
    provenance = policy.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Holiness provenance policy is invalid")
    return {
        "README.source.md": source_manifest.authority_path("source-local-readme").read_bytes(),
        "content.tei.xml": _content(
            root,
            source_bytes,
            source_sha256,
            str(profile["source_url"]),
            features,
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
