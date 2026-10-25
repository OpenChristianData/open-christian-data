"""Source-wide TEI projection of the retained Boethius CCEL witness."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el


WORK_ID = "boethius-theological-tractates"
SOURCE_PATH = "raw/ccel/boethius/tracts.xml"
SOURCE_BYTES = 162_005
SOURCE_SHA256 = "406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8"
ROOT_IDS = ("i", "ii", "iii", "iv", "v")
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TAGS = {
    "div1": "div", "div2": "div", "div": "quote", "p": "p", "h1": "p",
    "h2": "p", "h3": "p", "pb": "pb", "note": "note", "i": "hi",
    "b": "hi", "sup": "hi", "span": "seg", "sync": "anchor",
    "unclear": "seg", "scripRef": "ref", "insertIndex": "milestone",
    "ul": "list", "li": "item", "a": "ref",
}


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    manifest.verify()
    raw = manifest.authority_path("retained-thml").read_bytes()
    if len(raw) != SOURCE_BYTES or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Boethius retained XML identity drifted")
    source = etree.parse(io.BytesIO(raw), etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False,
        remove_pis=False, huge_tree=True,
    ))
    body = source.getroot().find("ThML.body")
    if body is None:
        raise ValueError("Boethius retained XML has no ThML.body")
    roots = [node for node in body if isinstance(node.tag, str)]
    if tuple(node.get("id") for node in roots) != ROOT_IDS:
        raise ValueError("Boethius five-root source envelope drifted")
    source_ids = {node.get("id") for node in body.iter() if isinstance(node.tag, str) and node.get("id")}
    if len(source_ids) != sum(bool(node.get("id")) for node in body.iter() if isinstance(node.tag, str)):
        raise ValueError("Boethius source IDs are duplicated")
    tei = tei_el("TEI", {"xml:id": WORK_ID})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text="The Theological Tractates"))
    title_stmt.append(tei_el("author", text="Boethius"))
    file_desc.append(title_stmt)
    pub = tei_el("publicationStmt")
    pub.append(tei_el("publisher", text="Christian Classics Ethereal Library"))
    availability = tei_el("availability", {"status": "unknown"})
    availability.append(tei_el("p", text="Rights and publication require separate review."))
    pub.append(availability)
    file_desc.append(pub)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl")
    bibl.append(tei_el("title", text="The Theological Tractates, retained CCEL ThML witness"))
    bibl.append(tei_el("idno", {"type": "sha256"}, text=SOURCE_SHA256))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = tei_el("text", {"xml:lang": "en"})
    front = tei_el("front", {"xml:id": WORK_ID + "-front"})
    main = tei_el("body", {"xml:id": WORK_ID + "-body"})
    back = tei_el("back", {"xml:id": WORK_ID + "-back"})
    text.extend((front, main, back))
    tei.append(text)
    rows: list[dict[str, object]] = []
    comments: list[dict[str, object]] = []

    def emit(node: etree._Element, parent: etree._Element) -> None:
        if not isinstance(node.tag, str):
            if node.tag is not etree.Comment:
                raise ValueError("Boethius source contains unsupported non-element node")
            if (node.tail or "").strip():
                raise ValueError("Boethius source comment has visible tail text")
            comments.append({"text": node.text or "", "tail": node.tail or "",
                             "after_feature": len(rows), "disposition": "source-comment-ledger-only"})
            return
        if node.tag not in TAGS:
            raise ValueError(f"Boethius source tag has no TEI mapping: {node.tag}")
        ordinal = len(rows) + 1
        source_id = node.get("id")
        attrs = {"xml:id": f"{WORK_ID}-{source_id}" if source_id else f"{WORK_ID}-feature-{ordinal:06d}"}
        if node.get("n"):
            attrs["n"] = node.get("n")
        if node.get("title") and node.tag in {"div1", "div2"}:
            attrs["n"] = node.get("title")
        if node.get("class"):
            attrs["rend"] = "source-class-" + node.get("class")
        if node.get("style"):
            attrs["rend"] = "source-style-" + node.get("style")
        if node.tag in {"h1", "h2", "h3"}:
            attrs["rend"] = "source-" + node.tag
        if node.tag in {"i", "b", "sup"}:
            attrs["rend"] = {"i": "italic", "b": "bold", "sup": "superscript"}[node.tag]
        if node.tag == "unclear":
            attrs["type"] = "source-unclear"
        if node.get("lang"):
            attrs["xml:lang"] = node.get("lang").lower()
        if node.tag == "pb" and node.get("href"):
            attrs["facs"] = node.get("href")
        if node.tag == "insertIndex":
            attrs["unit"] = "insertIndex"
        if node.tag == "scripRef" and node.get("osisRef"):
            attrs["target"] = node.get("osisRef")
        if node.tag == "a":
            href = node.get("href")
            if not href or not href.startswith("#") or href[1:] not in source_ids:
                raise ValueError(f"Boethius source reference is unresolved: {href}")
            attrs["target"] = f"#{WORK_ID}-{href[1:]}"
        out = tei_el(TAGS[node.tag], attrs)
        out.text, out.tail = node.text, node.tail
        parent.append(out)
        rows.append({
            "ordinal": ordinal, "source_tag": node.tag, "source_id": source_id,
            "source_attributes": dict(node.attrib), "source_text": node.text or "",
            "source_tail": node.tail or "", "tei_id": attrs["xml:id"],
            "tei_tag": TAGS[node.tag], "tei_attributes": attrs,
        })
        for child in node:
            emit(child, out)

    front.text = body.text
    for index, node in enumerate(body):
        target = front if index < 3 else main if index == 3 else back
        emit(node, target)
    if len(rows) != 1119 or len(comments) != 10 or sum(row["source_tag"] == "a" for row in rows) != 136:
        raise ValueError("Boethius complete source feature or link census drifted")
    accountability = {
        "contract": "ocd-boethius-complete-envelope-accountability-v1",
        "source": {"path": SOURCE_PATH, "bytes": len(raw), "sha256": SOURCE_SHA256},
        "root_ids_in_order": list(ROOT_IDS),
        "root_disposition": {"front": ["i", "ii", "iii"], "body": ["iv"], "back": ["v"]},
        "source_body_text": body.text or "", "features": rows, "feature_count": len(rows),
        "comments": comments, "comment_count": len(comments),
    }
    provenance = {
        "status": "nonaccepted", "work_id": WORK_ID,
        "source_id": manifest.record["source_id"],
        "scope": "complete five-root retained CCEL ThML body",
        "human_acceptance": "absent", "rights": "unresolved", "publication": "not_ready",
    }
    unresolved = {"id": "boethius-edition-rights-acceptance", "status": "unresolved",
                  "detail": "Print edition identity, rights, human acceptance, and publication require separate review."}
    return {
        "content.tei.xml": etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False),
        "source-accountability.json": _json(accountability),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": _json(unresolved),
        "README.source.md": manifest.authority_path("source-local-attribution-readme").read_bytes(),
    }


_convert.converter_id = "ocd-boethius-complete-envelope-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    manifest = SourceManifest.load(arguments.source_manifest, repository_root=arguments.repository_root)
    print(reconstruct(manifest, arguments.destination, _convert).sha256)


if __name__ == "__main__":
    main()
