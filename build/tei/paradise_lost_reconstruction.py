"""Direct retained Standard Ebooks Paradise Lost to nonaccepted TEI."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-paradise-lost-retained-se-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
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


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _el(
    name: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    node = etree.Element(f"{{{TEI}}}{name}")
    for key, value in (attrs or {}).items():
        node.set(XML_ID if key == "xml:id" else XML_LANG if key == "xml:lang" else key, value)
    node.text = text
    return node


def _attribute_name(expanded: str) -> str:
    qname = etree.QName(expanded)
    if qname.namespace == EPUB:
        return f"epub:{qname.localname}"
    if qname.namespace == XML:
        return f"xml:{qname.localname}"
    return qname.localname


def _tokens(node: etree._Element) -> tuple[str, ...]:
    return tuple(node.get(EPUB_TYPE, "").split())


def _norm(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _marker(logical: str, tree: etree._ElementTree, node: etree._Element) -> str:
    return "#pl-source-" + _sha((logical + "|" + tree.getpath(node)).encode())


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    value = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "Paradise Lost profile",
    )
    if value.get("contract") != "ocd-paradise-lost-reconstruction-profile-v1":
        raise ValueError("Paradise Lost reconstruction profile mismatch")
    return value


def _policy(source_manifest: SourceManifest) -> dict[str, object]:
    value = _strict_json(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "Paradise Lost policy",
    )
    if value.get("contract") != "ocd-paradise-lost-validation-policy-v1":
        raise ValueError("Paradise Lost validation policy mismatch")
    return value


def _source_members(source_manifest: SourceManifest) -> list[tuple[str, Path, bytes]]:
    prefix = "raw/standard_ebooks/john-milton_paradise-lost/"
    members: list[tuple[str, Path, bytes]] = []
    for authority in source_manifest.record["authorities"]:
        if authority.get("role") != "primary-source":
            continue
        logical_path = str(authority["path"])
        if not logical_path.startswith(prefix):
            raise ValueError("Paradise Lost source authority escaped the retained checkout")
        path = source_manifest.authority_path(str(authority["name"]))
        members.append((logical_path.removeprefix(prefix), path, path.read_bytes()))
    return sorted(members, key=lambda row: row[0].encode())


def _git_state(checkout: Path) -> dict[str, object]:
    safe = str(checkout.resolve(strict=True))

    def run(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-c", f"safe.directory={safe}", "-C", safe, *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout

    return {
        "commit": run("rev-parse", "HEAD").strip(),
        "tree": run("rev-parse", "HEAD^{tree}").strip(),
        "clean": run("status", "--porcelain=v1", "--untracked-files=all") == "",
        "tracked_members": sorted(item for item in run("ls-files").splitlines() if item),
    }


def _runtime_paths(repository_root: Path) -> None:
    expected_self = repository_root / "build/tei/paradise_lost_reconstruction.py"
    contract_module = sys.modules[SourceManifest.__module__]
    expected_contract = repository_root / "ocd_kernel/reconstruction/contract.py"
    if not Path(__file__).resolve(strict=True).samefile(expected_self):
        raise ValueError("Paradise Lost producer loaded outside the reviewed repository")
    module_path = getattr(contract_module, "__file__", None)
    if module_path is None or not Path(module_path).resolve(strict=True).samefile(expected_contract):
        raise ValueError("Paradise Lost producer loaded an editable/import-shadow contract")


def _local_imports(path: Path, repository_root: Path, seen: set[Path]) -> None:
    path = path.resolve(strict=True)
    if path in seen:
        return
    seen.add(path)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
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


def _closure(repository_root: Path) -> tuple[str, list[dict[str, object]]]:
    seen: set[Path] = set()
    _local_imports(Path(__file__), repository_root, seen)
    records = []
    for path in sorted(seen, key=lambda item: item.as_posix().encode()):
        content = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(repository_root).as_posix(),
                "bytes": len(content),
                "sha256": _sha(content),
            }
        )
    return _sha(_canonical({"contract": "ocd-python-import-closure-v1", "members": records})), records


def _nearest_section(node: etree._Element) -> str | None:
    sections = node.xpath("ancestor-or-self::*[local-name()='section'][@id][1]")
    return sections[0].get("id") if sections else None


def _observation_disposition(
    *,
    member: str,
    kind: str,
    name: str,
    value: str | None,
    section_id: str | None,
    top_section_id: str | None,
) -> tuple[str, str, str]:
    claimable = (
        (kind in {"text", "tail"} and value is not None and bool(value.strip()))
        or (kind == "element" and name in {"section", "h1", "h2", "h3", "h4", "h5", "h6", "a"})
        or (kind == "attribute" and name in {"id", "href"})
    )
    if claimable and section_id is not None:
        return (
            "represented",
            "stable-section-text-structure-or-link-correspondence",
            f"tei:#{section_id}",
        )
    if (
        kind == "attribute"
        and name == "xml:lang"
        and member.startswith("src/epub/text/")
        and top_section_id is not None
    ):
        return (
            "represented",
            "effective-section-language-correspondence",
            f"tei:#{top_section_id}@xml:lang",
        )
    target = f"exact-source-member:{member}"
    if member == "src/epub/toc.xhtml":
        return "evidence-only", "navigation-carrier-retained-exact", target
    if member == "src/epub/content.opf":
        return "evidence-only", "package-metadata-retained-exact", target
    if not member.endswith(".xhtml"):
        return "evidence-only", "support-or-nontext-member-retained-exact", target
    if kind in {"text", "tail"} and (value is None or not value.strip()):
        return "evidence-only", "formatting-whitespace-retained-exact", target
    return "evidence-only", "xhtml-carrier-semantics-retained-exact", target


def _observations(
    logical: str, content: bytes
) -> tuple[list[dict[str, object]], etree._ElementTree | None]:
    file_digest = _sha(content)
    disposition, reason, target = _observation_disposition(
        member=logical,
        kind="file",
        name=logical,
        value=file_digest,
        section_id=None,
        top_section_id=None,
    )
    records: list[dict[str, object]] = [
        {
            "source_address": f"file:{logical}",
            "source_member": logical,
            "source_kind": "file",
            "source_name": logical,
            "value": file_digest,
            "value_sha256": _sha(file_digest.encode()),
            "disposition": disposition,
            "reason": reason,
            "target": target,
        }
    ]
    if Path(logical).suffix.lower() not in XML_SUFFIXES:
        return records, None
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        recover=False,
        resolve_entities=False,
    )
    root_element = etree.fromstring(content, parser)
    tree = root_element.getroottree()
    top_sections = root_element.xpath(
        "//*[local-name()='body']/*[local-name()='section'][@id][1]"
    )
    top_section_id = top_sections[0].get("id") if top_sections else None
    paths: dict[etree._Element, str] = {}
    ordinals: dict[tuple[etree._Element, str], int] = {}
    prefix = f"file:{logical}#"

    def add(kind: str, name: str, value: str | None, node: etree._Element, address: str) -> None:
        section_id = _nearest_section(node)
        disposition, reason, target = _observation_disposition(
            member=logical,
            kind=kind,
            name=name,
            value=value,
            section_id=section_id,
            top_section_id=top_section_id,
        )
        records.append(
            {
                "source_address": address,
                "source_member": logical,
                "source_kind": kind,
                "source_name": name,
                "value": value,
                "value_sha256": _sha((value or "").encode()),
                "disposition": disposition,
                "reason": reason,
                "target": target,
            }
        )

    for node in root_element.iter():
        if not isinstance(node.tag, str):
            continue
        local = etree.QName(node).localname
        parent = node.getparent()
        if parent is None:
            element_path = f"/{local}[1]"
        else:
            key = (parent, local)
            ordinal = ordinals.get(key, 0) + 1
            ordinals[key] = ordinal
            element_path = f"{paths[parent]}/{local}[{ordinal}]"
        paths[node] = element_path
        add("element", local, None, node, prefix + element_path)
        for expanded, value in sorted(node.attrib.items()):
            name = _attribute_name(expanded)
            add("attribute", name, value, node, f"{prefix}{element_path}::attr:{name}")
        if node.text is not None:
            add("text", "#text", node.text, node, f"{prefix}{element_path}::text")
        if node.tail is not None:
            add("tail", "#tail", node.tail, node, f"{prefix}{element_path}::tail")
    return records, tree


def _semantic_attributes(node: etree._Element) -> dict[str, str]:
    return {_attribute_name(name): value for name, value in sorted(node.attrib.items())}


def _matter(body: etree._Element) -> str:
    matches = [
        token.removesuffix("matter")
        for token in _tokens(body)
        if token in {"frontmatter", "bodymatter", "backmatter"}
    ]
    if len(matches) != 1:
        raise ValueError("Paradise Lost spine body has ambiguous matter classification")
    return matches[0]


def _semantic_bindings(
    roots: Mapping[str, etree._ElementTree],
    spine: list[str],
    config: Mapping[str, object],
) -> dict[str, object]:
    ns = {"x": XHTML, "epub": EPUB, "opf": OPF, "dc": DC}
    spine_roots = [("src/epub/" + href, roots["src/epub/" + href]) for href in spine]
    sections: list[dict[str, object]] = []
    verse_groups: list[dict[str, object]] = []
    inline_occurrences: list[dict[str, object]] = []
    for order, (logical, tree) in enumerate(spine_roots, 1):
        body = tree.xpath("//x:body", namespaces=ns)[0]
        matter = _matter(body)
        language = tree.getroot().get(XML_LANG)
        for section in tree.xpath("//x:body//x:section[@id]", namespaces=ns):
            parent = section.getparent()
            headings = section.xpath(
                "./x:h1|./x:h2|./x:h3|./x:h4|./x:h5|./x:h6|"
                "./x:header/*[contains(concat(' ',@epub:type,' '),' title ')]|"
                "./x:header/x:h1|./x:header/x:h2|./x:header/x:h3|./x:header/x:h4|./x:header/x:h5|./x:header/x:h6",
                namespaces=ns,
            )
            sections.append(
                {
                    "member": logical,
                    "spine_order": order,
                    "matter": matter,
                    "id": section.get("id"),
                    "parent": parent.get("id") if etree.QName(parent).localname == "section" else None,
                    "language": language,
                    "path": tree.getpath(section),
                    "corresp": _marker(logical, tree, section),
                    "heading_sha256": [_sha(_norm(node).encode()) for node in headings],
                    "text_sha256": _sha(_norm(section).encode()),
                }
            )
        groups = tree.xpath(
            "//x:section[@epub:type='z3998:poem']|//x:blockquote[@epub:type='z3998:verse']",
            namespaces=ns,
        )
        for group in groups:
            stanzas = []
            for paragraph in group.xpath("./x:p", namespaces=ns):
                lines = []
                for line in paragraph.xpath("./x:span", namespaces=ns):
                    value = _norm(line)
                    lines.append(
                        {
                            "path": tree.getpath(line),
                            "corresp": _marker(logical, tree, line),
                            "value": value,
                            "value_sha256": _sha(value.encode()),
                        }
                    )
                stanzas.append(
                    {
                        "path": tree.getpath(paragraph),
                        "corresp": _marker(logical, tree, paragraph),
                        "lines": lines,
                    }
                )
            verse_groups.append(
                {
                    "member": logical,
                    "path": tree.getpath(group),
                    "corresp": _marker(logical, tree, group),
                    "genre": "poem" if etree.QName(group).localname == "section" else "verse",
                    "matter": matter,
                    "stanzas": stanzas,
                }
            )
        for node in tree.xpath(
            "//x:body//*[self::x:a or self::x:abbr or self::x:b or self::x:i or self::x:em or self::x:span or self::x:time or self::x:br or self::x:img]",
            namespaces=ns,
        ):
            carrier = etree.QName(node).localname
            in_verse = bool(
                node.xpath(
                    "ancestor::x:section[@epub:type='z3998:poem']|ancestor::x:blockquote[@epub:type='z3998:verse']",
                    namespaces=ns,
                )
            )
            verse_line = carrier == "span" and in_verse and etree.QName(node.getparent()).localname == "p"
            projected = not (carrier == "br" and in_verse)
            expected_tag = "l" if verse_line else {
                "a": "ref", "abbr": "abbr", "b": "hi", "i": "hi", "em": "emph",
                "span": "seg", "time": "date", "br": "lb", "img": "figure",
            }[carrier]
            inline_occurrences.append(
                {
                    "member": logical,
                    "path": tree.getpath(node),
                    "corresp": _marker(logical, tree, node),
                    "carrier": carrier,
                    "expected_tag": expected_tag,
                    "projected": projected,
                    "attributes": _semantic_attributes(node),
                    "value_sha256": _sha(_norm(node).encode()),
                }
            )
    toc_tree = roots["src/epub/toc.xhtml"]
    toc = []
    for order, link in enumerate(toc_tree.xpath("//x:nav//x:a", namespaces=ns), 1):
        nav = link.xpath("ancestor::x:nav[1]", namespaces=ns)[0]
        toc.append(
            {
                "order": order,
                "nav_type": nav.get(EPUB_TYPE),
                "depth": len(link.xpath("ancestor::x:li", namespaces=ns)),
                "path": toc_tree.getpath(link),
                "target": link.get("href"),
                "label": _norm(link),
                "link_type": link.get(EPUB_TYPE),
            }
        )
    image_strings = []
    for logical, tree in sorted(roots.items()):
        if not logical.endswith(".svg"):
            continue
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
            "creators": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:creator", namespaces=ns)],
            "contributors": [{"id": node.get("id"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:contributor", namespaces=ns)],
            "languages": [_norm(node) for node in opf.xpath("//opf:metadata/dc:language", namespaces=ns)],
            "dates": [{"kind": etree.QName(node).localname, "property": node.get("property"), "value": _norm(node)} for node in opf.xpath("//opf:metadata/dc:date|//opf:metadata/opf:meta[@property='dcterms:modified']", namespaces=ns)],
            "sources": [_norm(node) for node in opf.xpath("//opf:metadata/dc:source", namespaces=ns)],
            "identifiers": [_norm(node) for node in opf.xpath("//opf:metadata/dc:identifier", namespaces=ns)],
            "rights": [_norm(node) for node in opf.xpath("//opf:metadata/dc:rights", namespaces=ns)],
            "long_description": [_norm(node) for node in opf.xpath("//opf:metadata/opf:meta[@property='se:long-description']", namespaces=ns)],
        },
        "spine_languages": [{"member": logical, "language": tree.getroot().get(XML_LANG)} for logical, tree in spine_roots],
    }
    rights_nodes = opf.xpath("//opf:metadata/dc:rights", namespaces=ns)
    if len(rights_nodes) != 1:
        raise ValueError("Paradise Lost OPF must retain one exact rights statement")
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
        "verse_groups": verse_groups,
        "inline_occurrences": inline_occurrences,
        "toc": toc,
        "image_strings": image_strings,
        "metadata_claims": metadata,
        "rights_claims": rights,
    }


def _append_text(target: etree._Element, value: str | None) -> None:
    if value is None or value == "":
        return
    if not value.strip():
        value = " "
    if len(target):
        target[-1].tail = (target[-1].tail or "") + value
    else:
        target.text = (target.text or "") + value


def _ana(node: etree._Element) -> str | None:
    tokens = _tokens(node)
    return " ".join("epub:" + token for token in tokens) if tokens else None


def _common_attrs(node: etree._Element, logical: str, tree: etree._ElementTree) -> dict[str, str]:
    attrs = {"corresp": _marker(logical, tree, node)}
    if node.get("id"):
        attrs["xml:id"] = str(node.get("id"))
    if node.get(XML_LANG):
        attrs["xml:lang"] = str(node.get(XML_LANG))
    if _ana(node):
        attrs["ana"] = str(_ana(node))
    if node.get("class"):
        attrs["rend"] = str(node.get("class"))
    return attrs


def _inline(node: etree._Element, logical: str, tree: etree._ElementTree) -> etree._Element:
    tag = etree.QName(node).localname
    attrs = _common_attrs(node, logical, tree)
    if tag == "a":
        attrs["target"] = str(node.get("href", ""))
        out = _el("ref", attrs)
    elif tag == "abbr":
        out = _el("abbr", attrs)
    elif tag == "b":
        attrs["rend"] = "bold"
        out = _el("hi", attrs)
    elif tag == "i":
        attrs["rend"] = "italic"
        out = _el("hi", attrs)
    elif tag == "em":
        out = _el("emph", attrs)
    elif tag == "span":
        out = _el("seg", attrs)
    elif tag == "time":
        if node.get("datetime"):
            attrs["when"] = str(node.get("datetime"))
        out = _el("date", attrs)
    elif tag == "br":
        return _el("lb", attrs)
    elif tag == "img":
        out = _el("figure", attrs)
        out.append(_el("graphic", {"url": str(node.get("src", ""))}))
        out.append(_el("figDesc", text=str(node.get("alt", ""))))
        return out
    else:
        raise ValueError(f"unsupported Paradise Lost inline carrier {tag}")
    _append_text(out, node.text)
    for child in node:
        out.append(_inline(child, logical, tree))
        _append_text(out, child.tail)
    return out


def _paragraph(node: etree._Element, logical: str, tree: etree._ElementTree, *, heading: bool = False) -> etree._Element:
    out = _el("head" if heading else "p", _common_attrs(node, logical, tree))
    _append_text(out, node.text)
    for child in node:
        out.append(_inline(child, logical, tree))
        _append_text(out, child.tail)
    return out


def _verse_group(node: etree._Element, logical: str, tree: etree._ElementTree, genre: str) -> etree._Element:
    group = _el("lg", {**_common_attrs(node, logical, tree), "type": genre})
    for paragraph in node.findall(f"{{{XHTML}}}p"):
        stanza = _el("lg", {**_common_attrs(paragraph, logical, tree), "type": "stanza"})
        for span in paragraph.findall(f"{{{XHTML}}}span"):
            line = _el("l", _common_attrs(span, logical, tree))
            _append_text(line, span.text)
            for child in span:
                line.append(_inline(child, logical, tree))
                _append_text(line, child.tail)
            line.tail = " "
            stanza.append(line)
        group.append(stanza)
    return group


def _blockquote(node: etree._Element, logical: str, tree: etree._ElementTree) -> etree._Element:
    if "z3998:verse" in _tokens(node):
        out = _el("quote")
        out.append(_verse_group(node, logical, tree, "verse"))
        return out
    out = _el("quote", _common_attrs(node, logical, tree))
    for child in node:
        tag = etree.QName(child).localname
        if tag == "p":
            out.append(_paragraph(child, logical, tree))
        else:
            out.append(_inline(child, logical, tree))
        _append_text(out, child.tail)
    return out


def _section(node: etree._Element, logical: str, tree: etree._ElementTree, language: str) -> etree._Element:
    tokens = _tokens(node)
    section_id = str(node.get("id"))
    section_type = (
        "book" if section_id.startswith("book-") else
        "argument" if section_id.startswith("argument-") else
        "poem" if "z3998:poem" in tokens else
        next(iter(tokens), "section").split(":")[-1]
    )
    attrs = {**_common_attrs(node, logical, tree), "type": section_type}
    if node.getparent() is not None and etree.QName(node.getparent()).localname != "section":
        attrs["xml:lang"] = language
        attrs["source"] = logical
    out = _el("div", attrs)
    if "z3998:poem" in tokens:
        for paragraph in node.findall(f"{{{XHTML}}}p"):
            stanza = _el("lg", {**_common_attrs(paragraph, logical, tree), "type": "stanza"})
            for span in paragraph.findall(f"{{{XHTML}}}span"):
                line = _el("l", _common_attrs(span, logical, tree))
                _append_text(line, span.text)
                for child in span:
                    line.append(_inline(child, logical, tree))
                    _append_text(line, child.tail)
                line.tail = " "
                stanza.append(line)
            out.append(stanza)
        return out
    for child in node:
        tag = etree.QName(child).localname
        if tag == "header":
            for header_child in child:
                header_tag = etree.QName(header_child).localname
                is_heading = header_tag.startswith("h") or "title" in _tokens(header_child)
                if header_tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"}:
                    out.append(_paragraph(header_child, logical, tree, heading=is_heading))
                elif header_tag == "img":
                    out.append(_inline(header_child, logical, tree))
                else:
                    raise ValueError(f"unsupported Paradise Lost header carrier {header_tag}")
        elif tag == "section":
            out.append(_section(child, logical, tree, language))
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            out.append(_paragraph(child, logical, tree, heading=True))
        elif tag == "p":
            out.append(_paragraph(child, logical, tree))
        elif tag == "blockquote":
            out.append(_blockquote(child, logical, tree))
        elif tag == "img":
            out.append(_inline(child, logical, tree))
        else:
            raise ValueError(f"unsupported Paradise Lost section carrier {tag}")
        _append_text(out, child.tail)
    return out


def _availability(rights: Mapping[str, object]) -> str:
    return (
        "Retained OPF rights statement: "
        + str(rights["retained_opf_text"])
        + " Candidate status: nonaccepted. Reconstruction and validation do not establish worldwide publication clearance or human acceptance."
    )


def _readme(rights: Mapping[str, object]) -> bytes:
    return (
        "# Source and rights\n\n"
        "Status: nonaccepted.\n\n"
        "Retained OPF rights statement:\n\n"
        + str(rights["retained_opf_text"])
        + "\n\nThe underlying text and artwork are reported as believed public domain in the United States; other jurisdictions remain uncertain. Standard Ebooks contributor work is separately dedicated under CC0 1.0. Reconstruction and validation do not grant worldwide publication clearance or constitute human acceptance.\n\n"
        "Metadata review: config language en; OPF language en-GB; spine XHTML en-GB/en-US variation; empty config contributors versus four named OPF contributors; original 1667 publication versus the 2019 digital date; the OPF 1910 A. W. Verity basis claim; and the HathiTrust source witness all remain explicitly reviewable.\n"
    ).encode("utf-8")


def _tei_header(profile: Mapping[str, object], source_set_sha256: str, rights: Mapping[str, object]) -> etree._Element:
    metadata = profile["metadata"]
    assert isinstance(metadata, Mapping)
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", text=str(metadata["title"])))
    title_stmt.append(_el("author", text=str(metadata["author"])))
    file_desc.append(title_stmt)
    publication_stmt = _el("publicationStmt")
    publication_stmt.append(_el("publisher", text="Open Christian Data"))
    availability = _el("availability", {"status": "unknown"})
    availability.append(_el("p", text=_availability(rights)))
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("title", text=str(metadata["title"])))
    bibl.append(_el("author", text=str(metadata["author"])))
    bibl.append(_el("publisher", text="Standard Ebooks"))
    bibl.append(_el("ptr", {"target": str(metadata["source_url"])}))
    bibl.append(_el("idno", {"type": "sha256"}, source_set_sha256))
    note = _el("note", {"type": "edition-basis"}, str(metadata["print_basis_claim"]))
    bibl.append(note)
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    _runtime_paths(source_manifest.repository_root)
    profile = _profile(source_manifest)
    policy = _policy(source_manifest)
    members = _source_members(source_manifest)
    source_scope = profile["source_scope"]
    assert isinstance(source_scope, Mapping)
    observed_set = [
        {"path": logical, "bytes": len(content), "sha256": _sha(content)}
        for logical, _, content in members
    ]
    if observed_set != source_scope["members"] or len(members) != 33 or sum(len(content) for _, _, content in members) != 3747043:
        raise ValueError("retained Paradise Lost member census drifted")
    checkout = source_manifest.repository_root / "raw/standard_ebooks/john-milton_paradise-lost"
    expected_git = {
        "commit": source_scope["commit"],
        "tree": source_scope["tree"],
        "clean": True,
        "tracked_members": [row["path"] for row in observed_set],
    }
    if _git_state(checkout) != expected_git:
        raise ValueError("retained Paradise Lost checkout revision or member set drifted")

    roots: dict[str, etree._ElementTree] = {}
    observations: list[dict[str, object]] = []
    non_xml = []
    for logical, _, content in members:
        records, tree = _observations(logical, content)
        observations.extend(records)
        if tree is None:
            non_xml.append(
                {
                    "member": logical,
                    "bytes": len(content),
                    "sha256": _sha(content),
                    "disposition": profile["non_xml_dispositions"][logical],
                }
            )
        else:
            roots[logical] = tree
    if len(roots) != 25 or len(non_xml) != 8 or len(observations) != 55544:
        raise ValueError("complete Paradise Lost XML/non-XML accounting drifted")

    opf = roots["src/epub/content.opf"]
    ns = {"opf": OPF}
    hrefs = {node.get("id"): node.get("href") for node in opf.xpath("//opf:manifest/opf:item", namespaces=ns)}
    spine = [str(hrefs[node.get("idref")]) for node in opf.xpath("//opf:spine/opf:itemref", namespaces=ns)]
    if spine != profile["spine"]:
        raise ValueError("Paradise Lost OPF spine drifted")
    config = _strict_json(source_manifest.authority_path("local-source-config").read_bytes(), "Paradise Lost config")
    bindings = _semantic_bindings(roots, spine, config)

    feature_inventory = profile["feature_inventory"]
    assert isinstance(feature_inventory, Mapping)
    inline_counts = Counter(row["carrier"] for row in bindings["inline_occurrences"])
    derived_counts = {
        "sections": len(bindings["sections"]),
        "top_level_sections": sum(row["parent"] is None for row in bindings["sections"]),
        "books": sum(str(row["id"]).startswith("book-") for row in bindings["sections"]),
        "arguments": sum(str(row["id"]).startswith("argument-") for row in bindings["sections"]),
        "poem_groups": sum(row["genre"] == "poem" for row in bindings["verse_groups"]),
        "verse_groups": sum(row["genre"] == "verse" for row in bindings["verse_groups"]),
        "stanzas": sum(len(row["stanzas"]) for row in bindings["verse_groups"]),
        "verse_lines": sum(len(stanza["lines"]) for row in bindings["verse_groups"] for stanza in row["stanzas"]),
        "body_links": inline_counts["a"],
        "toc_links": sum(row["nav_type"] == "toc" for row in bindings["toc"]),
        "landmarks": sum(row["nav_type"] == "landmarks" for row in bindings["toc"]),
        "image_borne_strings": len(bindings["image_strings"]),
        "image_alternatives": sum(row["kind"] == "xhtml-alt" for row in bindings["image_strings"]),
    }
    for key, value in derived_counts.items():
        if feature_inventory[key] != value:
            raise ValueError(f"Paradise Lost source-derived {key} count drifted")
    if dict(inline_counts) != feature_inventory["inline_carriers"]:
        raise ValueError("Paradise Lost inline carrier census drifted")

    source_set_sha = _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": observed_set}))
    rights = bindings["rights_claims"]
    assert isinstance(rights, Mapping)
    tei = _el("TEI")
    tei.append(_tei_header(profile, source_set_sha, rights))
    text = _el("text")
    containers = {name: _el(name) for name in ("front", "body", "back")}
    for name in ("front", "body", "back"):
        text.append(containers[name])
    tei.append(text)
    for href in spine:
        logical = "src/epub/" + href
        tree = roots[logical]
        body = tree.find(f".//{{{XHTML}}}body")
        if body is None:
            raise ValueError(f"Paradise Lost spine member {logical} has no body")
        top_sections = body.findall(f"{{{XHTML}}}section")
        if len(top_sections) != 1:
            raise ValueError(f"Paradise Lost spine member {logical} must have one top section")
        language = str(tree.getroot().get(XML_LANG))
        containers[_matter(body)].append(_section(top_sections[0], logical, tree, language))
    tei_bytes = etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False)

    dispositions = [row["disposition"] for row in observations]
    observed_accounting = {
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
    if observed_accounting != profile["observation_accounting"]:
        raise ValueError("Paradise Lost represented/evidence accounting drifted")

    accountability = {
        "contract": "ocd-paradise-lost-source-accountability-v1",
        "schema": "paradise-lost.source-accountability.schema.json",
        "source_members": observed_set,
        "xml_member_count": 25,
        "non_xml_member_count": 8,
        "observation_count": 55544,
        "file_count": observed_accounting["files"],
        "element_count": observed_accounting["elements"],
        "attribute_count": observed_accounting["attributes"],
        "text_count": observed_accounting["texts"],
        "tail_count": observed_accounting["tails"],
        "represented_count": observed_accounting["represented"],
        "evidence_only_count": observed_accounting["evidence_only"],
        "ordered_dispositions_sha256": observed_accounting["ordered_dispositions_sha256"],
        "omitted_count": 0,
        "duplicate_count": 0,
        "observations": observations,
        "non_xml_dispositions": non_xml,
        "semantic_bindings": bindings,
    }
    producer_closure_sha, _ = _closure(source_manifest.repository_root)
    provenance = {
        "contract": "ocd-paradise-lost-provenance-v1",
        "status": "nonaccepted",
        "retained_commit": source_scope["commit"],
        "retained_tree": source_scope["tree"],
        "source_member_set_sha256": source_set_sha,
        "spine": spine,
        "metadata_conflicts": profile["metadata_conflicts"],
        "rights": profile["rights"],
        "producer_import_closure_sha256": producer_closure_sha,
        "metadata_claims": bindings["metadata_claims"],
    }
    unresolved = [
        {"id": "paradise-lost-edition-basis", "status": "unresolved", "detail": "The OPF reports a 1910 A. W. Verity basis; no independent print collation was performed."},
        {"id": "paradise-lost-metadata-conflicts", "status": "unresolved", "detail": json.dumps(bindings["metadata_claims"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))},
        {"id": "paradise-lost-rights-jurisdiction", "status": "unresolved", "detail": "US public-domain belief and contributor CC0 dedication do not establish worldwide publication rights."},
        {"id": "paradise-lost-human-acceptance", "status": "unresolved", "detail": "Validation does not constitute human textual acceptance or publication readiness."},
    ]
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(row) for row in unresolved),
        "README.source.md": _readme(rights),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
