"""Producer-independent retained-source oracle for the Paradise Lost candidate."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-paradise-lost-independent-source-to-tei-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
XML = "http://www.w3.org/XML/1998/namespace"
XML_LANG = f"{{{XML}}}lang"
EPUB_TYPE = f"{{{EPUB}}}type"
XML_SUFFIXES = frozenset({".opf", ".svg", ".xhtml", ".xml"})


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict(content: bytes, label: str, *, canonical: bool = False) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict) or (canonical and _canonical(value) != content):
        raise ValueError(f"{label} is not a canonical JSON object")
    return value


def _attribute_name(expanded: str) -> str:
    qname = etree.QName(expanded)
    if qname.namespace == EPUB:
        return "epub:" + qname.localname
    if qname.namespace == XML:
        return "xml:" + qname.localname
    return qname.localname


def _norm(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _types(node: etree._Element) -> tuple[str, ...]:
    return tuple(node.get(EPUB_TYPE, "").split())


def _runtime_paths(repository_root: Path) -> None:
    self_path = Path(__file__).resolve(strict=True)
    contract_module = sys.modules[SourceManifest.__module__]
    contract_path = getattr(contract_module, "__file__", None)
    expected_self = repository_root / "build/tei/paradise_lost_oracle.py"
    expected_contract = repository_root / "ocd_kernel/reconstruction/contract.py"
    if not self_path.samefile(expected_self):
        raise ValueError("Paradise Lost oracle loaded outside the reviewed repository")
    if contract_path is None or not Path(contract_path).resolve(strict=True).samefile(expected_contract):
        raise ValueError("Paradise Lost oracle loaded an editable/import-shadow contract")


def _members(source_manifest: SourceManifest) -> list[tuple[str, Path, bytes]]:
    prefix = "raw/standard_ebooks/john-milton_paradise-lost/"
    result = []
    for item in source_manifest.record["authorities"]:
        if item.get("role") != "primary-source":
            continue
        declared = str(item["path"])
        if not declared.startswith(prefix):
            raise ValueError("independent Paradise Lost source authority escaped checkout")
        path = source_manifest.authority_path(str(item["name"]))
        result.append((declared[len(prefix):], path, path.read_bytes()))
    result.sort(key=lambda row: row[0].encode())
    return result


def _git_evidence(checkout: Path) -> dict[str, object]:
    root = str(checkout.resolve(strict=True))

    def command(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", f"safe.directory={root}", "-C", root, *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    commit = command("rev-parse", "--verify", "HEAD").stdout.strip()
    tree = command("show", "-s", "--format=%T", "HEAD").stdout.strip()
    status = command("status", "--porcelain=v1", "--untracked-files=all").stdout
    tracked = command("ls-files", "-z").stdout.split("\0")
    return {
        "commit": commit,
        "tree": tree,
        "clean": status == "",
        "tracked_members": sorted(item for item in tracked if item),
    }


def _element_path(node: etree._Element) -> str:
    steps = []
    lineage = list(node.iterancestors())[::-1] + [node]
    for current in lineage:
        local = etree.QName(current).localname
        ordinal = 1
        sibling = current.getprevious()
        while sibling is not None:
            if isinstance(sibling.tag, str) and etree.QName(sibling).localname == local:
                ordinal += 1
            sibling = sibling.getprevious()
        steps.append(f"{local}[{ordinal}]")
    return "/" + "/".join(steps)


def _section_identity(node: etree._Element) -> str | None:
    current: etree._Element | None = node
    while current is not None:
        if etree.QName(current).localname == "section" and current.get("id"):
            return current.get("id")
        current = current.getparent()
    return None


def _scope(
    member: str,
    kind: str,
    name: str,
    value: str | None,
    section: str | None,
    top_section: str | None,
) -> tuple[str, str, str]:
    content_claim = kind in {"text", "tail"} and bool(value and value.strip())
    element_claim = kind == "element" and name in {"section", "h1", "h2", "h3", "h4", "h5", "h6", "a"}
    attribute_claim = kind == "attribute" and name in {"id", "href"}
    if section is not None and (content_claim or element_claim or attribute_claim):
        return "represented", "stable-section-text-structure-or-link-correspondence", f"tei:#{section}"
    if kind == "attribute" and name == "xml:lang" and member.startswith("src/epub/text/") and top_section:
        return "represented", "effective-section-language-correspondence", f"tei:#{top_section}@xml:lang"
    target = "exact-source-member:" + member
    if member == "src/epub/toc.xhtml":
        return "evidence-only", "navigation-carrier-retained-exact", target
    if member == "src/epub/content.opf":
        return "evidence-only", "package-metadata-retained-exact", target
    if not member.endswith(".xhtml"):
        return "evidence-only", "support-or-nontext-member-retained-exact", target
    if kind in {"text", "tail"} and not (value and value.strip()):
        return "evidence-only", "formatting-whitespace-retained-exact", target
    return "evidence-only", "xhtml-carrier-semantics-retained-exact", target


def _row(
    address: str,
    member: str,
    kind: str,
    name: str,
    value: str | None,
    section: str | None,
    top_section: str | None,
) -> dict[str, object]:
    disposition, reason, target = _scope(member, kind, name, value, section, top_section)
    return {
        "source_address": address,
        "source_member": member,
        "source_kind": kind,
        "source_name": name,
        "value": value,
        "value_sha256": _sha((value or "").encode()),
        "disposition": disposition,
        "reason": reason,
        "target": target,
    }


def _independent_observations(
    member: str, content: bytes
) -> tuple[list[dict[str, object]], etree._ElementTree | None]:
    digest = _sha(content)
    rows = [_row(f"file:{member}", member, "file", member, digest, None, None)]
    if Path(member).suffix.lower() not in XML_SUFFIXES:
        return rows, None
    parser = etree.XMLParser(load_dtd=False, no_network=True, recover=False, resolve_entities=False)
    document = etree.fromstring(content, parser).getroottree()
    top_candidates = document.xpath("//*[local-name()='body']/*[local-name()='section'][@id]")
    top_section = top_candidates[0].get("id") if top_candidates else None
    for node in document.getroot().iter():
        if not isinstance(node.tag, str):
            continue
        path = _element_path(node)
        section = _section_identity(node)
        local = etree.QName(node).localname
        rows.append(_row(f"file:{member}#{path}", member, "element", local, None, section, top_section))
        for expanded, value in sorted(node.attrib.items()):
            name = _attribute_name(expanded)
            rows.append(_row(f"file:{member}#{path}::attr:{name}", member, "attribute", name, value, section, top_section))
        if node.text is not None:
            rows.append(_row(f"file:{member}#{path}::text", member, "text", "#text", node.text, section, top_section))
        if node.tail is not None:
            rows.append(_row(f"file:{member}#{path}::tail", member, "tail", "#tail", node.tail, section, top_section))
    return rows, document


def _attrs(node: etree._Element) -> dict[str, str]:
    return {_attribute_name(name): value for name, value in sorted(node.attrib.items())}


def _matter(body: etree._Element) -> str:
    values = [token[:-6] for token in _types(body) if token in {"frontmatter", "bodymatter", "backmatter"}]
    if len(values) != 1:
        raise ValueError("independent Paradise Lost matter classification failed")
    return values[0]


def _marker(member: str, tree: etree._ElementTree, node: etree._Element) -> str:
    return "#pl-source-" + _sha((member + "|" + tree.getpath(node)).encode())


def _independent_bindings(
    roots: Mapping[str, etree._ElementTree],
    spine: list[str],
    config: Mapping[str, object],
) -> dict[str, object]:
    ns = {"x": XHTML, "epub": EPUB, "opf": OPF, "dc": DC}
    sections = []
    groups = []
    inline = []
    spine_documents = [("src/epub/" + href, roots["src/epub/" + href]) for href in spine]
    for spine_number, (member, tree) in enumerate(spine_documents, 1):
        body = tree.xpath("/*[local-name()='html']/*[local-name()='body']")[0]
        matter = _matter(body)
        language = tree.getroot().get(XML_LANG)
        for section in tree.xpath("//*[local-name()='body']//*[local-name()='section'][@id]"):
            parent = section.getparent()
            headings = section.xpath(
                "./x:h1|./x:h2|./x:h3|./x:h4|./x:h5|./x:h6|"
                "./x:header/*[contains(concat(' ',@epub:type,' '),' title ')]|"
                "./x:header/x:h1|./x:header/x:h2|./x:header/x:h3|./x:header/x:h4|./x:header/x:h5|./x:header/x:h6",
                namespaces=ns,
            )
            sections.append(
                {
                    "member": member,
                    "spine_order": spine_number,
                    "matter": matter,
                    "id": section.get("id"),
                    "parent": parent.get("id") if etree.QName(parent).localname == "section" else None,
                    "language": language,
                    "path": tree.getpath(section),
                    "corresp": _marker(member, tree, section),
                    "heading_sha256": [_sha(_norm(item).encode()) for item in headings],
                    "text_sha256": _sha(_norm(section).encode()),
                }
            )
        selected_groups = tree.xpath(
            "//x:section[@epub:type='z3998:poem']|//x:blockquote[@epub:type='z3998:verse']",
            namespaces=ns,
        )
        for group in selected_groups:
            stanzas = []
            for paragraph in group.xpath("./x:p", namespaces=ns):
                lines = []
                for line in paragraph.xpath("./x:span", namespaces=ns):
                    value = _norm(line)
                    lines.append(
                        {
                            "path": tree.getpath(line),
                            "corresp": _marker(member, tree, line),
                            "value": value,
                            "value_sha256": _sha(value.encode()),
                        }
                    )
                stanzas.append({"path": tree.getpath(paragraph), "corresp": _marker(member, tree, paragraph), "lines": lines})
            groups.append(
                {
                    "member": member,
                    "path": tree.getpath(group),
                    "corresp": _marker(member, tree, group),
                    "genre": "poem" if etree.QName(group).localname == "section" else "verse",
                    "matter": matter,
                    "stanzas": stanzas,
                }
            )
        selected_inline = tree.xpath(
            "//x:body//*[self::x:a or self::x:abbr or self::x:b or self::x:i or self::x:em or self::x:span or self::x:time or self::x:br or self::x:img]",
            namespaces=ns,
        )
        for node in selected_inline:
            carrier = etree.QName(node).localname
            verse_ancestors = node.xpath(
                "ancestor::x:section[@epub:type='z3998:poem']|ancestor::x:blockquote[@epub:type='z3998:verse']",
                namespaces=ns,
            )
            in_verse = bool(verse_ancestors)
            line_carrier = carrier == "span" and in_verse and etree.QName(node.getparent()).localname == "p"
            projected = not (carrier == "br" and in_verse)
            tag = "l" if line_carrier else {
                "a": "ref", "abbr": "abbr", "b": "hi", "i": "hi", "em": "emph",
                "span": "seg", "time": "date", "br": "lb", "img": "figure",
            }[carrier]
            inline.append(
                {
                    "member": member,
                    "path": tree.getpath(node),
                    "corresp": _marker(member, tree, node),
                    "carrier": carrier,
                    "expected_tag": tag,
                    "projected": projected,
                    "attributes": _attrs(node),
                    "value_sha256": _sha(_norm(node).encode()),
                }
            )
    toc_tree = roots["src/epub/toc.xhtml"]
    navigation = []
    for number, link in enumerate(toc_tree.xpath("//x:nav//x:a", namespaces=ns), 1):
        nav = link.xpath("ancestor::x:nav[1]", namespaces=ns)[0]
        navigation.append(
            {
                "order": number,
                "nav_type": nav.get(EPUB_TYPE),
                "depth": len(link.xpath("ancestor::x:li", namespaces=ns)),
                "path": toc_tree.getpath(link),
                "target": link.get("href"),
                "label": _norm(link),
                "link_type": link.get(EPUB_TYPE),
            }
        )
    image_strings = []
    for member in sorted(roots):
        tree = roots[member]
        if not member.endswith(".svg"):
            continue
        for node in tree.getroot().iter():
            path = tree.getpath(node)
            if node.text and node.text.strip():
                image_strings.append({"member": member, "path": path + "/text()", "kind": "svg-text", "value": node.text})
            if node.tail and node.tail.strip():
                image_strings.append({"member": member, "path": path + "/tail()", "kind": "svg-tail", "value": node.tail})
    for member, tree in spine_documents:
        for image in tree.xpath("//x:img[@alt]", namespaces=ns):
            image_strings.append({"member": member, "path": tree.getpath(image) + "/@alt", "kind": "xhtml-alt", "value": image.get("alt")})
    opf = roots["src/epub/content.opf"]
    metadata = {
        "config": {key: config.get(key) for key in ("title", "author", "contributors", "original_publication_year", "language", "original_language", "source_url", "source_edition")},
        "opf": {
            "titles": [{"id": item.get("id"), "value": _norm(item)} for item in opf.xpath("//opf:metadata/dc:title", namespaces=ns)],
            "creators": [{"id": item.get("id"), "value": _norm(item)} for item in opf.xpath("//opf:metadata/dc:creator", namespaces=ns)],
            "contributors": [{"id": item.get("id"), "value": _norm(item)} for item in opf.xpath("//opf:metadata/dc:contributor", namespaces=ns)],
            "languages": [_norm(item) for item in opf.xpath("//opf:metadata/dc:language", namespaces=ns)],
            "dates": [{"kind": etree.QName(item).localname, "property": item.get("property"), "value": _norm(item)} for item in opf.xpath("//opf:metadata/dc:date|//opf:metadata/opf:meta[@property='dcterms:modified']", namespaces=ns)],
            "sources": [_norm(item) for item in opf.xpath("//opf:metadata/dc:source", namespaces=ns)],
            "identifiers": [_norm(item) for item in opf.xpath("//opf:metadata/dc:identifier", namespaces=ns)],
            "rights": [_norm(item) for item in opf.xpath("//opf:metadata/dc:rights", namespaces=ns)],
            "long_description": [_norm(item) for item in opf.xpath("//opf:metadata/opf:meta[@property='se:long-description']", namespaces=ns)],
        },
        "spine_languages": [{"member": member, "language": tree.getroot().get(XML_LANG)} for member, tree in spine_documents],
    }
    rights_nodes = opf.xpath("//opf:metadata/dc:rights", namespaces=ns)
    if len(rights_nodes) != 1:
        raise ValueError("independent Paradise Lost OPF rights cardinality drifted")
    rights = {
        "candidate_status": "nonaccepted",
        "source_member": "src/epub/content.opf",
        "source_path": opf.getpath(rights_nodes[0]),
        "retained_opf_text": _norm(rights_nodes[0]),
        "underlying_scope": "believed-US-public-domain-worldwide-uncertain",
        "contributor_scope": "CC0-1.0-dedication",
        "worldwide_clearance": False,
    }
    return {
        "spine": spine,
        "sections": sections,
        "verse_groups": groups,
        "inline_occurrences": inline,
        "toc": navigation,
        "image_strings": image_strings,
        "metadata_claims": metadata,
        "rights_claims": rights,
    }


def _local_imports(path: Path, repository_root: Path, seen: set[Path]) -> None:
    resolved = path.resolve(strict=True)
    if resolved in seen:
        return
    seen.add(resolved)
    tree = ast.parse(resolved.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        imported = []
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported = [node.module]
        for name in imported:
            parts = name.split(".")
            module = repository_root.joinpath(*parts).with_suffix(".py")
            package = repository_root.joinpath(*parts, "__init__.py")
            target = module if module.is_file() else package if package.is_file() else None
            if target is None:
                continue
            for depth in range(1, len(parts)):
                initializer = repository_root.joinpath(*parts[:depth], "__init__.py")
                if initializer.is_file():
                    _local_imports(initializer, repository_root, seen)
            _local_imports(target, repository_root, seen)


def _closure(repository_root: Path, start: Path | None = None) -> tuple[str, list[dict[str, object]]]:
    seen: set[Path] = set()
    _local_imports(start or Path(__file__), repository_root, seen)
    records = []
    for path in sorted(seen, key=lambda item: item.as_posix().encode()):
        content = path.read_bytes()
        records.append({"path": path.relative_to(repository_root).as_posix(), "bytes": len(content), "sha256": _sha(content)})
    return _sha(_canonical({"contract": "ocd-python-import-closure-v1", "members": records})), records


def _expected_availability(rights: Mapping[str, object]) -> str:
    return (
        "Retained OPF rights statement: "
        + str(rights["retained_opf_text"])
        + " Candidate status: nonaccepted. Reconstruction and validation do not establish worldwide publication clearance or human acceptance."
    )


def _expected_readme(rights: Mapping[str, object]) -> bytes:
    return (
        "# Source and rights\n\n"
        "Status: nonaccepted.\n\n"
        "Retained OPF rights statement:\n\n"
        + str(rights["retained_opf_text"])
        + "\n\nThe underlying text and artwork are reported as believed public domain in the United States; other jurisdictions remain uncertain. Standard Ebooks contributor work is separately dedicated under CC0 1.0. Reconstruction and validation do not grant worldwide publication clearance or constitute human acceptance.\n\n"
        "Metadata review: config language en; OPF language en-GB; spine XHTML en-GB/en-US variation; empty config contributors versus four named OPF contributors; original 1667 publication versus the 2019 digital date; the OPF 1910 A. W. Verity basis claim; and the HathiTrust source witness all remain explicitly reviewable.\n"
    ).encode("utf-8")


def _tei_projection(node: etree._Element) -> dict[str, object]:
    return {
        "name": etree.QName(node).text,
        "attributes": dict(sorted(node.attrib.items())),
        "text": node.text or "",
        "tail": node.tail or "",
        "children": [_tei_projection(child) for child in node],
    }


def _expected_element(
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    node = etree.Element(f"{{{TEI}}}{name}")
    for key, value in (attributes or {}).items():
        expanded = (
            f"{{{XML}}}id"
            if key == "xml:id"
            else f"{{{XML}}}lang"
            if key == "xml:lang"
            else key
        )
        node.set(expanded, value)
    node.text = text
    return node


def _expected_append_text(target: etree._Element, value: str | None) -> None:
    if value is None or value == "":
        return
    normalized = " " if not value.strip() else value
    if len(target):
        target[-1].tail = (target[-1].tail or "") + normalized
    else:
        target.text = (target.text or "") + normalized


def _expected_source_attributes(
    node: etree._Element, member: str, tree: etree._ElementTree
) -> dict[str, str]:
    attributes = {"corresp": _marker(member, tree, node)}
    if node.get("id"):
        attributes["xml:id"] = str(node.get("id"))
    if node.get(XML_LANG):
        attributes["xml:lang"] = str(node.get(XML_LANG))
    source_types = _types(node)
    if source_types:
        attributes["ana"] = " ".join(f"epub:{item}" for item in source_types)
    if node.get("class"):
        attributes["rend"] = str(node.get("class"))
    return attributes


def _expected_inline(
    node: etree._Element, member: str, tree: etree._ElementTree
) -> etree._Element:
    carrier = etree.QName(node).localname
    attributes = _expected_source_attributes(node, member, tree)
    if carrier == "a":
        attributes["target"] = str(node.get("href", ""))
        result = _expected_element("ref", attributes)
    elif carrier == "abbr":
        result = _expected_element("abbr", attributes)
    elif carrier == "b":
        attributes["rend"] = "bold"
        result = _expected_element("hi", attributes)
    elif carrier == "i":
        attributes["rend"] = "italic"
        result = _expected_element("hi", attributes)
    elif carrier == "em":
        result = _expected_element("emph", attributes)
    elif carrier == "span":
        result = _expected_element("seg", attributes)
    elif carrier == "time":
        if node.get("datetime"):
            attributes["when"] = str(node.get("datetime"))
        result = _expected_element("date", attributes)
    elif carrier == "br":
        return _expected_element("lb", attributes)
    elif carrier == "img":
        result = _expected_element("figure", attributes)
        result.append(
            _expected_element("graphic", {"url": str(node.get("src", ""))})
        )
        result.append(_expected_element("figDesc", text=str(node.get("alt", ""))))
        return result
    else:
        raise ValueError(
            f"independent Paradise Lost expected projection found unsupported inline {carrier}"
        )
    _expected_append_text(result, node.text)
    for child in node:
        result.append(_expected_inline(child, member, tree))
        _expected_append_text(result, child.tail)
    return result


def _expected_paragraph(
    node: etree._Element,
    member: str,
    tree: etree._ElementTree,
    *,
    heading: bool = False,
) -> etree._Element:
    result = _expected_element(
        "head" if heading else "p",
        _expected_source_attributes(node, member, tree),
    )
    _expected_append_text(result, node.text)
    for child in node:
        result.append(_expected_inline(child, member, tree))
        _expected_append_text(result, child.tail)
    return result


def _expected_verse_group(
    node: etree._Element,
    member: str,
    tree: etree._ElementTree,
    genre: str,
) -> etree._Element:
    result = _expected_element(
        "lg",
        {**_expected_source_attributes(node, member, tree), "type": genre},
    )
    for paragraph in node.findall(f"{{{XHTML}}}p"):
        stanza = _expected_element(
            "lg",
            {
                **_expected_source_attributes(paragraph, member, tree),
                "type": "stanza",
            },
        )
        for span in paragraph.findall(f"{{{XHTML}}}span"):
            line = _expected_element(
                "l", _expected_source_attributes(span, member, tree)
            )
            _expected_append_text(line, span.text)
            for child in span:
                line.append(_expected_inline(child, member, tree))
                _expected_append_text(line, child.tail)
            line.tail = " "
            stanza.append(line)
        result.append(stanza)
    return result


def _expected_blockquote(
    node: etree._Element, member: str, tree: etree._ElementTree
) -> etree._Element:
    if "z3998:verse" in _types(node):
        result = _expected_element("quote")
        result.append(_expected_verse_group(node, member, tree, "verse"))
        return result
    result = _expected_element(
        "quote", _expected_source_attributes(node, member, tree)
    )
    for child in node:
        if etree.QName(child).localname == "p":
            result.append(_expected_paragraph(child, member, tree))
        else:
            result.append(_expected_inline(child, member, tree))
        _expected_append_text(result, child.tail)
    return result


def _expected_section(
    node: etree._Element,
    member: str,
    tree: etree._ElementTree,
    language: str,
) -> etree._Element:
    source_types = _types(node)
    section_id = str(node.get("id"))
    section_type = (
        "book"
        if section_id.startswith("book-")
        else "argument"
        if section_id.startswith("argument-")
        else "poem"
        if "z3998:poem" in source_types
        else next(iter(source_types), "section").split(":")[-1]
    )
    attributes = {
        **_expected_source_attributes(node, member, tree),
        "type": section_type,
    }
    if node.getparent() is not None and etree.QName(node.getparent()).localname != "section":
        attributes["xml:lang"] = language
        attributes["source"] = member
    result = _expected_element("div", attributes)
    if "z3998:poem" in source_types:
        for paragraph in node.findall(f"{{{XHTML}}}p"):
            stanza = _expected_element(
                "lg",
                {
                    **_expected_source_attributes(paragraph, member, tree),
                    "type": "stanza",
                },
            )
            for span in paragraph.findall(f"{{{XHTML}}}span"):
                line = _expected_element(
                    "l", _expected_source_attributes(span, member, tree)
                )
                _expected_append_text(line, span.text)
                for child in span:
                    line.append(_expected_inline(child, member, tree))
                    _expected_append_text(line, child.tail)
                line.tail = " "
                stanza.append(line)
            result.append(stanza)
        return result
    for child in node:
        carrier = etree.QName(child).localname
        if carrier == "header":
            for header_child in child:
                header_carrier = etree.QName(header_child).localname
                is_heading = header_carrier.startswith("h") or "title" in _types(
                    header_child
                )
                if header_carrier in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
                    result.append(
                        _expected_paragraph(
                            header_child,
                            member,
                            tree,
                            heading=is_heading,
                        )
                    )
                elif header_carrier == "img":
                    result.append(_expected_inline(header_child, member, tree))
                else:
                    raise ValueError(
                        "independent Paradise Lost expected projection found "
                        f"unsupported header carrier {header_carrier}"
                    )
        elif carrier == "section":
            result.append(_expected_section(child, member, tree, language))
        elif carrier in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            result.append(
                _expected_paragraph(child, member, tree, heading=True)
            )
        elif carrier == "p":
            result.append(_expected_paragraph(child, member, tree))
        elif carrier == "blockquote":
            result.append(_expected_blockquote(child, member, tree))
        elif carrier == "img":
            result.append(_expected_inline(child, member, tree))
        else:
            raise ValueError(
                "independent Paradise Lost expected projection found "
                f"unsupported section carrier {carrier}"
            )
        _expected_append_text(result, child.tail)
    return result


def _expected_tei_projection(
    profile: Mapping[str, object],
    source_set_sha256: str,
    rights: Mapping[str, object],
    roots: Mapping[str, etree._ElementTree],
    spine: list[str],
) -> dict[str, object]:
    metadata = profile["metadata"]
    header = _expected_element("teiHeader")
    file_desc = _expected_element("fileDesc")
    title_stmt = _expected_element("titleStmt")
    title_stmt.append(_expected_element("title", text=str(metadata["title"])))
    title_stmt.append(_expected_element("author", text=str(metadata["author"])))
    file_desc.append(title_stmt)
    publication = _expected_element("publicationStmt")
    publication.append(_expected_element("publisher", text="Open Christian Data"))
    availability = _expected_element("availability", {"status": "unknown"})
    availability.append(_expected_element("p", text=_expected_availability(rights)))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _expected_element("sourceDesc")
    bibl = _expected_element("bibl")
    bibl.append(_expected_element("title", text=str(metadata["title"])))
    bibl.append(_expected_element("author", text=str(metadata["author"])))
    bibl.append(_expected_element("publisher", text="Standard Ebooks"))
    bibl.append(_expected_element("ptr", {"target": str(metadata["source_url"])}))
    bibl.append(
        _expected_element("idno", {"type": "sha256"}, source_set_sha256)
    )
    bibl.append(
        _expected_element(
            "note",
            {"type": "edition-basis"},
            str(metadata["print_basis_claim"]),
        )
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)

    tei = _expected_element("TEI")
    tei.append(header)
    text = _expected_element("text")
    containers = {name: _expected_element(name) for name in ("front", "body", "back")}
    for name in ("front", "body", "back"):
        text.append(containers[name])
    tei.append(text)
    for href in spine:
        member = "src/epub/" + href
        tree = roots[member]
        body = tree.find(f".//{{{XHTML}}}body")
        if body is None:
            raise ValueError(
                f"independent Paradise Lost expected projection found no body in {member}"
            )
        top_sections = body.findall(f"{{{XHTML}}}section")
        if len(top_sections) != 1:
            raise ValueError(
                "independent Paradise Lost expected projection found invalid top-section count"
            )
        language = str(tree.getroot().get(XML_LANG))
        containers[_matter(body)].append(
            _expected_section(top_sections[0], member, tree, language)
        )
    return _tei_projection(tei)


def _source_sha256(source_manifest: SourceManifest) -> str:
    records = sorted(
        (
            {"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
            for item in source_manifest.record["authorities"]
            if item["role"] == "primary-source"
        ),
        key=lambda row: (str(row["path"]), str(row["name"])),
    )
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": records}))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    _runtime_paths(source_manifest.repository_root)
    source_logical = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if (
        candidate.manifest.get("status") != "nonaccepted"
        or candidate.manifest.get("source_id") != source_manifest.record["source_id"]
        or dict(candidate.manifest.get("source_manifest", {}))
        != {"path": source_logical, "sha256": source_manifest.sha256}
        or dict(candidate.manifest.get("converter", {}))
        != dict(source_manifest.record["converter"])
        or dict(candidate.manifest.get("package_schema", {}))
        != dict(source_manifest.record["package_schema"])
    ):
        raise ValueError("Paradise Lost candidate manifest authority drifted")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Paradise Lost profile")
    policy = _strict(policy_bytes, "Paradise Lost validation policy")
    members = _members(source_manifest)
    observed_set = [{"path": logical, "bytes": len(content), "sha256": _sha(content)} for logical, _, content in members]
    if observed_set != profile["source_scope"]["members"] or len(observed_set) != 33 or sum(row["bytes"] for row in observed_set) != 3747043:
        raise ValueError("independent Paradise Lost source member census drifted")
    expected_git = {
        "commit": profile["source_scope"]["commit"],
        "tree": profile["source_scope"]["tree"],
        "clean": True,
        "tracked_members": [row["path"] for row in observed_set],
    }
    checkout = source_manifest.repository_root / "raw/standard_ebooks/john-milton_paradise-lost"
    if _git_evidence(checkout) != expected_git:
        raise ValueError("independent Paradise Lost Git authority drifted")

    observations = []
    roots: dict[str, etree._ElementTree] = {}
    non_xml = []
    for logical, _, content in members:
        rows, tree = _independent_observations(logical, content)
        observations.extend(rows)
        if tree is None:
            non_xml.append({"member": logical, "bytes": len(content), "sha256": _sha(content), "disposition": profile["non_xml_dispositions"][logical]})
        else:
            roots[logical] = tree
    if len(roots) != 25 or len(non_xml) != 8 or len(observations) != 55544:
        raise ValueError("independent Paradise Lost complete observation accounting drifted")
    opf = roots["src/epub/content.opf"]
    ns = {"opf": OPF}
    manifest = {node.get("id"): node.get("href") for node in opf.xpath("//opf:manifest/opf:item", namespaces=ns)}
    spine = [str(manifest[node.get("idref")]) for node in opf.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    if spine != profile["spine"]:
        raise ValueError("independent Paradise Lost OPF spine drifted")
    config = _strict(source_manifest.authority_path("local-source-config").read_bytes(), "Paradise Lost config")
    bindings = _independent_bindings(roots, spine, config)

    lines = [
        {"member": group["member"], "path": line["path"], "value_sha256": line["value_sha256"], "value": line["value"]}
        for group in bindings["verse_groups"]
        for stanza in group["stanzas"]
        for line in stanza["lines"]
    ]
    inline_projection = [
        {"member": row["member"], "path": row["path"], "carrier": row["carrier"], "attrs": row["attributes"], "value_sha256": row["value_sha256"]}
        for row in bindings["inline_occurrences"]
    ]
    image_projection = [{"member": row["member"], "path": row["path"], "value": row["value"]} for row in bindings["image_strings"]]
    line_values = Counter(row["value"] for row in lines)
    inline_counts = Counter(row["carrier"] for row in bindings["inline_occurrences"])
    feature = profile["feature_inventory"]
    checks = {
        "sections": len(bindings["sections"]),
        "top_level_sections": sum(row["parent"] is None for row in bindings["sections"]),
        "books": sum(str(row["id"]).startswith("book-") for row in bindings["sections"]),
        "arguments": sum(str(row["id"]).startswith("argument-") for row in bindings["sections"]),
        "poem_groups": sum(row["genre"] == "poem" for row in bindings["verse_groups"]),
        "verse_groups": sum(row["genre"] == "verse" for row in bindings["verse_groups"]),
        "stanzas": sum(len(row["stanzas"]) for row in bindings["verse_groups"]),
        "verse_lines": len(lines),
        "body_links": inline_counts["a"],
        "toc_links": sum(row["nav_type"] == "toc" for row in bindings["toc"]),
        "landmarks": sum(row["nav_type"] == "landmarks" for row in bindings["toc"]),
        "image_borne_strings": len(bindings["image_strings"]),
        "image_alternatives": sum(row["kind"] == "xhtml-alt" for row in bindings["image_strings"]),
        "repeated_line_values": sum(count > 1 for count in line_values.values()),
        "repeated_line_occurrences": sum(count for count in line_values.values() if count > 1),
    }
    if any(feature[key] != value for key, value in checks.items()):
        raise ValueError("independent Paradise Lost semantic feature floor drifted")
    if dict(inline_counts) != feature["inline_carriers"]:
        raise ValueError("independent Paradise Lost inline carrier census drifted")
    if _sha(_canonical(lines)) != feature["line_occurrences_sha256"] or _sha(_canonical(inline_projection)) != feature["inline_occurrences_sha256"] or _sha(_canonical(bindings["toc"])) != feature["toc_occurrences_sha256"] or _sha(_canonical(image_projection)) != feature["image_strings_sha256"]:
        raise ValueError("independent Paradise Lost occurrence-location digest drifted")
    poem_breaks = sum(
        len(tree.xpath("//x:section[@epub:type='z3998:poem']//x:br", namespaces={"x": XHTML, "epub": EPUB}))
        for tree in roots.values()
    )
    uncopyright_breaks = len(roots["src/epub/text/uncopyright.xhtml"].xpath("//x:blockquote[@epub:type='z3998:verse']//x:br", namespaces={"x": XHTML, "epub": EPUB}))
    if poem_breaks != feature["poem_breaks"] or uncopyright_breaks != feature["uncopyright_breaks"]:
        raise ValueError("Paradise Lost retained break placement drifted")

    accountability = _strict(candidate.member_bytes("source-accountability.json"), "Paradise Lost accountability", canonical=True)
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "Paradise Lost accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=lambda error: list(error.path))
    if errors:
        raise ValueError(f"Paradise Lost accountability schema failed: {errors[0].message}")
    if accountability["source_members"] != observed_set or accountability["observations"] != observations or accountability["non_xml_dispositions"] != non_xml or accountability["semantic_bindings"] != bindings:
        raise ValueError("Paradise Lost candidate accountability differs from independent retained truth")
    dispositions = [row["disposition"] for row in observations]
    expected_accounting = {
        "total": len(observations),
        "represented": dispositions.count("represented"),
        "evidence_only": dispositions.count("evidence-only"),
        "files": sum(row["source_kind"] == "file" for row in observations),
        "elements": sum(row["source_kind"] == "element" for row in observations),
        "attributes": sum(row["source_kind"] == "attribute" for row in observations),
        "texts": sum(row["source_kind"] == "text" for row in observations),
        "tails": sum(row["source_kind"] == "tail" for row in observations),
        "ordered_dispositions_sha256": _sha(_canonical(dispositions)),
    }
    if expected_accounting != profile["observation_accounting"]:
        raise ValueError("Paradise Lost represented/evidence floor collapsed")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    tei = etree.fromstring(tei_bytes)
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(tei):
        raise ValueError(f"Paradise Lost TEI P5 XSD failure: {xsd.error_log.last_error}")
    source_set_sha = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": observed_set})
    )
    if _tei_projection(tei) != _expected_tei_projection(
        profile,
        source_set_sha,
        bindings["rights_claims"],
        roots,
        spine,
    ):
        raise ValueError("Paradise Lost complete TEI projection mutation")
    tns = {"t": TEI, "xml": XML}
    correlated = tei.xpath("//*[@corresp]")
    by_corresp = {node.get("corresp"): node for node in correlated}
    if len(by_corresp) != len(correlated):
        raise ValueError("Paradise Lost TEI has duplicate source occurrence attachments")
    candidate_sections = tei.xpath("//t:div[@xml:id]", namespaces=tns)
    if len(candidate_sections) != 40:
        raise ValueError("Paradise Lost TEI section count drifted")
    for expected, node in zip(bindings["sections"], candidate_sections, strict=True):
        identifier = node.get(f"{{{XML}}}id")
        parent = node.xpath("ancestor::t:div[@xml:id][1]/@xml:id", namespaces=tns)
        container = node.xpath("ancestor::*[self::t:front or self::t:body or self::t:back][1]", namespaces=tns)
        source = node.xpath("ancestor-or-self::t:div[@source][1]/@source", namespaces=tns)
        language = node.xpath("ancestor-or-self::*[@xml:lang][1]/@xml:lang", namespaces=tns)
        if identifier != expected["id"] or (parent[0] if parent else None) != expected["parent"] or len(container) != 1 or etree.QName(container[0]).localname != expected["matter"] or (source[0] if source else None) != expected["member"] or (language[0] if language else None) != expected["language"] or node.get("corresp") != expected["corresp"]:
            raise ValueError("Paradise Lost TEI section hierarchy/order/matter/language attachment drifted")
        source_node = roots[str(expected["member"])].xpath(str(expected["path"]))[0]
        candidate_copy = etree.fromstring(etree.tostring(node))
        for description in candidate_copy.xpath(".//t:figDesc", namespaces=tns):
            description.getparent().remove(description)
        if _sha(_norm(source_node).encode()) != _sha(_norm(candidate_copy).encode()):
            raise ValueError("Paradise Lost TEI section text omission, invention, reorder, or misattachment")
        heads = [_sha(_norm(item).encode()) for item in node.xpath("./t:head", namespaces=tns)]
        if heads != expected["heading_sha256"]:
            raise ValueError("Paradise Lost TEI heading attachment drifted")

    for group in bindings["verse_groups"]:
        node = by_corresp.get(group["corresp"])
        expected_tag = "div" if group["genre"] == "poem" else "lg"
        if node is None or etree.QName(node).localname != expected_tag or node.get("type") != group["genre"]:
            raise ValueError("Paradise Lost TEI verse group genre/location attachment drifted")
        stanzas = node.xpath("./t:lg[@type='stanza']", namespaces=tns)
        if len(stanzas) != len(group["stanzas"]):
            raise ValueError("Paradise Lost TEI stanza count/attachment drifted")
        for expected_stanza, stanza in zip(group["stanzas"], stanzas, strict=True):
            lines_in_stanza = stanza.xpath("./t:l", namespaces=tns)
            if stanza.get("corresp") != expected_stanza["corresp"] or [line.get("corresp") for line in lines_in_stanza] != [line["corresp"] for line in expected_stanza["lines"]] or [_sha(_norm(line).encode()) for line in lines_in_stanza] != [line["value_sha256"] for line in expected_stanza["lines"]]:
                raise ValueError("Paradise Lost TEI line/stanza occurrence identity drifted")
    if len(tei.xpath("//t:lg[@type='stanza']", namespaces=tns)) != 400 or len(tei.xpath("//t:l", namespaces=tns)) != 10568:
        raise ValueError("Paradise Lost TEI stanza/line floor drifted")

    projected = [row for row in bindings["inline_occurrences"] if row["projected"]]
    projected_markers = [row["corresp"] for row in projected]
    projected_set = set(projected_markers)
    if [node.get("corresp") for node in correlated if node.get("corresp") in projected_set] != projected_markers:
        raise ValueError("Paradise Lost TEI inline occurrence order drifted")
    for expected in projected:
        node = by_corresp.get(expected["corresp"])
        if node is None or etree.QName(node).localname != expected["expected_tag"]:
            raise ValueError("Paradise Lost TEI inline carrier type/location drifted")
        attributes = expected["attributes"]
        expected_ana = " ".join("epub:" + token for token in str(attributes.get("epub:type", "")).split()) or None
        if node.get("ana") != expected_ana:
            raise ValueError("Paradise Lost TEI EPUB semantic attachment drifted")
        if attributes.get("class") is not None and node.get("rend") != attributes["class"]:
            raise ValueError("Paradise Lost TEI exact class/rendition attachment drifted")
        if expected["carrier"] == "b" and node.get("rend") != "bold":
            raise ValueError("Paradise Lost TEI bold carrier drifted")
        if expected["carrier"] == "i" and node.get("rend") != "italic":
            raise ValueError("Paradise Lost TEI italic carrier drifted")
        if expected["carrier"] not in {"img", "br"} and _sha(_norm(node).encode()) != expected["value_sha256"]:
            raise ValueError("Paradise Lost TEI inline value occurrence drifted")
        if expected["carrier"] == "a" and node.get("target") != attributes.get("href"):
            raise ValueError("Paradise Lost TEI link target drifted")
        if expected["carrier"] == "time" and node.get("when") != attributes.get("datetime"):
            raise ValueError("Paradise Lost TEI date attachment drifted")
        if expected["carrier"] == "img":
            graphics = node.xpath("./t:graphic", namespaces=tns)
            descriptions = node.xpath("./t:figDesc", namespaces=tns)
            if len(graphics) != 1 or graphics[0].get("url") != attributes.get("src") or len(descriptions) != 1 or _norm(descriptions[0]) != attributes.get("alt"):
                raise ValueError("Paradise Lost TEI image URL/alternative drifted")
    if len(tei.xpath("//t:lb", namespaces=tns)) != 17 or len(tei.xpath("//t:ref", namespaces=tns)) != 14 or len(tei.xpath("//t:figure", namespaces=tns)) != 3 or len(tei.xpath("//t:abbr[@rend='eoc']", namespaces=tns)) != 1:
        raise ValueError("Paradise Lost TEI inline semantic floor drifted")

    metadata = profile["metadata"]
    if [_norm(node) for node in tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=tns)] != [metadata["title"]] or [_norm(node) for node in tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:author", namespaces=tns)] != [metadata["author"]]:
        raise ValueError("Paradise Lost TEI title/author drifted")
    rights = bindings["rights_claims"]
    availability = tei.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:availability", namespaces=tns)
    if len(availability) != 1 or availability[0].get("status") != "unknown" or _norm(availability[0]) != _expected_availability(rights):
        raise ValueError("Paradise Lost TEI rights categories are missing or conflated")
    if candidate.member_bytes("README.source.md") != _expected_readme(rights):
        raise ValueError("Paradise Lost README source/rights handoff drifted")
    unresolved = [_strict(line + b"\n", "Paradise Lost unresolved", canonical=True) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    if [row["id"] for row in unresolved] != policy["required_unresolved_ids"]:
        raise ValueError("Paradise Lost unresolved human-review boundaries drifted")

    oracle_closure_sha, oracle_members = _closure(source_manifest.repository_root)
    producer_path = source_manifest.repository_root / "build/tei/paradise_lost_reconstruction.py"
    producer_closure_sha, _ = _closure(source_manifest.repository_root, producer_path)
    forbidden = tuple(policy["forbidden_import_prefixes"])
    imported = [str(row["path"]).removesuffix(".py").replace("/", ".") for row in oracle_members]
    if any(name.startswith(forbidden) for name in imported):
        raise ValueError("Paradise Lost oracle closure reaches producer, incumbent, census, or campaign machinery")
    validator = source_manifest.record["validator"]
    if oracle_closure_sha != validator["import_closure_sha256"]:
        raise ValueError("Paradise Lost oracle recursive import closure drifted")
    expected_provenance = {
        "contract": "ocd-paradise-lost-provenance-v1",
        "status": "nonaccepted",
        "retained_commit": profile["source_scope"]["commit"],
        "retained_tree": profile["source_scope"]["tree"],
        "source_member_set_sha256": source_set_sha,
        "spine": spine,
        "metadata_conflicts": profile["metadata_conflicts"],
        "rights": profile["rights"],
        "producer_import_closure_sha256": producer_closure_sha,
        "metadata_claims": bindings["metadata_claims"],
    }
    provenance = _strict(candidate.member_bytes("provenance.json"), "Paradise Lost provenance", canonical=True)
    if provenance != expected_provenance:
        raise ValueError("Paradise Lost provenance, metadata conflicts, revision, or rights drifted")
    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("Paradise Lost candidate crossed the human acceptance boundary")

    implementation_sha = _sha(Path(__file__).read_bytes())
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha,
        "import_closure_sha256": oracle_closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": str(source_manifest.record["package_schema"]["sha256"]),
        "source_sha256": _source_sha256(source_manifest),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
