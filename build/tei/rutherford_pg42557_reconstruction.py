"""Preserve the complete proofread Bonar edition, including its source structure."""

from collections import Counter
from hashlib import sha256
import json
from xml.etree.ElementTree import Element

import html5lib
from lxml import etree

from build.tei.tyerman_pg_html import TEI, block, node


def _convert(manifest):
    source = manifest.authority_path("retained-source").read_bytes()
    source.decode("utf-8", errors="strict")
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    if sha256(source).hexdigest() != profile["source_sha256"]:
        raise ValueError("Rutherford source differs from the bound profile")
    body = html5lib.parse(source, treebuilder="etree", namespaceHTMLElements=False).find(".//body")
    if body is None:
        raise ValueError("Rutherford HTML has no body")
    source_tags = dict(Counter(e.tag for e in body.iter() if isinstance(e.tag, str)))
    # This source puts two page anchors in one span; map both, preserving its break.
    compound_pages = 0
    for parent in list(body.iter()):
        for index, item in enumerate(list(parent)):
            if item.tag != "span" or "pagenum" not in item.get("class", "").split():
                continue
            anchors = list(item.iter("a"))
            if len(anchors) <= 1:
                continue
            if [a.get("id") for a in anchors] != ["Page_710", "Page_711"] or [c.tag for c in item] != ["a", "br", "a"]:
                raise ValueError("Unexpected compound page marker")
            separator, last = item[1], item[2]
            item.remove(separator)
            item.remove(last)
            following = Element("span", dict(item.attrib))
            following.append(last)
            following.tail, item.tail = item.tail, None
            parent.insert(index + 1, separator)
            parent.insert(index + 2, following)
            compound_pages += 1
    if compound_pages != 1:
        raise ValueError("Expected the source's one compound page marker")
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    root.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    header = node(root, "teiHeader")
    description = node(header, "fileDesc")
    titles = node(description, "titleStmt")
    node(titles, "title").text = "Letters of Samuel Rutherford (Bonar, Third Edition)"
    node(titles, "author").text = "Samuel Rutherford"
    node(titles, "editor").text = "Andrew A. Bonar"
    node(node(description, "publicationStmt"), "p").text = "Source reconstruction; acceptance and publication are separate."
    node(node(description, "sourceDesc"), "p").text = "Complete retained Project Gutenberg 42557 electronic edition, produced by Colin Bell, Julia Neufeld and Distributed Proofreaders."
    text = node(root, "text")
    regions = {name: node(node(text, name), "div", type=f"source-{name}") for name in ("front", "body", "back")}
    for child in body:
        if not isinstance(child.tag, str):
            continue
        region = "front" if child.tag == "header" else "back" if child.tag == "footer" else "body"
        if child.tag == "footer":
            wrapper = node(regions[region], "div", type="provider-license")
            wrapper.set("{http://www.w3.org/XML/1998/namespace}id", child.get("id"))
            node(wrapper, "ab").text = "".join(child.itertext())
            wrapper.tail = child.tail
        else:
            block(child, node(regions[region], "div", type="source-carrier"))
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    accounting = {"contract": "ocd-rutherford-pg42557-accounting-v1", "source_sha256": profile["source_sha256"],
                  "source_tags": source_tags, "compound_page_mapping": "One source span maps ordered Page_710 and Page_711 anchors with the original break retained.",
                  "tei_sha256": sha256(content).hexdigest(), "scope": "Complete Bonar electronic edition; no Martin material used.",
                  "html_head": "Retained unchanged as metadata/style support; not book text."}
    encoded = lambda value: (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    return {"content.tei.xml": content, "source-accountability.json": encoded(accounting),
            "provenance.json": encoded({"provider": "Project Gutenberg", "ebook": "42557", "source_sha256": profile["source_sha256"]}),
            "unresolved.jsonl": b"", "README.source.md": manifest.authority_path("readme").read_bytes()}


_convert.converter_id = "ocd-rutherford-pg42557-complete-html-to-tei"
_convert.converter_version = "1"
