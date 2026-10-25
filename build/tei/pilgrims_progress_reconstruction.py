"""Direct retained Standard Ebooks Bunyan witness to nonaccepted TEI candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.lib.storage_topology import resolve_repo_path


CONVERTER_ID = "ocd-pilgrims-progress-retained-se-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
EPUB_TYPE = f"{{{EPUB}}}type"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _el(name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    node = etree.Element(f"{{{TEI}}}{name}")
    for key, value in (attrs or {}).items():
        node.set(XML_ID if key == "xml:id" else XML_LANG if key == "xml:lang" else key, value)
    node.text = text
    return node


def _profile(manifest: SourceManifest) -> dict[str, object]:
    value = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
    if value.get("contract") != "ocd-pilgrims-progress-reconstruction-profile-v1":
        raise ValueError("Pilgrim's Progress reconstruction profile mismatch")
    return value


def _policy(manifest: SourceManifest) -> dict[str, object]:
    value = json.loads(manifest.authority_path("validation-policy").read_bytes())
    if value.get("contract") != "ocd-pilgrims-progress-validation-policy-v1":
        raise ValueError("Pilgrim's Progress validation policy mismatch")
    return value


def _source_members(manifest: SourceManifest) -> list[tuple[str, Path, bytes]]:
    authorities = manifest.record["authorities"]
    members = []
    for authority in authorities:
        if authority.get("role") == "primary-source":
            path = manifest.authority_path(str(authority["name"]))
            logical = str(authority["path"]).split("john-bunyan_the-pilgrims-progress/", 1)[1]
            members.append((logical, path, path.read_bytes()))
    return sorted(members)


def _git_state(checkout: Path) -> dict[str, object]:
    safe = str(checkout.resolve(strict=True))
    def run(*args: str) -> str:
        return subprocess.run(["git", "-c", f"safe.directory={safe}", "-C", safe, *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout
    return {"commit": run("rev-parse", "HEAD").strip(), "tree": run("rev-parse", "HEAD^{tree}").strip(), "clean": run("status", "--porcelain=v1", "--untracked-files=all") == "", "tracked_members": sorted(item for item in run("ls-files").splitlines() if item)}


def _observations(logical: str, root: etree._ElementTree) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    number = 0
    for element in root.iter():
        qname = etree.QName(element)
        in_body = (qname.namespace == XHTML and qname.localname == "body") or any(
            etree.QName(ancestor).namespace == XHTML and etree.QName(ancestor).localname == "body"
            for ancestor in element.iterancestors()
        )
        disposition = "represented" if in_body else "evidence-only"
        number += 1
        path = root.getpath(element)
        records.append({"member": logical, "kind": "element", "path": path, "name": etree.QName(element).localname, "value_sha256": _sha(etree.QName(element).text.encode()), "disposition": disposition})
        for name, value in sorted(element.attrib.items()):
            number += 1
            records.append({"member": logical, "kind": "attribute", "path": path, "name": etree.QName(name).text, "value_sha256": _sha(value.encode()), "disposition": disposition})
        if element.text and element.text.strip():
            number += 1
            records.append({"member": logical, "kind": "text", "path": path + "/text()", "name": "text", "value_sha256": _sha(element.text.encode()), "disposition": disposition})
        if element.tail and element.tail.strip():
            number += 1
            records.append({"member": logical, "kind": "text", "path": path + "/following-sibling-text()", "name": "tail", "value_sha256": _sha(element.tail.encode()), "disposition": disposition})
    for index, record in enumerate(records, 1):
        record["observation_id"] = f"{logical}#{index:05d}"
    return records


def _tokens(node: etree._Element) -> set[str]:
    return set(node.get(EPUB_TYPE, "").split())


def _norm(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _line_values(paragraph: etree._Element) -> list[str]:
    values = [paragraph.text or ""]
    for child in paragraph:
        if etree.QName(child).localname == "br":
            values.append(child.tail or "")
        else:
            values[-1] += "".join(child.itertext()) + (child.tail or "")
    return [" ".join(value.split()) for value in values]


def _semantic_bindings(roots: Mapping[str, etree._ElementTree], spine: list[str], config: Mapping[str, object]) -> dict[str, object]:
    ns = {"x": XHTML, "epub": EPUB, "opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/", "xml": "http://www.w3.org/XML/1998/namespace"}
    spine_roots = [("src/epub/" + href, roots["src/epub/" + href]) for href in spine]
    refs = []
    inline = []
    verse = []
    cites = []
    for logical, tree in spine_roots:
        body = tree.find(".//x:body", ns)
        assert body is not None
        matter = next(item for item in _tokens(body) if item in {"frontmatter", "bodymatter", "backmatter"}).removesuffix("matter")
        for node in tree.xpath("//x:a[contains(concat(' ',@epub:type,' '),' noteref ')]", namespaces=ns):
            refs.append({"member": logical, "path": tree.getpath(node), "id": node.get("id"), "target": node.get("href"), "label": _norm(node)})
        for node in tree.xpath("//x:a|//x:abbr|//x:b|//x:strong|//x:i|//x:em|//x:cite|//x:span|//x:small|//x:sub|//x:sup|//x:q|//x:time|//x:br|//x:img", namespaces=ns):
            semantic_attributes = {name: value for name, value in (("id", node.get("id")), ("href", node.get("href")), ("src", node.get("src")), ("alt", node.get("alt")), ("datetime", node.get("datetime")), ("class", node.get("class")), ("xml:lang", node.get(XML_LANG)), ("epub:type", node.get(EPUB_TYPE))) if value is not None}
            inline.append({"member": logical, "path": tree.getpath(node), "carrier": etree.QName(node).localname, "class": node.get("class"), "language": node.get(XML_LANG), "epub_type": node.get(EPUB_TYPE), "semantic_attributes": semantic_attributes, "value_sha256": _sha(_norm(node).encode())})
        for node in tree.xpath("//x:cite", namespaces=ns):
            cites.append({"member": logical, "path": tree.getpath(node), "value": _norm(node)})
        groups = [node for node in tree.xpath("//*[@epub:type]", namespaces=ns) if _tokens(node) & {"z3998:poem", "z3998:verse", "z3998:song"}]
        for node in groups:
            kind = next(token.split(":")[-1] for token in ("z3998:poem", "z3998:verse", "z3998:song") if token in _tokens(node))
            stanzas = []
            for paragraph in node.xpath("./x:p", namespaces=ns):
                values = _line_values(paragraph)
                stanzas.append({"path": tree.getpath(paragraph), "line_count": len(values), "line_sha256": [_sha(value.encode()) for value in values]})
            verse.append({"member": logical, "path": tree.getpath(node), "genre": kind, "placement": matter, "stanzas": stanzas})
    endnotes = roots["src/epub/text/endnotes.xhtml"]
    note_bindings = []
    for note in endnotes.xpath("//x:li[@epub:type='endnote']", namespaces=ns):
        note_id = note.get("id")
        matching = [row for row in refs if str(row["target"]).rsplit("#", 1)[-1] == note_id]
        backs = note.xpath(".//x:a[contains(concat(' ',@epub:type,' '),' backlink ')]", namespaces=ns)
        if len(matching) != 1 or len(backs) != 1:
            raise ValueError("source note graph is not bijective")
        back = backs[0]
        note_bindings.append({"body_id": note_id, "body_path": endnotes.getpath(note), "body_text_sha256": _sha(_norm(note).encode()), "reference": matching[0], "backlink_path": endnotes.getpath(back), "backlink_target": back.get("href"), "backlink_label": _norm(back)})
    toc_tree = roots["src/epub/toc.xhtml"]
    toc = []
    for order, link in enumerate(toc_tree.xpath("//x:nav//x:a", namespaces=ns), 1):
        nav = link.xpath("ancestor::x:nav[1]", namespaces=ns)[0]
        toc.append({"order": order, "nav_type": nav.get(EPUB_TYPE), "depth": len(link.xpath("ancestor::x:li", namespaces=ns)), "path": toc_tree.getpath(link), "target": link.get("href"), "label": _norm(link), "link_type": link.get(EPUB_TYPE)})
    image_strings = []
    for logical, tree in sorted(roots.items()):
        if logical.endswith(".svg"):
            for node in tree.iter():
                path = tree.getpath(node)
                if node.text and node.text.strip():
                    image_strings.append({"member": logical, "path": path + "/text()", "kind": "svg-text", "value": node.text})
                if node.tail and node.tail.strip():
                    image_strings.append({"member": logical, "path": path + "/tail()", "kind": "svg-tail", "value": node.tail})
    for logical, tree in spine_roots:
        for node in tree.xpath("//x:img[@alt]", namespaces=ns):
            image_strings.append({"member": logical, "path": tree.getpath(node) + "/@alt", "kind": "xhtml-alt", "value": node.get("alt")})
    opf = roots["src/epub/content.opf"]
    metadata = {
        "config": {key: config.get(key) for key in ("title", "author", "contributors", "original_publication_year", "language", "original_language", "source_url", "source_edition")},
        "opf": {
            "titles": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:title", namespaces=ns)],
            "language": [_norm(node) for node in opf.xpath("//opf:metadata/dc:language", namespaces=ns)],
            "dates": [{"property": node.get("property"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:date|//opf:metadata/opf:meta[@property='dcterms:modified']", namespaces=ns)],
            "sources": [_norm(node) for node in opf.xpath("//opf:metadata/dc:source", namespaces=ns)],
            "creators": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:creator", namespaces=ns)],
            "contributors": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:contributor", namespaces=ns)],
            "rights": [_norm(node) for node in opf.xpath("//opf:metadata/dc:rights", namespaces=ns)],
            "long_description": [_norm(node) for node in opf.xpath("//opf:metadata/opf:meta[@property='se:long-description']", namespaces=ns)],
            "production_notes": [_norm(node) for node in opf.xpath("//opf:metadata/opf:meta[@property='se:production-notes']", namespaces=ns)],
        },
    }
    distinct = sorted({row["value"] for row in cites})
    rights_text = metadata["opf"]["rights"]
    if len(rights_text) != 1:
        raise ValueError("retained OPF must provide one exact rights statement")
    rights_claims = {"candidate_status": "nonaccepted", "source_member": "src/epub/content.opf", "source_path": opf.getpath(opf.xpath("//opf:metadata/dc:rights", namespaces=ns)[0]), "retained_opf_text": rights_text[0], "underlying_scope": "believed-US-public-domain-worldwide-uncertain", "contributor_scope": "CC0-1.0-dedication", "worldwide_clearance": False}
    return {"notes": note_bindings, "verse": verse, "inline": inline, "toc": toc, "image_strings": image_strings, "cite_occurrences": cites, "distinct_cite_strings": distinct, "metadata_claims": metadata, "rights_claims": rights_claims}


def _id_attrs(node: etree._Element) -> dict[str, str]:
    value = node.get("id")
    return {"xml:id": value} if value else {}


def _append_text(target: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(target):
        target[-1].tail = (target[-1].tail or "") + value
    else:
        target.text = (target.text or "") + value


def _corresp(logical: str, root: etree._ElementTree, node: etree._Element, suffix: str = "") -> str:
    return "#bunyan-source-" + _sha((logical + "|" + root.getpath(node) + suffix).encode())


def _epub_ana(node: etree._Element) -> str | None:
    tokens = node.get(EPUB_TYPE, "").split()
    return " ".join("epub:" + token for token in tokens) if tokens else None


def _inline(node: etree._Element, logical: str, root: etree._ElementTree) -> etree._Element | None:
    tag = etree.QName(node).localname
    tokens = _tokens(node)
    if tag == "a":
        attrs = _id_attrs(node)
        href = node.get("href", "")
        if "noteref" in tokens:
            attrs.update({"type": "note", "target": "#" + href.rsplit("#", 1)[-1]})
        elif "backlink" in tokens:
            attrs.update({"type": "backlink", "target": "#" + href.rsplit("#", 1)[-1]})
        else:
            attrs["target"] = href
        attrs["corresp"] = _corresp(logical, root, node)
        out = _el("ref", attrs)
    elif tag == "abbr":
        out = _el("abbr", {**_id_attrs(node), "corresp": _corresp(logical, root, node), **({"rend": node.get("class", "")} if node.get("class") else {})})
    elif tag in {"b", "strong"}:
        out = _el("hi", {**_id_attrs(node), "rend": "bold", "corresp": _corresp(logical, root, node)})
    elif tag in {"i", "em"}:
        out = _el("emph" if tag == "em" else "hi", {**_id_attrs(node), **({"rend": "italic"} if tag == "i" else {}), "corresp": _corresp(logical, root, node)})
    elif tag == "cite":
        out = _el("title", {**_id_attrs(node), "corresp": _corresp(logical, root, node)})
    elif tag in {"span", "small"}:
        attrs = _id_attrs(node)
        attrs["corresp"] = _corresp(logical, root, node)
        if node.get("class"):
            attrs["rend"] = node.get("class", "")
        lang = node.get(XML_LANG)
        if lang:
            attrs["xml:lang"] = lang
        out = _el("seg" if tag == "span" else "hi", attrs)
    elif tag in {"sub", "sup"}:
        out = _el("hi", {"rend": "subscript" if tag == "sub" else "superscript", "corresp": _corresp(logical, root, node)})
    elif tag == "q":
        out = _el("q", {"corresp": _corresp(logical, root, node)})
    elif tag == "time":
        when = node.get("datetime")
        out = _el("date", {**({"when": when} if when else {}), "corresp": _corresp(logical, root, node)})
    elif tag == "br":
        return _el("lb", {"corresp": _corresp(logical, root, node)})
    elif tag == "img":
        out = _el("figure", {"corresp": _corresp(logical, root, node)})
        if _epub_ana(node):
            out.set("ana", str(_epub_ana(node)))
        out.append(_el("graphic", {"url": node.get("src", "")}))
        if node.get("alt") is not None:
            out.append(_el("figDesc", text=node.get("alt", "")))
        return out
    else:
        out = _el("seg", {**_id_attrs(node), "corresp": _corresp(logical, root, node)})
    language = node.get(XML_LANG)
    if language:
        out.set(XML_LANG, language)
    if _epub_ana(node):
        out.set("ana", str(_epub_ana(node)))
    out.text = node.text
    for child in node:
        converted = _inline(child, logical, root)
        if converted is not None:
            out.append(converted)
        _append_text(out, child.tail)
    return out


def _verse_lines(paragraph: etree._Element, logical: str, root: etree._ElementTree) -> list[etree._Element]:
    lines = [_el("l", {"corresp": _corresp(logical, root, paragraph, "|line:1")})]
    _append_text(lines[-1], paragraph.text)
    for child in paragraph:
        if etree.QName(child).localname == "br":
            lines[-1].append(_inline(child, logical, root))
            lines.append(_el("l", {"corresp": _corresp(logical, root, paragraph, f"|line:{len(lines) + 1}")}))
        else:
            converted = _inline(child, logical, root)
            if converted is not None:
                lines[-1].append(converted)
        _append_text(lines[-1], child.tail)
    return lines


def _block(node: etree._Element, logical: str, root: etree._ElementTree) -> etree._Element | None:
    tag = etree.QName(node).localname
    tokens = _tokens(node)
    verse_kind = next((item.split(":")[-1] for item in ("z3998:poem", "z3998:verse", "z3998:song") if item in tokens), None)
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "hgroup"}:
        out = _el("head", _id_attrs(node))
    elif tag == "p":
        out = _el("p", _id_attrs(node))
    elif tag == "blockquote" and verse_kind:
        quote = _el("quote")
        group = _el("lg", {"type": verse_kind, "corresp": _corresp(logical, root, node)})
        for child in node:
            if etree.QName(child).localname == "p":
                stanza = _el("lg", {"type": "stanza", "corresp": _corresp(logical, root, child)})
                for line in _verse_lines(child, logical, root):
                    stanza.append(line)
                group.append(stanza)
            elif etree.QName(child).localname == "cite":
                converted = _block(child, logical, root)
                if converted is not None:
                    quote.append(converted)
        quote.insert(0, group)
        return quote
    elif tag == "blockquote":
        out = _el("quote")
    elif tag in {"ol", "ul"}:
        out = _el("list", {"type": "ordered" if tag == "ol" else "bulleted"})
    elif tag == "li":
        out = _el("item", _id_attrs(node))
    elif tag == "cite":
        out = _el("bibl")
    elif tag == "header":
        out = _el("div", {"type": "header"})
    elif tag == "footer":
        out = _el("div", {"type": "footer"})
    elif tag == "img":
        return _inline(node, logical, root)
    elif tag == "section":
        out = _el("div", {**_id_attrs(node), "type": next(iter(tokens), "section").split(":")[-1]})
    else:
        return _inline(node, logical, root)
    if out.get("corresp") is None:
        out.set("corresp", _corresp(logical, root, node))
    if _epub_ana(node):
        out.set("ana", str(_epub_ana(node)))
    out.text = node.text
    for child in node:
        child_tag = etree.QName(child).localname
        if child_tag in {"header", "footer"}:
            for grandchild in child:
                converted = _block(grandchild, logical, root)
                if converted is not None:
                    out.append(converted)
                _append_text(out, grandchild.tail)
        else:
            converted = _block(child, logical, root) if child_tag in {"section", "h1", "h2", "h3", "h4", "h5", "h6", "hgroup", "p", "blockquote", "ol", "ul", "li", "cite", "img"} else _inline(child, logical, root)
            if converted is not None:
                out.append(converted)
        _append_text(out, child.tail)
    return out


def _availability_text(rights_claims: Mapping[str, object]) -> str:
    return "Retained OPF rights statement: " + str(rights_claims["retained_opf_text"]) + " This reconstruction candidate is nonaccepted; generation and validation do not grant worldwide publication clearance."


def _readme_text(rights_claims: Mapping[str, object]) -> bytes:
    return (
        "# Source and rights\n\n"
        "Status: nonaccepted.\n\n"
        "Retained OPF rights statement:\n\n"
        + str(rights_claims["retained_opf_text"])
        + "\n\nThis reconstruction candidate is nonaccepted. Generation and validation do not establish worldwide publication clearance or replace human acceptance.\n\n"
        "Metadata review: config language en versus OPF en-GB; config contributors [] versus named OPF contributors; original 1678 versus digital 2020-05-07 dates; the retained extended title; and both Gutenberg and Internet Archive OPF source witnesses.\n"
    ).encode()


def _tei_header(profile: Mapping[str, object], source_set_sha: str, rights_claims: Mapping[str, object]) -> etree._Element:
    metadata = profile["metadata"]
    assert isinstance(metadata, dict)
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", text=str(metadata["title"])))
    title_stmt.append(_el("author", text=str(metadata["author"])))
    file_desc.append(title_stmt)
    publication = _el("publicationStmt")
    publication.append(_el("publisher", text="Open Christian Data"))
    availability = _el("availability", {"status": "unknown"})
    availability.append(_el("p", text=_availability_text(rights_claims)))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("title", text=str(metadata["title"])))
    bibl.append(_el("author", text=str(metadata["author"])))
    bibl.append(_el("editor", text=str(metadata["editor"])))
    bibl.append(_el("publisher", text="Standard Ebooks"))
    bibl.append(_el("ptr", {"target": str(metadata["source_url"])}))
    bibl.append(_el("idno", {"type": "sha256"}, source_set_sha))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = _profile(source_manifest)
    policy = _policy(source_manifest)
    members = _source_members(source_manifest)
    expected = profile["source_scope"]
    assert isinstance(expected, dict)
    if len(members) != 26 or sum(len(content) for _, _, content in members) != 6028743:
        raise ValueError("retained Bunyan member census drifted")
    observed_set = [{"path": logical, "bytes": len(content), "sha256": _sha(content)} for logical, _, content in members]
    if observed_set != expected["members"]:
        raise ValueError("retained Bunyan member identity drifted")
    checkout = resolve_repo_path(
        source_manifest.repository_root,
        "raw/standard_ebooks/john-bunyan_the-pilgrims-progress",
    )
    git_state = _git_state(checkout)
    if git_state != {"commit": expected["commit"], "tree": expected["tree"], "clean": True, "tracked_members": [row["path"] for row in observed_set]}:
        raise ValueError("retained Bunyan checkout revision drifted")

    roots: dict[str, etree._ElementTree] = {}
    all_observations: list[dict[str, object]] = []
    non_xml: list[dict[str, object]] = []
    for logical, path, content in members:
        try:
            root = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))
        except etree.XMLSyntaxError:
            non_xml.append({"member": logical, "bytes": len(content), "sha256": _sha(content), "disposition": profile["non_xml_dispositions"][logical]})
            continue
        roots[logical] = root
        all_observations.extend(_observations(logical, root))
    if len(roots) != 19 or len(all_observations) != 31735 or len(non_xml) != 7:
        raise ValueError("complete retained XML/non-XML accounting drifted")

    opf = roots["src/epub/content.opf"]
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    href_by_id = {node.get("id"): node.get("href") for node in opf.xpath("//opf:manifest/opf:item", namespaces=ns)}
    spine = [href_by_id[node.get("idref")] for node in opf.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    if spine != profile["spine"]:
        raise ValueError("OPF spine reading order drifted")
    semantic_bindings = _semantic_bindings(roots, spine, json.loads(source_manifest.authority_path("local-source-config").read_bytes()))
    if len(semantic_bindings["distinct_cite_strings"]) != 156:
        raise ValueError("source-derived cite-string inventory drifted")

    source_set_sha = _sha(_json({"contract": "ocd-source-member-set-v1", "members": observed_set}))
    tei = _el("TEI")
    rights_claims = semantic_bindings["rights_claims"]
    assert isinstance(rights_claims, dict)
    tei.append(_tei_header(profile, source_set_sha, rights_claims))
    text = _el("text")
    reading_order = _el("body")
    text.append(reading_order)
    tei.append(text)
    section_records = []
    for href in spine:
        logical = "src/epub/" + href
        root = roots[logical]
        body = root.find(f".//{{{XHTML}}}body")
        if body is None:
            raise ValueError(f"spine member {logical} has no XHTML body")
        matter = next((item.removesuffix("matter") for item in _tokens(body) if item in {"frontmatter", "bodymatter", "backmatter"}), None)
        if matter not in {"front", "body", "back"}:
            raise ValueError(f"spine member {logical} has no matter classification")
        sections = body.findall(f"{{{XHTML}}}section")
        if len(sections) != 1:
            raise ValueError(f"spine member {logical} must contain one source section")
        converted = _block(sections[0], logical, root)
        assert converted is not None
        converted.set("source", logical)
        converted.set("ana", f"#{matter}matter")
        reading_order.append(converted)
        heading = next(("".join(node.itertext()) for node in sections[0] if etree.QName(node).localname.startswith("h")), "")
        section_records.append({"member": logical, "matter": matter, "id": sections[0].get("id"), "heading_sha256": _sha(heading.encode())})
    if section_records != profile["sections"]:
        raise ValueError("source-derived section and heading inventory drifted")
    tei_bytes = etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)

    represented_count = sum(item["disposition"] == "represented" for item in all_observations)
    evidence_only_count = len(all_observations) - represented_count
    disposition_digest = _sha(_json([item["disposition"] for item in all_observations]))
    if {"total":len(all_observations), "represented":represented_count, "evidence_only":evidence_only_count, "ordered_dispositions_sha256":disposition_digest} != profile["observation_accounting"]:
        raise ValueError("retained body/evidence observation scope drifted")

    accountability = {
        "contract": "ocd-pilgrims-progress-source-accountability-v1",
        "schema": "pilgrims-progress.source-accountability.schema.json",
        "source_members": observed_set,
        "xml_member_count": 19,
        "non_xml_member_count": 7,
        "xml_observation_count": 31735,
        "element_count": 12091,
        "attribute_count": 9241,
        "text_count": 10403,
        "represented_count": represented_count,
        "evidence_only_count": evidence_only_count,
        "ordered_dispositions_sha256": disposition_digest,
        "omitted_count": 0,
        "duplicate_count": 0,
        "observations": all_observations,
        "non_xml_dispositions": non_xml,
        "sections": section_records,
        "feature_inventory": profile["feature_inventory"],
        "semantic_bindings": semantic_bindings,
    }
    provenance = {
        "contract": "ocd-pilgrims-progress-provenance-v1",
        "status": "nonaccepted",
        "retained_commit": expected["commit"],
        "retained_tree": expected["tree"],
        "source_member_set_sha256": source_set_sha,
        "spine": spine,
        "metadata_conflicts": profile["metadata_conflicts"],
        "rights": profile["rights"],
        "producer_import_closure_sha256": profile["producer_import_closure_sha256"],
        "metadata_claims": semantic_bindings["metadata_claims"],
    }
    unresolved = [
        {"id": "bunyan-edition-metadata-conflicts", "status": "unresolved", "detail": json.dumps(semantic_bindings["metadata_claims"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))},
        {"id": "bunyan-rights-jurisdiction", "status": "unresolved", "detail": "US public-domain belief and CC0 contributor dedication do not establish worldwide publication rights."},
        {"id": "bunyan-note-provenance", "status": "unresolved", "detail": "The consolidated endnotes contain multiple commentators; individual provenance remains source-reported, not independently adjudicated."},
        {"id": "bunyan-human-acceptance", "status": "unresolved", "detail": "Validation does not constitute human textual acceptance or publication readiness."},
    ]
    readme = _readme_text(rights_claims)
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _json(accountability),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
