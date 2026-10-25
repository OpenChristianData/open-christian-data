"""Route-local readable hierarchical TEI mapping for held hymn sources L671-L674."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest

TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
ROUTES = {
    "L671": ("cox-sacred-hymns-from-the-german-1841", "cox-sacred-hymns-1841-pg39440"),
    "L672": ("cox-hymns-from-the-german-1864", "cox-hymns-1864-second-revised-pg39439"),
    "L673": ("indian-methodist-hymn-book-1898", "pg30995-1898"),
    "L674": ("hymns-of-prudentius-1905", "pg14959-1905"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canon(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _el(parent: etree._Element, name: str, **attrs: str) -> etree._Element:
    return etree.SubElement(parent, f"{{{TEI}}}{name}", **attrs)


def _map_type(node: etree._Element) -> str:
    """Expose source roles as readable TEI types without inferring language."""
    classes = set((node.get("class") or "").split())
    if "hymn" in classes:
        return "hymn"
    if "verse" in classes:
        return "verse"
    if node.tag.lower() == "table" and "poem" in classes:
        return "poem"
    if node.tag.lower() == "table" and ("sn" in classes or "snt" in classes):
        return "source-note-table"
    if node.tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "heading-" + node.tag.lower()
    if node.tag.lower() == "blockquote":
        return "quotation"
    return "html-" + node.tag.lower()


def _tag_descriptor(node: etree._Element) -> str:
    attrs = dict(sorted(node.attrib.items()))
    return json.dumps({"tag": node.tag.lower(), "attributes": attrs}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_body(manifest: SourceManifest) -> tuple[dict, etree._Element, list[dict]]:
    profile = json.loads(manifest.authority_path("profile").read_text(encoding="utf-8"))
    archive = manifest.authority_path("retained-archive").read_bytes()
    if _sha(archive) != profile["archive_sha256"]:
        raise ValueError("retained hymn archive identity changed")
    with ZipFile(manifest.authority_path("retained-archive")) as zf:
        if zf.testzip() is not None:
            raise ValueError("retained hymn ZIP CRC failure")
        members = [{"path": item.filename, "bytes": item.file_size, "crc32": f"{item.CRC:08x}", "sha256": _sha(zf.read(item))}
                   for item in zf.infolist() if not item.is_dir()]
        html_member = profile.get("html_member")
        if html_member:
            raw = zf.read(html_member)
            authority_names = {a["name"] for a in manifest.record["authorities"]}
            extraction_name = "retained-html" if "retained-html" in authority_names else "extracted-html"
            if raw != manifest.authority_path(extraction_name).read_bytes():
                raise ValueError("archive HTML member differs from retained extraction")
        else:
            candidates = [m["path"] for m in members if m["path"].lower().endswith((".html", ".htm"))]
            if len(candidates) != 1:
                raise ValueError("source HTML member is ambiguous")
            html_member = candidates[0]
            raw = zf.read(html_member)
    if _sha(raw) != profile["html_sha256"]:
        raise ValueError("retained hymn HTML hash changed")
    root = html.fromstring(raw.decode("utf-8", errors="strict"))
    body = root.find(".//body")
    if body is None:
        raise ValueError("retained hymn source body is missing")
    if len(body) != profile.get("body_direct_children", len(body)):
        raise ValueError("retained hymn body boundary changed")
    return profile, body, members


def _emit_source(node: etree._Element, parent: etree._Element, path: str) -> None:
    if not isinstance(node.tag, str):
        comment = _el(parent, "seg", type="source-comment", n=path)
        comment.text = node.text or ""
        comment.tail = node.tail
        return
    tag = node.tag.lower()
    attrs = dict(sorted(node.attrib.items()))
    target_name = "ref" if tag == "a" else "seg"
    target = _el(parent, target_name, type=_map_type(node), n=path,
                 rend="source-tag:" + tag + ";source-attributes:" + json.dumps(attrs, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if tag == "a" and node.get("href") is not None:
        target.set("target", node.get("href"))
    if node.get("id"):
        target.set(XML_ID, node.get("id"))
    target.text = node.text
    for i, child in enumerate(node, 1):
        _emit_source(child, target, f"{path}/{i}")
    target.tail = node.tail


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    profile, source_body, members = _source_body(manifest)
    row = str(profile["ticket_id"])
    if row not in ROUTES or (profile["work_id"], profile["edition_id"]) != ROUTES[row]:
        raise ValueError("manifest does not identify one of the four authorized L671-L674 works")
    policy = json.loads(manifest.authority_path("policy").read_text(encoding="utf-8"))
    tei = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    tei.set(XML_ID, "pg" + str(profile["ebook_id"]) + "-" + str(profile["work_id"]))
    header = _el(tei, "teiHeader")
    file_desc = _el(header, "fileDesc")
    title_stmt = _el(file_desc, "titleStmt")
    _el(title_stmt, "title").text = str(profile["title"])
    if profile.get("author"):
        _el(title_stmt, "author").text = str(profile["author"])
    if profile.get("translator"):
        translator = _el(title_stmt, "respStmt")
        _el(translator, "resp").text = "Translator"
        _el(translator, "name").text = str(profile["translator"])
    _el(_el(file_desc, "publicationStmt"), "p").text = "Nonaccepted source-to-TEI candidate; rights clearance, human acceptance, and publication remain unresolved."
    bibl = _el(_el(file_desc, "sourceDesc"), "bibl")
    _el(bibl, "title").text = str(profile["title"])
    _el(bibl, "idno", type="gutenberg-ebook-id").text = str(profile["ebook_id"])
    _el(bibl, "idno", type="archive-sha256").text = str(profile["archive_sha256"])
    _el(bibl, "idno", type="html-sha256").text = str(profile["html_sha256"])
    _el(_el(header, "encodingDesc"), "p").text = "Each source HTML element is represented by a nested TEI seg carrying its source tag, attributes, class roles, and source path; source anchors are TEI refs with their retained href as target. Each top-level source carrier has one TEI p boundary, and mixed descendant text and tails retain exact source order. Hymn, verse, poem, heading, and quotation roles are carried where the retained HTML identifies them; language is not inferred from CSS classes."
    body = _el(_el(tei, "text"), "body")
    body.set("n", row)
    if source_body.text:
        _el(body, "p", rend="source-text", n="body.text").text = source_body.text
    for i, node in enumerate(source_body, 1):
        carrier = _el(body, "p", n=f"body/{i}")
        _emit_source(node, carrier, f"body/{i}")
    xml = etree.tostring(tei, encoding="UTF-8", xml_declaration=True)
    source_ids = [node.get("id") for node in source_body.iter() if isinstance(node.tag, str) and node.get("id")]
    internal_targets = [node.get("href")[1:] for node in source_body.iter()
                        if isinstance(node.tag, str) and node.get("href", "").startswith("#")]
    missing_targets = sorted(set(internal_targets) - set(source_ids))
    account = {"contract": "ocd-l671-l674-readable-source-accountability-v1", "ticket_id": row,
               "source_id": profile["source_id"], "work_id": profile["work_id"], "edition_id": profile["edition_id"],
               "archive_sha256": profile["archive_sha256"], "html_sha256": profile["html_sha256"],
               "archive_members": members, "body_text_sha256": _sha("".join(source_body.itertext()).encode()),
               "carriers": profile["carriers"], "carrier_node_count": len(profile["carriers"]),
               "source_anchor_count": sum(1 for node in source_body.iter() if isinstance(node.tag, str) and node.tag.lower() == "a"),
               "tei_ref_count": sum(1 for node in tei.iter() if etree.QName(node).localname == "ref"),
               "source_id_count": len(source_ids), "source_ids_sha256": _sha(_canon(source_ids)),
               "source_internal_ref_count": len(internal_targets), "unresolved_internal_target_count": len(missing_targets),
               "tei_sha256": _sha(xml), "mapping": "Nested readable source-tag and source-class TEI segments; anchors are TEI refs with source href as target; exact source text and tails remain ordered; one complete titled work occupies one TEI root."}
    return {"content.tei.xml": xml, "source-accountability.json": _canon(account),
            "README.source.md": manifest.authority_path("readme").read_bytes(),
            "provenance.json": _canon(policy["provenance"]),
            "unresolved.jsonl": b"".join(_canon(item) for item in policy["unresolved"])}


_convert.converter_id = "ocd-l671-l674-readable-hymn-source-tei"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()
