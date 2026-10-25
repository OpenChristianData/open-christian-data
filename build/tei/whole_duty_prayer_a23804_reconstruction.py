"""Build a byte-preserving candidate for the complete retained TCP A23804 TEI."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-tcp-a23804-exact-tei-p5"
CONVERTER_VERSION = "1"
SOURCE_SHA256 = "4ce798180f8b9ef8c9b9cd9200b50a9c324ab858c7aad07d1e7d22931ee2a5f1"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _inspect(content: bytes) -> tuple[dict[str, int], dict[str, int], dict[str, object]]:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_comments=False,
        huge_tree=True,
    )
    document = etree.fromstring(content, parser)
    elements = [item for item in document.iter() if isinstance(item.tag, str)]
    counts = dict(
        sorted(Counter(etree.QName(item).localname for item in elements).items())
    )
    census = {
        "elements": len(elements),
        "attributes": sum(len(item.attrib) for item in elements),
        "text_nodes": sum(item.text is not None for item in elements),
        "tail_nodes": sum(item.tail is not None for item in elements),
        "characters": sum(len((item.text or "") + (item.tail or "")) for item in elements),
        "comments": len(document.xpath("//comment()")),
        "processing_instructions": len(document.xpath("//processing-instruction()")),
    }
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    text = lambda node: " ".join("".join(node.itertext()).split())
    root_text = document.xpath("/tei:TEI/tei:text", namespaces=ns)
    grouped_text = document.xpath("/tei:TEI/tei:text/tei:group/tei:text", namespaces=ns)
    notes = document.xpath(
        "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:biblFull/tei:notesStmt/tei:note",
        namespaces=ns,
    )
    divisions = document.xpath("//tei:div", namespaces=ns)
    page_breaks = document.xpath("//tei:pb", namespaces=ns)
    gaps = document.xpath("//tei:gap", namespaces=ns)
    glyphs = document.xpath("//tei:g", namespaces=ns)
    features: dict[str, object] = {
        "root": etree.QName(document).localname,
        "namespace": etree.QName(document).namespace,
        "tei_corpus_count": len(document.xpath("//tei:teiCorpus", namespaces=ns)),
        "title_statement_count": len(
            document.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt", namespaces=ns)
        ),
        "title_statement_titles": [
            text(item)
            for item in document.xpath(
                "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title",
                namespaces=ns,
            )
        ],
        "title_statement_authors": [
            text(item)
            for item in document.xpath(
                "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author",
                namespaces=ns,
            )
        ],
        "dlps_ids": [
            text(item)
            for item in document.xpath(
                "/tei:TEI/tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:idno[@type='DLPS']",
                namespaces=ns,
            )
        ],
        "top_level_text_count": len(root_text),
        "top_level_text_children": [etree.QName(item).localname for item in root_text[0]]
        if root_text
        else [],
        "grouped_work_text_count": len(grouped_text),
        "grouped_work_children": [etree.QName(item).localname for item in grouped_text[0]]
        if grouped_text
        else [],
        "front_div_types": [
            item.get("type")
            for item in document.xpath(
                "/tei:TEI/tei:text/tei:group/tei:text/tei:front/tei:div", namespaces=ns
            )
        ],
        "body_div_types": [
            item.get("type")
            for item in document.xpath(
                "/tei:TEI/tei:text/tei:group/tei:text/tei:body/tei:div", namespaces=ns
            )
        ],
        "back_div_types": [
            item.get("type")
            for item in document.xpath(
                "/tei:TEI/tei:text/tei:group/tei:text/tei:back/tei:div", namespaces=ns
            )
        ],
        "source_notes": [text(item) for item in notes],
        "division_count": len(divisions),
        "division_types": dict(
            sorted(Counter(item.get("type") or "(untyped)" for item in divisions).items())
        ),
        "head_count": len(document.xpath("//tei:head", namespaces=ns)),
        "page_breaks": [[item.get("n"), item.get("facs")] for item in page_breaks],
        "gap_count": len(gaps),
        "gap_reasons": dict(
            sorted(Counter(item.get("reason") or "(unspecified)" for item in gaps).items())
        ),
        "glyph_references": dict(
            sorted(Counter(item.get("ref") or "(unreferenced)" for item in glyphs).items())
        ),
        "graphic_count": len(document.xpath("//tei:graphic", namespaces=ns)),
        "facs_attribute_count": sum("facs" in item.attrib for item in elements),
        "note_signature_values": [
            text(item) for item in document.xpath("//tei:signed", namespaces=ns)
        ],
    }
    return counts, census, features


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source = source_manifest.authority_path("retained-tei-p5").read_bytes()
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    readme = source_manifest.authority_path("source-local-attribution-readme").read_bytes()
    source_sha = sha256(source).hexdigest()
    if (
        len(source) != profile["source_bytes"]
        or source_sha != SOURCE_SHA256
        or source_sha != profile["source_sha256"]
    ):
        raise ValueError("retained TCP A23804 source binding drifted")
    counts, census, features = _inspect(source)
    if (
        counts != profile["element_counts"]
        or census != profile["source_census"]
        or features != profile["source_features"]
    ):
        raise ValueError("retained TCP A23804 source census/features drifted")
    identity = {
        "work_id": source_manifest.record["work_id"],
        "textual_form_id": source_manifest.record["textual_form_id"],
        "edition_id": source_manifest.record["edition_id"],
        "acquisition_id": source_manifest.record["acquisition_id"],
    }
    if policy["identity"] != identity or policy["source_id"] != source_manifest.record["source_id"]:
        raise ValueError("A23804 policy identity/source binding drifted")
    accountability = policy["accountability"] | {
        "source_id": source_manifest.record["source_id"],
        "source_content_bytes": len(source),
        "source_content_sha256": source_sha,
        "candidate_content_bytes": len(source),
        "candidate_content_sha256": source_sha,
        "element_counts": counts,
        "source_census": census,
        "source_features": features,
    }
    return {
        "README.source.md": readme,
        "content.tei.xml": source,
        "provenance.json": _canonical(policy["provenance"]),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(row) for row in policy["unresolved"]),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
