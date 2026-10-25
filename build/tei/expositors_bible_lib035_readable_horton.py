"""Source-order-preserving readable TEI for Horton's one CCEL edition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el


ROOT = Path(__file__).resolve().parents[2]
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {
    "horton-expositorprov": {
        "work_id": "expositors-bible--robert-f-horton",
        "source_path": "raw/ccel/expositors-bible/horton_expositorprov.xml",
        "sha256": "a7372596c60d053b539e957c01d29a54269da5c25b094cd7b373cb7e834e122d",
        "author": "R. F. Horton", "title": "The Book of Proverbs",
        "front": ("i", "ii"), "back": ("xxxiv", "xxxv", "xxxvi"),
    },
}
TAGS = {
    "div1": "div", "div2": "div", "div3": "div", "div4": "div",
    "p": "p", "h1": "p", "h2": "p", "h3": "p", "h4": "p",
    "a": "ref", "b": "hi", "br": "lb", "i": "hi", "small": "hi",
    "pb": "pb", "note": "note", "scripRef": "ref", "scripCom": "milestone",
    "table": "table", "tr": "row", "td": "cell", "img": "figure",
    "insertIndex": "milestone", "hr": "milestone", "span": "seg",
    "verse": "lg", "l": "l", "div": "div",
    "ul": "list", "li": "item", "em": "hi", "cite": "hi", "blockquote": "quote", "sup": "hi",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def convert(member_id: str) -> tuple[bytes, bytes]:
    member = MEMBERS[member_id]
    source_path = ROOT / member["source_path"]
    raw = source_path.read_bytes()
    if _sha(raw) != member["sha256"]:
        raise ValueError(f"{member_id} retained source hash drifted")
    source = etree.fromstring(raw, etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False,
        remove_pis=False, huge_tree=True,
    ))
    body = source.find("ThML.body")
    if body is None:
        raise ValueError(f"{member_id} lacks ThML.body")
    roots = [node for node in body if isinstance(node.tag, str)]
    root_ids = tuple(node.get("id") for node in roots)
    if root_ids != tuple(["i", "ii"] + ["iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi", "xxii", "xxiii", "xxiv", "xxv", "xxvi", "xxvii", "xxviii", "xxix", "xxx", "xxxi", "xxxii", "xxxiii", "xxxiv", "xxxv", "xxxvi"]):
        raise ValueError(f"{member_id} root IDs drifted")
    ids = [node.get("id") for node in body.iter() if isinstance(node.tag, str) and node.get("id")]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{member_id} source IDs are duplicated")
    id_set = set(ids)
    broken_links = [(node.get("id"), node.get("href")) for node in body.iter("a")
                    if (node.get("href") or "").startswith("#") and node.get("href")[1:] not in id_set]
    if broken_links:
        raise ValueError(f"{member_id} source-broken local links differ")
    tei = tei_el("TEI", {"xml:id": member_id})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text="The Expositor's Bible: " + member["title"]))
    file_desc.append(title_stmt)
    pub = tei_el("publicationStmt")
    pub.append(tei_el("p", text="Christian Classics Ethereal Library electronic witness; rights and publication require separate review."))
    file_desc.append(pub)
    source_desc = tei_el("sourceDesc")
    source_desc.append(tei_el("p", text="Retained CCEL ThML electronic witness by " + member["author"] + "; SHA-256 " + member["sha256"]))
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = tei_el("text", {"xml:lang": "en"})
    regions = {name: tei_el(name, {"xml:id": f"{member_id}-{name}"}) for name in ("front", "body", "back")}
    text.extend(regions.values())
    tei.append(text)
    features: list[dict[str, object]] = []
    comments: list[dict[str, object]] = []

    def emit(node: etree._Element, parent: etree._Element) -> None:
        if not isinstance(node.tag, str):
            if node.tag is not etree.Comment or (node.tail or "").strip():
                raise ValueError(f"{member_id} unexpected nontextual source node")
            comments.append({"text": node.text or "", "tail": node.tail or "",
                             "after_feature": len(features), "disposition": "source-comment-ledger-only"})
            return
        if node.tag not in TAGS:
            raise ValueError(f"{member_id} unmapped source tag {node.tag}")
        number = len(features) + 1
        source_id = node.get("id")
        attrs = {"xml:id": f"{member_id}-{source_id}" if source_id else f"{member_id}-feature-{number:06d}"}
        if node.tag.startswith("div"):
            attrs["type"] = "source-" + node.tag
            if node.get("title"):
                attrs["n"] = node.get("title")
        if node.tag == "div":
            attrs["type"] = "source-div"
        if node.tag.startswith("h") and node.tag[1:].isdigit():
            attrs["rend"] = "source-" + node.tag
        if node.tag in {"i", "b", "small", "em", "sup", "cite"}:
            attrs["rend"] = {"i": "italic", "b": "bold", "small": "small", "em": "emphasis", "sup": "superscript", "cite": "source-citation"}[node.tag]
        if node.tag == "span":
            attrs["type"] = "thml-span"
        if node.tag == "verse":
            attrs["type"] = "source-stanza"
        if node.tag == "l" and node.get("class"):
            attrs["rend"] = "source-class-" + node.get("class")
        if node.tag in {"p", "td"} and node.get("class"):
            attrs["rend"] = "source-class-" + node.get("class")
        if node.tag == "td":
            if node.get("colspan") not in {"1", "2"} or node.get("rowspan") != "1":
                raise ValueError(f"{member_id} source cell span differs")
            attrs["cols"] = node.get("colspan")
        if node.tag == "pb" and node.get("n"):
            attrs["n"] = node.get("n")
        if node.tag == "a":
            href = node.get("href")
            if href is None:
                if node.text or len(node):
                    tag = "seg"
                    attrs["type"] = "source-anchor"
                else:
                    tag = "anchor"
            else:
                if href.startswith("#"):
                    if href[1:] not in id_set:
                        tag = "seg"
                        attrs["type"] = "source-unresolved-link"
                        attrs["n"] = href
                    else:
                        tag = "ref"
                        attrs["target"] = f"#{member_id}-{href[1:]}"
                else:
                    tag = "ref"
                    attrs["target"] = href
        else:
            tag = TAGS[node.tag]
        if node.tag == "scripRef" and node.get("osisRef"):
            attrs["target"] = node.get("osisRef")
        if node.tag in {"scripCom", "insertIndex", "hr"}:
            if (node.text or "").strip() or len(node):
                raise ValueError(f"{member_id} textual administrative marker")
            attrs["unit"] = "horizontal-rule" if node.tag == "hr" else node.tag
        if node.tag == "br":
            attrs["type"] = "source-br"
        if node.tag == "div":
            tag = "quote"
        if node.tag == "blockquote":
            attrs["type"] = "source-blockquote"
        out = tei_el(tag, attrs)
        out.text, out.tail = node.text, node.tail
        if node.tag == "img":
            if node.get("src") != "/ccel/horton/expositorprov/files/provill.png" or node.get("alt") != "Provill" or node.get("title") != "Provill" or node.text or len(node):
                raise ValueError(f"{member_id} source image differs")
            out.append(tei_el("graphic", {"url": node.get("src")}))
            out.append(tei_el("figDesc", text=node.get("alt")))
            out.append(tei_el("label", text=node.get("title")))
        parent.append(out)
        features.append({"ordinal": number, "source_tag": node.tag, "source_id": source_id,
                         "source_attributes": dict(node.attrib), "source_text": node.text or "",
                         "source_tail": node.tail or "", "tei_id": attrs["xml:id"],
                         "tei_tag": tag, "tei_attributes": attrs})
        for child in node:
            emit(child, out)

    regions["front"].text = body.text
    for node in body:
        if not isinstance(node.tag, str):
            emit(node, regions["front"])
            continue
        part = "front" if node.get("id") in member["front"] else "back" if node.get("id") in member["back"] else "body"
        emit(node, regions[part])
    if len(features) != sum(isinstance(node.tag, str) for node in body.iter()) - 1:
        raise ValueError(f"{member_id} feature count differs")
    account = {"contract": "ocd-expositors-lib035-readable-horton-accounting-v1",
               "member_id": member_id, "source": {"path": member["source_path"], "bytes": len(raw),
                                               "sha256": member["sha256"]},
               "root_ids_in_order": root_ids,
               "root_disposition": {part: [node.get("id") for node in roots if
                                             ("front" if node.get("id") in member["front"] else "back" if node.get("id") in member["back"] else "body") == part]
                                    for part in regions},
               "source_body_text": body.text or "", "features": features,
               "feature_count": len(features), "comments": comments, "comment_count": len(comments),
               "broken_local_links": [{"source_id": source_id, "href": href} for source_id, href in broken_links]}
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True), _json(account)


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    manifest.verify()
    member_id = manifest.record["source_id"].removeprefix("ccel-expositors-lib035-readable-").removesuffix("-v1")
    if member_id not in MEMBERS:
        raise ValueError("Expositor Horton member identity differs")
    member = MEMBERS[member_id]
    if manifest.authority_path("retained-thml").read_bytes() != (ROOT / member["source_path"]).read_bytes():
        raise ValueError("Expositor candidate retained source authority differs")
    tei, account = convert(member_id)
    return {"content.tei.xml": tei, "source-accountability.json": account,
            "provenance.json": _json({"status": "nonaccepted", "work_id": member["work_id"],
                                      "source_id": manifest.record["source_id"],
                                      "scope": "complete retained CCEL electronic edition",
                                      "human_acceptance": "absent", "rights": "unresolved", "publication": "not_ready"}),
            "unresolved.jsonl": _json({"id": member_id + "-rights-and-review", "status": "unresolved",
                                          "detail": "Human acceptance, print collation, rights, and publication require separate review."}),
            "README.source.md": manifest.authority_path("source-local-attribution-readme").read_bytes()}


_convert.converter_id = "ocd-expositors-lib035-readable-horton-to-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    args = parser.parse_args()
    if args.source_manifest:
        manifest = SourceManifest.load(args.source_manifest, repository_root=ROOT)
        print(reconstruct(manifest, args.destination, _convert).sha256)
        return
    args.destination.mkdir(parents=True, exist_ok=True)
    for member_id in MEMBERS:
        tei, account = convert(member_id)
        (args.destination / f"{member_id}.tei.xml").write_bytes(tei)
        (args.destination / f"{member_id}.source-accountability.json").write_bytes(account)


if __name__ == "__main__":
    main()
