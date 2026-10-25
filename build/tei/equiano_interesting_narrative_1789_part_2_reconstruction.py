"""Faithful ECCO-TCP ETS-to-TEI reconstruction for Equiano volume two."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-ecco-tcp-k053415-002-ets-to-tei-p5"
CONVERTER_VERSION = "1"
SOURCE_SHA256 = "f8898fcc3e788196168593f3c6bdd12e3ef9cbcba9328091917073ffa305c5ed"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_SIMPLE_TAGS = {
    "ABBR": "abbr",
    "ARGUMENT": "argument",
    "BODY": "body",
    "CLOSER": "closer",
    "DATE": "date",
    "DATELINE": "dateline",
    "FIGURE": "figure",
    "FRONT": "front",
    "HEAD": "head",
    "HI": "hi",
    "ITEM": "item",
    "L": "l",
    "LG": "lg",
    "LIST": "list",
    "OPENER": "opener",
    "P": "p",
    "Q": "q",
    "SALUTE": "salute",
    "SIGNED": "signed",
    "TRAILER": "trailer",
}


def _tei(local_name: str) -> str:
    return f"{{{TEI_NS}}}{local_name}"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse(content: bytes) -> etree._Element:
    return etree.fromstring(
        content,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _source_census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = list(root.iter())
    counts = Counter(etree.QName(element).localname for element in elements)
    census = {
        "elements": len(elements),
        "attributes": sum(len(element.attrib) for element in elements),
        "text_nodes": sum(element.text is not None for element in elements),
        "tail_nodes": sum(element.tail is not None for element in elements),
        "characters": sum(
            len((element.text or "") + (element.tail or "")) for element in elements
        ),
    }
    return dict(sorted(counts.items())), census


def _copy_content(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    for child in source:
        converted = _convert_element(child)
        converted.tail = child.tail
        target.append(converted)


def _convert_element(source: etree._Element) -> etree._Element:
    tag = etree.QName(source).localname
    if tag in {"DIV1", "DIV2"}:
        target = etree.Element(_tei("div"))
        target.set("type", source.get("TYPE", "unspecified").replace(" ", "_"))
        if source.get("N") is not None:
            target.set("n", source.get("N"))
    elif tag == "TEXT":
        target = etree.Element(_tei("floatingText"))
    elif tag == "LETTER":
        target = etree.Element(_tei("floatingText"))
        body = etree.SubElement(target, _tei("body"))
        letter = etree.SubElement(body, _tei("div"), type="letter")
        _copy_content(source, letter)
        return target
    elif tag == "PB":
        target = etree.Element(_tei("pb"))
        if source.get("N") is not None:
            target.set("n", source.get("N"))
        source_ref = source.get("REF")
        if source_ref is not None:
            target.set(
                "facs",
                "https://quod.lib.umich.edu/cgi/t/text/pageviewer-idx"
                "?cc=ecco&idno=004837188.0001.002&seq=" + source_ref,
            )
    elif tag == "GAP":
        target = etree.Element(_tei("gap"))
        target.set("reason", source.get("DESC", "unknown"))
        if source.get("RESP") is not None:
            target.set("resp", "#" + source.get("RESP"))
        if source.get("EXTENT") is not None:
            target.set("extent", source.get("EXTENT"))
        if source.get("DISP") is not None:
            target.set("rend", source.get("DISP"))
    elif tag == "NOTE":
        target = etree.Element(_tei("note"))
        place = {"foot": "bottom", "marg": "margin"}.get(
            source.get("PLACE", ""), source.get("PLACE")
        )
        if place:
            target.set("place", place)
        if source.get("N") is not None:
            target.set("n", source.get("N"))
    elif tag in _SIMPLE_TAGS:
        target = etree.Element(_tei(_SIMPLE_TAGS[tag]))
        if tag == "Q" and source.get("REND") is not None:
            target.set("rend", source.get("REND"))
        elif tag == "HI":
            target.set("rend", "source-emphasis")
    else:
        raise ValueError(f"unsupported ECCO-TCP source element {tag!r}")
    _copy_content(source, target)
    return target


def _header(source: etree._Element) -> etree._Element:
    header = etree.Element(_tei("teiHeader"))
    file_desc = etree.SubElement(header, _tei("fileDesc"))
    title_stmt = etree.SubElement(file_desc, _tei("titleStmt"))
    etree.SubElement(title_stmt, _tei("title")).text = (
        "The Interesting Narrative of the Life of Olaudah Equiano: or Gustavus "
        "Vassa, the African. Written by Himself, second edition, volume 2"
    )
    etree.SubElement(title_stmt, _tei("author")).text = "Equiano, Olaudah, b. 1745."
    publication_stmt = etree.SubElement(file_desc, _tei("publicationStmt"))
    etree.SubElement(publication_stmt, _tei("p")).text = (
        "Nonaccepted technical reconstruction candidate; publication is not authorized."
    )
    source_desc = etree.SubElement(file_desc, _tei("sourceDesc"))
    bibl = etree.SubElement(source_desc, _tei("bibl"))
    etree.SubElement(bibl, _tei("title")).text = (
        "The interesting narrative of the life of Olaudah Equiano: or Gustavus "
        "Vassa, the African. Written by himself."
    )
    etree.SubElement(bibl, _tei("author")).text = "Equiano, Olaudah, b. 1745."
    etree.SubElement(bibl, _tei("edition")).text = "Second edition."
    etree.SubElement(bibl, _tei("pubPlace")).text = "London"
    etree.SubElement(bibl, _tei("date")).text = "1789"
    for kind, value in (
        ("TCP", source.xpath("string(/ETS/EEBO/IDG/@ID)")),
        ("ESTC", "T61470"),
        ("Gale", source.xpath("string(/ETS/EEBO/IDG/BIBNO)")),
        ("image-set", source.xpath("string(/ETS/EEBO/IDG/VID)")),
        ("Michigan", "004837188.0001.002"),
    ):
        etree.SubElement(bibl, _tei("idno"), type=kind).text = value
    encoding_desc = etree.SubElement(header, _tei("encodingDesc"))
    project_desc = etree.SubElement(encoding_desc, _tei("projectDesc"))
    etree.SubElement(project_desc, _tei("p")).text = (
        "The pinned ECCO-TCP ETS source was transformed element-for-element into "
        "TEI P5 while retaining source text order, divisions, embedded documents, "
        "letters, pages, gaps, notes, quotations, verse groups, and typography."
    )
    profile_desc = etree.SubElement(header, _tei("profileDesc"))
    lang_usage = etree.SubElement(profile_desc, _tei("langUsage"))
    etree.SubElement(lang_usage, _tei("language"), ident="en").text = "English"
    source_changes = source.xpath("/ETS/TEMPHEAD/REVDESCR/CHANGE")
    if len(source_changes) != 1:
        raise ValueError("retained K053415.002 source revision history drifted")
    source_change = source_changes[0]
    revision_date = source_change.xpath("string(DATE)")
    revision_name = source_change.xpath("string(RESPSTMT/NAME)")
    revision_responsibility = source_change.xpath("string(RESPSTMT/RESP)")
    revision_item = source_change.xpath("string(ITEM)")
    if (
        revision_date,
        revision_name,
        revision_responsibility,
        revision_item,
    ) != ("2007-10-04", "Simon Charles", "MURP", "Proofed and reviewed"):
        raise ValueError("retained K053415.002 source revision metadata drifted")
    revision_desc = etree.SubElement(header, _tei("revisionDesc"))
    etree.SubElement(revision_desc, _tei("change"), when=revision_date).text = (
        f"{revision_item} by {revision_name}; responsibility "
        f"{revision_responsibility}."
    )
    etree.SubElement(revision_desc, _tei("change"), when="2026-08-31").text = (
        "Deterministic source-local ETS-to-TEI P5 reconstruction."
    )
    return header


def _transform_source(source_bytes: bytes) -> bytes:
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained K053415.002 source binding drifted")
    source = _parse(source_bytes)
    if source.tag != "ETS":
        raise ValueError("retained K053415.002 source root is not ETS")
    source_text = source.xpath("/ETS/EEBO/TEXT")
    if len(source_text) != 1:
        raise ValueError("retained K053415.002 source has no unique outer TEXT")
    root = etree.Element(_tei("TEI"), nsmap={None: TEI_NS})
    root.set(f"{{{XML_NS}}}id", "ecco-tcp-k053415-002")
    root.append(_header(source))
    text = etree.SubElement(root, _tei("text"))
    text.set(f"{{{XML_NS}}}lang", "en")
    _copy_content(source_text[0], text)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_bytes = source_manifest.authority_path("retained-ets-xml").read_bytes()
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    source_sha256 = _sha(source_bytes)
    if len(source_bytes) != profile["source_bytes"] or source_sha256 != SOURCE_SHA256 or source_sha256 != profile["source_sha256"]:
        raise ValueError("retained K053415.002 source binding drifted")
    if policy["source_id"] != source_manifest.record["source_id"]:
        raise ValueError("K053415.002 validation policy source binding drifted")
    source_root = _parse(source_bytes)
    counts, census = _source_census(source_root)
    if counts != profile["element_counts"] or census != profile["source_census"]:
        raise ValueError("retained K053415.002 source census drifted")
    candidate_bytes = _transform_source(source_bytes)
    candidate_root = _parse(candidate_bytes)
    candidate_counts, candidate_census = _source_census(candidate_root)
    if candidate_counts != profile["candidate_element_counts"]:
        raise ValueError("K053415.002 candidate element mapping drifted")
    source_text = "".join(source_root.xpath("/ETS/EEBO/TEXT")[0].itertext())
    candidate_text = "".join(candidate_root.xpath("//*[local-name()='text']")[0].itertext())
    if candidate_text != source_text:
        raise ValueError("K053415.002 source text order or characters were not preserved")
    accountability = {
        **policy["accountability"],
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source_bytes),
        "source_content_sha256": source_sha256,
        "candidate_content_bytes": len(candidate_bytes),
        "candidate_content_sha256": _sha(candidate_bytes),
        "source_text_characters": len(source_text),
        "source_text_sha256": _sha(source_text.encode("utf-8")),
        "candidate_text_characters": len(candidate_text),
        "candidate_text_sha256": _sha(candidate_text.encode("utf-8")),
        "source_census": census,
        "element_counts": counts,
        "candidate_census": candidate_census,
        "candidate_element_counts": candidate_counts,
    }
    return {
        "README.source.md": source_manifest.authority_path("source-local-attribution-readme").read_bytes(),
        "content.tei.xml": candidate_bytes,
        "provenance.json": _canonical(policy["provenance"]),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
