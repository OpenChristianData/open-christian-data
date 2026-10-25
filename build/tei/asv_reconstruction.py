"""LIB-023: preserve the complete retained ASV JSON as readable TEI."""

from __future__ import annotations

import hashlib
import json
from xml.etree import ElementTree as ET

NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"ASV duplicate key: {key}")
        result[key] = value
    return result


def _inventory(source):
    """Inventory all source fields before building any TEI nodes."""
    rows = []
    def field(pointer, value, target, attribute=None):
        rows.append({"pointer": pointer, "value_sha256": hashlib.sha256(_bytes(value)).hexdigest(),
                     "target": target, "attribute": attribute, "disposition": "preserved"})
    if list(source) != ["translation", "books"]:
        raise ValueError("ASV root envelope")
    if source["translation"] != "ASV: American Standard Version (1901)":
        raise ValueError("ASV translation identity")
    field("/translation", source["translation"], "asv-title")
    if not isinstance(source["books"], list) or len(source["books"]) != 66:
        raise ValueError("ASV book envelope")
    for b, book in enumerate(source["books"]):
        if list(book) != ["name", "chapters"] or not isinstance(book["name"], str):
            raise ValueError(f"ASV book shape {b}")
        field(f"/books/{b}/name", book["name"], f"asv-b{b+1}-title")
        if not isinstance(book["chapters"], list) or not book["chapters"]:
            raise ValueError(f"ASV chapter envelope {b}")
        for c, chapter in enumerate(book["chapters"]):
            if list(chapter) != ["chapter", "verses"] or type(chapter["chapter"]) is not int or chapter["chapter"] != c+1:
                raise ValueError(f"ASV chapter shape {b}/{c}")
            cid = f"asv-b{b+1}-c{c+1}"
            field(f"/books/{b}/chapters/{c}/chapter", chapter["chapter"], cid, "n")
            if not isinstance(chapter["verses"], list) or not chapter["verses"]:
                raise ValueError(f"ASV verse envelope {b}/{c}")
            for v, verse in enumerate(chapter["verses"]):
                if list(verse) != ["verse", "text"] or type(verse["verse"]) is not int or verse["verse"] != v+1 or not isinstance(verse["text"], str) or not verse["text"]:
                    raise ValueError(f"ASV verse shape {b}/{c}/{v}")
                vid = f"{cid}-v{v+1}"
                field(f"/books/{b}/chapters/{c}/verses/{v}/verse", verse["verse"], vid, "n")
                field(f"/books/{b}/chapters/{c}/verses/{v}/text", verse["text"], vid)
    return rows


def convert(manifest):
    manifest.verify()
    source_bytes = manifest.authority_path("asv-source").read_bytes()
    source = json.loads(source_bytes.decode("utf-8"), object_pairs_hook=_object)
    rows = _inventory(source)
    config = json.loads(manifest.authority_path("asv-config").read_bytes())
    if config["resource_id"] != "asv" or config["source_file"] != "raw/bible_databases/formats/json/ASV.json":
        raise ValueError("ASV work config identity")
    ET.register_namespace("", NS)
    def add(parent, name, text=None, **attrs):
        node = ET.SubElement(parent, f"{{{NS}}}{name}", attrs)
        node.text = text
        return node
    root = ET.Element(f"{{{NS}}}TEI", {f"{{{XML}}}id": "asv"})
    header = add(root, "teiHeader")
    description = add(header, "fileDesc")
    title = add(add(description, "titleStmt"), "title", source["translation"])
    title.set(f"{{{XML}}}id", "asv-title")
    add(add(description, "publicationStmt"), "p", "Nonaccepted reconstruction for review; publication is not authorized.")
    add(add(description, "sourceDesc"), "p", "Complete retained JSON witness: raw/bible_databases/formats/json/ASV.json. The provider label is preserved; a complete physical 1901 edition is not asserted.")
    body = add(add(root, "text"), "body")
    for b, book in enumerate(source["books"], 1):
        bn = add(body, "div", type="book", n=str(b))
        bn.set(f"{{{XML}}}id", f"asv-b{b}")
        head = add(bn, "head", book["name"])
        head.set(f"{{{XML}}}id", f"asv-b{b}-title")
        for chapter in book["chapters"]:
            c = chapter["chapter"]
            cn = add(bn, "div", type="chapter", n=str(c))
            cn.set(f"{{{XML}}}id", f"asv-b{b}-c{c}")
            for verse in chapter["verses"]:
                v = verse["verse"]
                vn = add(cn, "ab", verse["text"], type="verse", n=str(v))
                vn.set(f"{{{XML}}}id", f"asv-b{b}-c{c}-v{v}")
                vn.set(f"{{{XML}}}space", "preserve")
    bindings = {a["name"]: a["sha256"] for a in manifest.record["authorities"]}
    return {
        "content.tei.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n",
        "source-accountability.json": _bytes({"contract": "ocd-asv-accounting-v1", "source_sha256": hashlib.sha256(source_bytes).hexdigest(), "fields": rows, "excluded": []}),
        "provenance.json": _bytes({"source_manifest_sha256": manifest.sha256, "authorities": bindings, "converter": dict(manifest.record["converter"]), "scope": "complete retained ASV JSON; no complete-print-edition claim"}),
        "unresolved.jsonl": manifest.authority_path("asv-unresolved").read_bytes(),
        "README.source.md": manifest.authority_path("asv-readme").read_bytes(),
    }


convert.converter_id = "ocd-lib023-asv-json-to-tei"
convert.converter_version = "1"
