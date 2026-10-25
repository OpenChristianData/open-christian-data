"""Complete retained Matthew/Mark envelopes; no accepted or published writes."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from urllib.parse import urlsplit

from lxml import etree

NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
WORK = "robertson-word-pictures-vol1"
MEMBERS = ("matthew", "mark")


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def read(raw):
    return etree.parse(
        BytesIO(raw),
        etree.XMLParser(
            load_dtd=False,
            no_network=True,
            resolve_entities=False,
            recover=False,
            remove_comments=False,
            remove_pis=False,
        ),
    )


def inventory(manifest):
    manifest.verify()
    if (
        manifest.record["work_id"] != WORK
        or manifest.record["scope"]["member_order"] != MEMBERS
    ):
        raise ValueError("assigned work/member boundary mismatch")
    result = []
    for member in MEMBERS:
        raw = manifest.authority_path(member).read_bytes()
        tree = read(raw)
        root = tree.getroot()
        if root.tag != "ThML" or [n.tag for n in root] != ["ThML.head", "ThML.body"]:
            raise ValueError("unsupported ThML envelope")
        nodes = []
        for node in root.iter():
            if not isinstance(node.tag, str):
                raise ValueError("unsupported in-root non-element carrier")
            nodes.append(
                {
                    "path": tree.getpath(node),
                    "parent": tree.getpath(node.getparent())
                    if node.getparent() is not None
                    else None,
                    "tag": node.tag,
                    "attributes": dict(node.attrib),
                    "text": node.text,
                    "tail": node.tail,
                    "disposition": "readable-body"
                    if node is root.find("ThML.body")
                    or root.find("ThML.body") in node.iterancestors()
                    else "retained-envelope-and-header-observations",
                }
            )
        before = []
        sibling = root.getprevious()
        while sibling is not None:
            if not isinstance(sibling, etree._Comment):
                raise ValueError("unsupported prolog carrier")
            before.insert(0, sibling.text)
            sibling = sibling.getprevious()
        if root.getnext() is not None:
            raise ValueError("unsupported epilog carrier")
        result.append(
            {
                "member": member,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "raw_base64": base64.b64encode(raw).decode("ascii"),
                "element_count": len(nodes),
                "nodes": nodes,
                "shell": {
                    "doctype": tree.docinfo.doctype,
                    "comments": before,
                    "xml_version": tree.docinfo.xml_version,
                    "encoding": tree.docinfo.encoding,
                },
                "body_divisions": [
                    dict(n.attrib) for n in root.findall("ThML.body/div1")
                ],
                "chapters": [dict(n.attrib) for n in root.findall(".//scripCom")],
            }
        )
    profile = json.loads(manifest.authority_path("profile").read_bytes())
    for actual, expected in zip(result, profile["members"], strict=True):
        for key in (
            "member",
            "bytes",
            "sha256",
            "element_count",
            "body_divisions",
            "chapters",
            "shell",
        ):
            if actual[key] != expected[key]:
                raise ValueError(f"{actual['member']}: profile mismatch: {key}")
    return result


def mapped(node, member):
    names = {
        "div1": "div",
        "div2": "div",
        "div": "div",
        "h1": "head",
        "h2": "head",
        "h3": "head",
        "p": "p",
        "a": "ref",
        "scripRef": "ref",
        "i": "hi",
        "b": "hi",
        "span": "hi",
        "scripCom": "anchor",
        "insertIndex": "anchor",
        "ul": "list",
        "li": "item",
    }
    if node.tag not in names:
        raise ValueError(f"unsupported body carrier: {node.tag}")
    target = etree.Element("{" + NS + "}" + names[node.tag])
    if node.get("id"):
        target.set("{" + XML + "}id", member + "-" + node.get("id"))
    if node.get("lang"):
        target.set("{" + XML + "}lang", node.get("lang"))
    if node.tag in ("div1", "div2", "div"):
        target.set("type", "source-" + node.tag)
        if node.get("title"):
            target.set("n", node.get("title"))
        for pointer in ("prev", "next"):
            if node.get(pointer):
                target.set(pointer, "#" + member + "-" + node.get(pointer))
    elif node.tag in ("h1", "h2", "h3"):
        target.set("type", "source-" + node.tag)
    elif node.tag in ("i", "b", "span"):
        rendition = {"i": "italic", "b": "bold", "span": node.get("style", "")}[
            node.tag
        ]
        if rendition:
            target.set("rend", rendition)
    elif node.tag in ("a", "scripRef"):
        target.set("type", "scripture" if node.tag == "scripRef" else "source-link")
        link = node.get("href") if node.tag == "a" else node.get("osisRef")
        if link is not None:
            if node.tag == "a":
                uri = urlsplit(link)
                if uri.fragment and not (uri.scheme or uri.netloc or uri.path):
                    # Keep the exact query spelling/order, including scripture context.
                    context, separator, fragment = link.partition("#")
                    link = context + separator + member + "-" + fragment
            target.set("target", link)
        if node.get("passage"):
            target.set("n", node.get("passage"))
        if node.get("version"):
            target.set("subtype", node.get("version"))
    elif node.tag in ("scripCom", "insertIndex"):
        target.set("type", "source-" + node.tag)
        if node.get("passage"):
            target.set("n", node.get("passage"))
        if node.get("osisRef"):
            target.set("corresp", node.get("osisRef"))
        if node.get("type"):
            target.set("subtype", node.get("type"))
    if node.get("class") or node.get("style") and node.tag != "span":
        target.set(
            "rend", " ; ".join(node.get(a) for a in ("class", "style") if node.get(a))
        )
    target.text, target.tail = node.text, node.tail
    destination = target
    seen_prose = False
    for child in node:
        if child.tag in ("h1", "h2", "h3") and seen_prose:
            destination = etree.SubElement(
                target, "{" + NS + "}div", type="source-heading-section"
            )
        destination.append(mapped(child, member))
        if child.tag not in ("h1", "h2", "h3", "scripCom"):
            seen_prose = True
    return target


def convert(manifest):
    records = inventory(manifest)
    root = etree.Element("{" + NS + "}TEI", nsmap={None: NS})

    def add(parent, tag, text=None, **attrs):
        node = etree.SubElement(parent, "{" + NS + "}" + tag, **attrs)
        node.text = text
        return node

    header = add(root, "teiHeader")
    desc = add(header, "fileDesc")
    title = add(desc, "titleStmt")
    add(
        title,
        "title",
        "Word Pictures in the New Testament: assigned Matthew/Mark cohort",
    )
    add(
        add(desc, "publicationStmt"),
        "p",
        "Nonaccepted reconstruction; no rights or publication decision.",
    )
    source_desc = add(desc, "sourceDesc")
    for name in MEMBERS:
        source = read(manifest.authority_path(name).read_bytes()).getroot()
        add(source_desc, "p", source.findtext(".//DC.Title"), n=name)
    body = add(add(root, "text"), "body")
    for name in MEMBERS:
        source = (
            read(manifest.authority_path(name).read_bytes()).getroot().find("ThML.body")
        )
        member = add(body, "div", type="retained-member", n=name)
        member.text = source.text
        for node in source:
            member.append(mapped(node, name))
    return {
        "content.tei.xml": etree.tostring(root, xml_declaration=True, encoding="UTF-8"),
        "source-accountability.json": encoded({"work_id": WORK, "members": records}),
        "provenance.json": encoded(
            {
                "work_id": WORK,
                "source_manifest_sha256": manifest.sha256,
                "member_order": MEMBERS,
            }
        ),
        "unresolved.jsonl": manifest.authority_path("unresolved").read_bytes(),
        "README.source.md": manifest.authority_path("readme").read_bytes(),
    }


convert.converter_id = "robertson-vol1-retained-thml"
convert.converter_version = "1"
