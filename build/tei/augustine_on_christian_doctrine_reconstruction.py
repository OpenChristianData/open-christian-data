"""Work-local faithful TEI route for the exact 37c-048 retained ThML member."""
from __future__ import annotations

import json
import re

from lxml import etree

from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.source_selection import verify_source_selection
from ocd_kernel.tei.writer import stamp_header, tei_el

NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TAGS = {
    "div1": "div", "div2": "div", "div3": "div", "p": "p",
    "h1": "head", "h2": "head", "span": "seg", "i": "hi", "em": "hi",
    "note": "note", "pb": "pb", "scripRef": "ref", "br": "lb",
}


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _convert(manifest):
    manifest.verify()
    root_path = manifest.repository_root
    acquisition = validate_acquisition(manifest.authority_path("acquisition"), root=root_path)
    work = load_work(manifest.authority_path("work"))
    verified = verify_source_selection(acquisition, work, root=root_path)
    if verified is None:
        raise ValueError("37c-048 requires an acquisition-owned source selection")
    raw = manifest.authority_path("retained-source").read_bytes()
    tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    roots = tree.xpath('/ThML/ThML.body/div1[@id="v"]')
    if len(roots) != 1:
        raise ValueError("37c-048 requires one exact div1 id=v work root")
    selected = roots[0]
    form = next(f for f in work["textual_forms"] if any(e["edition_id"] == acquisition["edition_id"] for e in f["editions"]))
    edition = next(e for e in form["editions"] if e["edition_id"] == acquisition["edition_id"])

    root = tei_el("TEI", {"xml:id": work["work_id"]})
    header = stamp_header(
        title=work["title"], author="Augustine", contributors=[],
        source_url=acquisition["url"], source_sha256=acquisition["source_sha256"],
        print_source=edition["containing_source"]["title"],
    )
    root.append(header)
    binding = header.find(f".//{{{NS}}}bibl")
    for key, value in {
        "work_id": work["work_id"], "textual_form_id": form["textual_form_id"],
        "edition_id": edition["edition_id"], "acquisition_id": acquisition["acquisition_id"],
        "source_sha256": acquisition["source_sha256"], "source_bytes": str(len(raw)),
        "source_selection_sha256": verified["selection_sha256"],
    }.items():
        binding.append(tei_el("idno", {"type": key}, text=value))
    binding.append(tei_el("note", {"type": "source-location"}, text=acquisition["source_selection"]["member_path"]))
    binding.append(tei_el("note", {"type": "source-scope"}, text=acquisition["source_scope"]))

    css_rules = []
    for style in tree.xpath('/ThML/ThML.head/style[@type="text/css"]'):
        css = style.text or ""
        if re.sub(r"[^{}]+\{[^{}]*\}", "", css).strip():
            raise ValueError("37c-048 source stylesheet contains unsupported CSS structure")
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            selector = selector.strip()
            if not re.fullmatch(r"(?:[A-Za-z][A-Za-z0-9]*)?\.[A-Za-z][A-Za-z0-9_-]*", selector):
                raise ValueError(f"37c-048 unsupported retained CSS selector: {selector}")
            css_rules.append((selector, declarations))
    if css_rules:
        encoding = tei_el("encodingDesc")
        tags_decl = tei_el("tagsDecl")
        encoding.append(tags_decl)
        header.append(encoding)
        for index, (selector, declarations) in enumerate(css_rules, 1):
            tags_decl.append(tei_el("rendition", {"xml:id": f"source-style-{index}", "scheme": "css", "selector": selector}, text=declarations))

    text = tei_el("text", {"xml:lang": "en"})
    body = tei_el("body")
    text.append(body)
    root.append(text)
    source_nodes = [node for node in selected.iter() if isinstance(node.tag, str)]
    source_targets = {node.get("id"): f"#src-{index}" for index, node in enumerate(source_nodes, 1) if node.get("id")}
    features = []
    selected_tag_counts = {}

    def convert(source, parent):
        if not isinstance(source.tag, str):
            if isinstance(source, etree._Comment):
                comment = etree.Comment(source.text or "")
                comment.tail = source.tail
                parent.append(comment)
                return
            raise ValueError("37c-048 selected subtree contains an unsupported XML node")
        if source.tag not in TAGS:
            raise ValueError(f"37c-048 unsupported selected ThML element: {source.tag}")
        index = len(features) + 1
        attrs = {"xml:id": f"src-{index}"}
        for source_key, tei_key in (("n", "n"), ("class", "rend"), ("style", "style"), ("lang", "xml:lang")):
            if source.get(source_key):
                attrs[tei_key] = source.get(source_key)
        if source.tag in ("i", "em"):
            attrs["rend"] = "italic"
        styles = [
            f"#source-style-{i}" for i, (selector, _) in enumerate(css_rules, 1)
            if selector.split(".")[-1] in source.get("class", "").split()
            and (selector.startswith(".") or selector.split(".")[0] == source.tag)
        ]
        if styles:
            attrs["rendition"] = " ".join(styles)
        if source.tag.startswith("div"):
            for name in ("type", "prev", "next"):
                if source.get(name):
                    value = source.get(name)
                    if name in ("prev", "next"):
                        value = source_targets.get(value, f"{acquisition['url']}#{value}")
                    attrs[name] = value
        if source.tag == "note" and source.get("place"):
            attrs["place"] = source.get("place")
        if source.tag == "pb" and source.get("href"):
            attrs["facs"] = source.get("href")
        if source.tag == "scripRef":
            if source.get("passage"):
                attrs["cRef"] = source.get("passage")
            if source.get("osisRef"):
                attrs["target"] = source.get("osisRef")
            if source.get("version"):
                attrs["source"] = source.get("version")
        node = tei_el(TAGS[source.tag], attrs)
        node.text, node.tail = source.text, source.tail
        parent.append(node)
        features.append({"source_path": tree.getroottree().getpath(source), "native_id": source.get("id"),
                         "source_tag": source.tag, "attributes": dict(source.attrib), "tei_id": f"src-{index}"})
        selected_tag_counts[source.tag] = selected_tag_counts.get(source.tag, 0) + 1
        for child in source:
            convert(child, node)

    convert(selected, body)
    carriers = []
    for position, carrier in enumerate(tree.find("ThML.body")):
        if not isinstance(carrier.tag, str):
            raise ValueError("37c-048 source body contains an unaccounted non-element carrier")
        carriers.append({
            "native_id": carrier.get("id"), "position": position, "title": carrier.get("title"),
            "disposition": "selected-work" if carrier is selected else "outside-assigned-work",
        })
    if [item["native_id"] for item in carriers] != ["i", "ii", "iii", "iv", "v", "vi", "vii"]:
        raise ValueError("37c-048 source carrier envelope differs from the reviewed source census")

    shell = {
        "xml_version": tree.getroottree().docinfo.xml_version,
        "encoding": tree.getroottree().docinfo.encoding,
        "doctype": tree.getroottree().docinfo.doctype,
        "public_id": tree.getroottree().docinfo.public_id,
        "system_url": tree.getroottree().docinfo.system_url,
        "pre_root_comments": [n.text for n in tree.getroottree().getroot().itersiblings(preceding=True)],
        "root_text": tree.text,
        "post_root_nodes": [],
        "head_xml": etree.tostring(tree.find("ThML.head"), encoding="unicode"),
    }
    readme = (
        f"# {work['title']}\n\nNonaccepted, source-bound technical candidate for Ticket 37c-048.\n\n"
        f"Retained source: {acquisition['source_selection']['member_path']}\n\n"
        f"SHA-256: {acquisition['source_sha256']}\n\n"
        "## Retained source header (verbatim XML)\n\n```xml\n"
        f"{shell['head_xml']}\n```\n\n"
        "## Mapping limits and unresolved statements\n\n"
        "- The complete selected div1 and its ordered descendants are reconstructed. Division types and next/prev navigation relations are retained in TEI. Original body paragraphs own visible headings; division title/shorttitle attributes remain verbatim in source-accountability as navigation metadata and do not create visible text.\n"
        "- The retained progress percentages and scripRef parsed strings are non-textual CCEL navigation/index fields. They remain in source-accountability records; human-readable passage and OSIS references remain in TEI.\n"
        "- The source's printSourceInfo states New York: The Christian Literature Publishing Co., 1890. This does not resolve the constituent-edition date.\n"
        "- The source's Public Domain label is source evidence only; rights clearance, human acceptance, release, and publication authorization are not established.\n"
    )
    unresolved = [
        {"scope": "constituent-edition-date", "status": "unresolved", "source_statement": "printSourceInfo states New York: The Christian Literature Publishing Co., 1890"},
        {"scope": "rights-and-publication", "status": "source-statement-only", "source_statement": "ThML.head/DC.Rights states Public Domain"},
        {"scope": "human-acceptance", "status": "not-decided"},
    ]
    return {
        "content.tei.xml": etree.tostring(root, encoding="utf-8", xml_declaration=True),
        "source-accountability.json": _json({
            "source_sha256": acquisition["source_sha256"], "source_bytes": len(raw),
            "selection_sha256": verified["selection_sha256"], "selected_unit": "v",
            "selected_features": features, "selected_tag_counts": selected_tag_counts,
            "body_carriers": carriers, "document_shell": shell,
        }),
        "provenance.json": _json({"work_id": work["work_id"], "acquisition_id": acquisition["acquisition_id"],
                                  "source_selection_sha256": verified["selection_sha256"]}),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme.encode("utf-8"),
    }


_convert.converter_id = "ocd-37c-048-augustine-on-christian-doctrine-to-tei"
_convert.converter_version = "2"
