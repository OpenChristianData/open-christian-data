"""Direct retained Kempis Standard Ebooks witness to a nonaccepted TEI candidate."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
from typing import Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-imitation-of-christ-retained-se-to-tei"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
OPF = "http://www.idpf.org/2007/opf"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
EPUB_TYPE = f"{{{EPUB}}}type"
SOURCE_SLUG = "thomas-a-kempis_the-imitation-of-christ_william-benham"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _load_json(path: Path, contract: str, label: str) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get("contract") != contract:
        raise ValueError(f"{label} contract mismatch")
    return value


def _profile(manifest: SourceManifest) -> dict[str, object]:
    return _load_json(
        manifest.authority_path("reconstruction-profile"),
        "ocd-imitation-of-christ-reconstruction-profile-v1",
        "Kempis reconstruction profile",
    )


def _policy(manifest: SourceManifest) -> dict[str, object]:
    return _load_json(
        manifest.authority_path("validation-policy"),
        "ocd-imitation-of-christ-validation-policy-v1",
        "Kempis validation policy",
    )


def _primary_members(manifest: SourceManifest) -> list[tuple[str, Path, bytes]]:
    members: list[tuple[str, Path, bytes]] = []
    marker = f"{SOURCE_SLUG}/"
    for authority in manifest.record["authorities"]:
        if authority.get("role") != "primary-source":
            continue
        path = manifest.authority_path(str(authority["name"]))
        logical = str(authority["path"]).split(marker, 1)[1]
        members.append((logical, path, path.read_bytes()))
    return sorted(members, key=lambda row: row[0])


def _git(source_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={source_root.as_posix()}",
            "-C",
            str(source_root),
            *arguments,
        ],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _verify_checkout(
    source_root: Path,
    profile: Mapping[str, object],
    expected_members: list[str],
) -> None:
    scope = profile["source_scope"]
    assert isinstance(scope, dict)
    head = _git(source_root, "rev-parse", "--verify", "HEAD").decode().strip()
    tree = _git(source_root, "rev-parse", "--verify", "HEAD^{tree}").decode().strip()
    if head != scope["commit"] or tree != scope["tree"]:
        raise ValueError("retained Kempis commit or tree drifted")
    if _git(source_root, "status", "--porcelain=v1", "--untracked-files=all", "-z"):
        raise ValueError("retained Kempis checkout is not clean")
    tracked = _git(source_root, "ls-files", "-z").decode("utf-8").rstrip("\0")
    tracked_members = tracked.split("\0") if tracked else []
    if tracked_members != expected_members:
        raise ValueError("retained Kempis tracked-member set drifted")


def _assert_runtime_origins(repository_root: Path) -> dict[str, str]:
    expected_converter = (
        repository_root / "build/tei/imitation_of_christ_reconstruction.py"
    ).resolve(strict=True)
    actual_converter = Path(__file__).resolve(strict=True)
    contract_source = inspect.getsourcefile(SourceManifest)
    if contract_source is None:
        raise ValueError("loaded reconstruction contract has no source path")
    actual_contract = Path(contract_source).resolve(strict=True)
    expected_contract = (
        repository_root / "ocd_kernel/reconstruction/contract.py"
    ).resolve(strict=True)
    if not actual_converter.samefile(expected_converter):
        raise ValueError("runtime loaded an editable or site-package converter shadow")
    if not actual_contract.samefile(expected_contract):
        raise ValueError("runtime loaded an editable or site-package contract shadow")
    return {
        "converter": actual_converter.relative_to(repository_root).as_posix(),
        "contract": actual_contract.relative_to(repository_root).as_posix(),
    }


def _module_target(repository_root: Path, name: str) -> Path | None:
    stem = repository_root.joinpath(*name.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate.resolve(strict=True)
    return None


def _producer_closure(repository_root: Path) -> tuple[str, list[dict[str, object]]]:
    entry = Path(__file__).resolve(strict=True)
    relative_entry = entry.relative_to(repository_root)
    pending = [entry]
    for depth in range(1, len(relative_entry.parts)):
        initializer = repository_root.joinpath(
            *relative_entry.parts[:depth], "__init__.py"
        )
        if initializer.is_file():
            pending.append(initializer.resolve(strict=True))
    seen: set[Path] = set()
    while pending:
        path = pending.pop(0)
        if path in seen:
            continue
        path.relative_to(repository_root)
        seen.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                names = []
            for name in names:
                target = _module_target(repository_root, name)
                if target is None:
                    continue
                relative = target.relative_to(repository_root)
                for depth in range(1, len(relative.parts)):
                    initializer = repository_root.joinpath(
                        *relative.parts[:depth], "__init__.py"
                    )
                    if initializer.is_file():
                        pending.append(initializer.resolve(strict=True))
                pending.append(target)
    records = []
    for path in sorted(seen, key=lambda item: item.relative_to(repository_root).as_posix()):
        content = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(repository_root).as_posix(),
                "bytes": len(content),
                "sha256": _sha(content),
            }
        )
    return _sha(_canonical({"contract": "ocd-python-import-closure-v1", "members": records})), records


def _source_binding(logical: str, path: str) -> str:
    identity = _sha(f"{logical}|{path}".encode("utf-8"))
    return f"urn:ocd-source-observation:{identity}"


def _in_xhtml_body(element: etree._Element) -> bool:
    qname = etree.QName(element)
    if qname.namespace == XHTML and qname.localname == "body":
        return True
    return any(
        etree.QName(parent).namespace == XHTML
        and etree.QName(parent).localname == "body"
        for parent in element.iterancestors()
    )


def _observations(
    logical: str, tree: etree._ElementTree
) -> tuple[list[dict[str, object]], dict[etree._Element, str]]:
    records: list[dict[str, object]] = []
    bindings: dict[etree._Element, str] = {}
    for element in tree.iter():
        path = tree.getpath(element)
        binding = _source_binding(logical, path)
        bindings[element] = binding
        qname = etree.QName(element)
        base = {
            "member": logical,
            "path": path,
            "source_binding": binding,
            "disposition": "evidence-only",
        }
        records.append(
            {
                **base,
                "kind": "element",
                "name": qname.text,
                "value_sha256": _sha(qname.text.encode("utf-8")),
            }
        )
        for name, value in sorted(element.attrib.items()):
            records.append(
                {
                    **base,
                    "kind": "attribute",
                    "name": etree.QName(name).text,
                    "value_sha256": _sha(value.encode("utf-8")),
                }
            )
        if element.text and element.text.strip():
            records.append(
                {
                    **base,
                    "kind": "text",
                    "path": f"{path}/text()",
                    "name": "text",
                    "value_sha256": _sha(element.text.encode("utf-8")),
                }
            )
        if element.tail and element.tail.strip():
            records.append(
                {
                    **base,
                    "kind": "text",
                    "path": f"{path}/following-sibling-text()",
                    "name": "tail",
                    "value_sha256": _sha(element.tail.encode("utf-8")),
                }
            )
    for number, record in enumerate(records, 1):
        record["observation_id"] = f"{logical}#{number:05d}"
    return records, bindings


def _types(node: etree._Element) -> list[str]:
    return node.get(EPUB_TYPE, "").split()


def _normalize(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _nearest_section_id(node: etree._Element) -> str | None:
    if etree.QName(node).localname == "section":
        return node.get("id")
    parent = next(
        (
            item
            for item in node.iterancestors()
            if etree.QName(item).namespace == XHTML
            and etree.QName(item).localname == "section"
        ),
        None,
    )
    return parent.get("id") if parent is not None else None


def _semantic_bindings(
    roots: Mapping[str, etree._ElementTree],
    spine: list[str],
    bindings: Mapping[str, Mapping[etree._Element, str]],
) -> dict[str, object]:
    ns = {
        "x": XHTML,
        "epub": EPUB,
        "xml": "http://www.w3.org/XML/1998/namespace",
    }
    sections: list[dict[str, object]] = []
    headings: list[dict[str, object]] = []
    hgroups: list[dict[str, object]] = []
    bridgeheads: list[dict[str, object]] = []
    paragraphs: list[dict[str, object]] = []
    notes: list[dict[str, object]] = []
    lists: list[dict[str, object]] = []
    verse: list[dict[str, object]] = []
    inline: list[dict[str, object]] = []
    languages: list[dict[str, object]] = []
    images: list[dict[str, object]] = []
    matter_counts = {"front": 0, "body": 0, "back": 0}
    for href in spine:
        logical = f"src/epub/{href}"
        tree = roots[logical]
        body = tree.find(f".//{{{XHTML}}}body")
        if body is None:
            raise ValueError(f"spine member {logical} has no XHTML body")
        matter = next(
            (
                token.removesuffix("matter")
                for token in _types(body)
                if token in {"frontmatter", "bodymatter", "backmatter"}
            ),
            None,
        )
        if matter not in matter_counts:
            raise ValueError(f"spine member {logical} has no matter classification")
        matter_counts[matter] += 1
        for section in body.xpath(".//x:section", namespaces=ns):
            parent_section = next(
                (
                    ancestor
                    for ancestor in section.iterancestors()
                    if etree.QName(ancestor).localname == "section"
                ),
                None,
            )
            sections.append(
                {
                    "member": logical,
                    "binding": bindings[logical][section],
                    "id": section.get("id"),
                    "parent_id": parent_section.get("id") if parent_section is not None else None,
                    "matter": matter,
                    "types": _types(section),
                    "text_sha256": _sha(_normalize(section).encode("utf-8")),
                }
            )
        for heading in body.xpath(".//x:h1|.//x:h2|.//x:h3|.//x:h4|.//x:h5|.//x:h6", namespaces=ns):
            headings.append(
                {
                    "member": logical,
                    "binding": bindings[logical][heading],
                    "tag": etree.QName(heading).localname,
                    "section_id": _nearest_section_id(heading),
                    "in_hgroup": any(etree.QName(a).localname == "hgroup" for a in heading.iterancestors()),
                    "text_sha256": _sha(_normalize(heading).encode("utf-8")),
                }
            )
        for hgroup in body.xpath(".//x:hgroup", namespaces=ns):
            hgroups.append(
                {
                    "member": logical,
                    "binding": bindings[logical][hgroup],
                    "section_id": _nearest_section_id(hgroup),
                    "child_tags": [etree.QName(child).localname for child in hgroup],
                    "text_sha256": _sha(_normalize(hgroup).encode("utf-8")),
                }
            )
        for paragraph in body.xpath(".//x:p", namespaces=ns):
            record = {
                "member": logical,
                "binding": bindings[logical][paragraph],
                "section_id": _nearest_section_id(paragraph),
                "class": paragraph.get("class"),
                "types": _types(paragraph),
                "text_sha256": _sha(_normalize(paragraph).encode("utf-8")),
            }
            paragraphs.append(record)
            if "bridgehead" in _types(paragraph):
                bridgeheads.append(record)
        for anchor in body.xpath(".//x:a", namespaces=ns):
            anchor_types = _types(anchor)
            if "noteref" in anchor_types:
                paragraph = next(
                    (
                        ancestor
                        for ancestor in anchor.iterancestors()
                        if etree.QName(ancestor).localname == "p"
                    ),
                    None,
                )
                notes.append(
                    {
                        "member": logical,
                        "binding": bindings[logical][anchor],
                        "id": anchor.get("id"),
                        "target": anchor.get("href"),
                        "label": _normalize(anchor),
                        "paragraph_binding": bindings[logical].get(paragraph),
                    }
                )
        for list_node in body.xpath(".//x:ol|.//x:ul", namespaces=ns):
            lists.append(
                {
                    "member": logical,
                    "binding": bindings[logical][list_node],
                    "tag": etree.QName(list_node).localname,
                    "section_id": _nearest_section_id(list_node),
                    "item_bindings": [bindings[logical][item] for item in list_node.xpath("./x:li", namespaces=ns)],
                    "item_text_sha256": [
                        _sha(_normalize(item).encode("utf-8"))
                        for item in list_node.xpath("./x:li", namespaces=ns)
                    ],
                }
            )
        for group in body.xpath(".//x:blockquote[@epub:type]", namespaces=ns):
            if "z3998:verse" not in _types(group):
                continue
            line_values: list[str] = []
            for paragraph in group.xpath("./x:p", namespaces=ns):
                serialized = etree.tostring(paragraph, encoding="unicode", with_tail=False)
                wrapper = etree.fromstring(serialized.encode("utf-8"))
                parts: list[str] = []
                current = wrapper.text or ""
                for child in wrapper:
                    if etree.QName(child).localname == "br":
                        parts.append(current)
                        current = child.tail or ""
                    else:
                        current += "".join(child.itertext()) + (child.tail or "")
                parts.append(current)
                line_values.extend(" ".join(part.split()) for part in parts)
            verse.append(
                {
                    "member": logical,
                    "binding": bindings[logical][group],
                    "section_id": _nearest_section_id(group),
                    "line_text_sha256": [
                        _sha(value.encode("utf-8")) for value in line_values
                    ],
                }
            )
        for tag in ("a", "abbr", "b", "strong", "i", "em", "span", "time", "br", "img"):
            for node in body.xpath(f".//x:{tag}", namespaces=ns):
                inline.append(
                    {
                        "member": logical,
                        "binding": bindings[logical][node],
                        "tag": tag,
                        "section_id": _nearest_section_id(node),
                        "attributes": sorted(
                            (etree.QName(name).text, value)
                            for name, value in node.attrib.items()
                        ),
                        "text_sha256": _sha(_normalize(node).encode("utf-8")),
                    }
                )
                if tag == "img":
                    images.append(
                        {
                            "member": logical,
                            "binding": bindings[logical][node],
                            "src": node.get("src"),
                            "alt": node.get("alt"),
                        }
                    )
        for node in body.xpath(".//*[@xml:lang] | self::*[@xml:lang]", namespaces=ns):
            languages.append(
                {
                    "member": logical,
                    "binding": bindings[logical][node],
                    "tag": etree.QName(node).localname,
                    "language": node.get(XML_LANG),
                    "section_id": _nearest_section_id(node),
                }
            )
        html = tree.getroot()
        if html.get(XML_LANG):
            languages.insert(
                len(languages),
                {
                    "member": logical,
                    "binding": bindings[logical][html],
                    "tag": "html",
                    "language": html.get(XML_LANG),
                    "section_id": None,
                },
            )

    endnotes = roots["src/epub/text/endnotes.xhtml"]
    for note, record in zip(
        endnotes.xpath("//x:li[@epub:type='endnote']", namespaces=ns),
        notes,
        strict=True,
    ):
        backlink = note.xpath(".//x:a[@epub:type='backlink']", namespaces=ns)
        if len(backlink) != 1:
            raise ValueError("retained endnote backlink cardinality drifted")
        record.update(
            {
                "note_binding": bindings["src/epub/text/endnotes.xhtml"][note],
                "note_id": note.get("id"),
                "note_text_sha256": _sha(_normalize(note).encode("utf-8")),
                "backlink_binding": bindings["src/epub/text/endnotes.xhtml"][backlink[0]],
                "backlink_target": backlink[0].get("href"),
                "backlink_label": _normalize(backlink[0]),
            }
        )

    toc_tree = roots["src/epub/toc.xhtml"]
    toc = []
    for anchor in toc_tree.xpath("//x:nav[@epub:type='toc']//x:a", namespaces=ns):
        ancestor_items = anchor.xpath("ancestor::x:li", namespaces=ns)
        parent_anchor = None
        if len(ancestor_items) > 1:
            candidates = ancestor_items[-2].xpath("./x:a", namespaces=ns)
            parent_anchor = candidates[0] if candidates else None
        toc.append(
            {
                "binding": bindings["src/epub/toc.xhtml"][anchor],
                "href": anchor.get("href"),
                "label": _normalize(anchor),
                "parent_href": parent_anchor.get("href") if parent_anchor is not None else None,
            }
        )
    landmarks = [
        {
            "binding": bindings["src/epub/toc.xhtml"][anchor],
            "href": anchor.get("href"),
            "label": _normalize(anchor),
            "types": _types(anchor),
        }
        for anchor in toc_tree.xpath("//x:nav[@epub:type='landmarks']//x:a", namespaces=ns)
    ]
    return {
        "matter_counts": matter_counts,
        "sections": sections,
        "headings": headings,
        "hgroups": hgroups,
        "bridgeheads": bridgeheads,
        "paragraphs": paragraphs,
        "notes": notes,
        "lists": lists,
        "verse": verse,
        "inline": inline,
        "languages": languages,
        "images": images,
        "toc": toc,
        "landmarks": landmarks,
    }


def _element(
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    node = etree.Element(f"{{{TEI}}}{name}")
    for key, value in (attributes or {}).items():
        node.set(XML_ID if key == "xml:id" else XML_LANG if key == "xml:lang" else key, value)
    node.text = text
    return node


def _append_text(target: etree._Element, value: str | None) -> None:
    if not value:
        return
    if len(target):
        target[-1].tail = (target[-1].tail or "") + value
    else:
        target.text = (target.text or "") + value


def _base_attributes(node: etree._Element, binding: str) -> dict[str, str]:
    attributes = {"corresp": binding}
    if node.get("id"):
        attributes["xml:id"] = str(node.get("id"))
    if node.get(XML_LANG):
        attributes["xml:lang"] = str(node.get(XML_LANG))
    if node.get("class"):
        attributes["rend"] = str(node.get("class"))
    return attributes


def _inline(
    node: etree._Element,
    bindings: Mapping[etree._Element, str],
) -> etree._Element:
    tag = etree.QName(node).localname
    attributes = _base_attributes(node, bindings[node])
    if tag == "a":
        href = node.get("href", "")
        if "noteref" in _types(node):
            attributes.update({"type": "note", "subtype": "source-a", "target": f"#{href.rsplit('#', 1)[-1]}"})
        elif "backlink" in _types(node):
            attributes.update({"type": "backlink", "subtype": "source-a", "target": f"#{href.rsplit('#', 1)[-1]}"})
        else:
            attributes.update({"type": "external", "subtype": "source-a", "target": href})
        output = _element("ref", attributes)
    elif tag == "abbr":
        output = _element("abbr", {**attributes, "type": "source-abbr"})
    elif tag in {"b", "strong"}:
        output = _element("hi", {**attributes, "rend": f"source-{tag} bold" if not node.get("class") else f"source-{tag} bold {node.get('class')}"})
    elif tag == "i":
        output = _element("hi", {**attributes, "rend": "source-i italic" if not node.get("class") else f"source-i italic {node.get('class')}"})
    elif tag == "em":
        output = _element("hi", {**attributes, "rend": "source-em emphasis" if not node.get("class") else f"source-em emphasis {node.get('class')}"})
    elif tag == "span":
        output = _element("seg", {**attributes, "type": "source-span"})
    elif tag == "time":
        if node.get("datetime"):
            attributes["when"] = str(node.get("datetime"))
        output = _element("date", {**attributes, "type": "source-time"})
    elif tag == "br":
        return _element("lb", {**attributes, "type": "source-br"})
    elif tag == "img":
        figure = _element("figure", {**attributes, "type": "source-img"})
        figure.append(_element("graphic", {"url": str(node.get("src", ""))}))
        figure.append(_element("figDesc", text=str(node.get("alt", ""))))
        return figure
    else:
        output = _element("seg", {**attributes, "type": f"source-{tag}"})
    output.text = node.text
    for child in node:
        output.append(_inline(child, bindings))
        _append_text(output, child.tail)
    return output


def _verse_lines(
    paragraph: etree._Element,
    bindings: Mapping[etree._Element, str],
) -> list[etree._Element]:
    lines = [_element("l", {"n": "1"})]
    _append_text(lines[-1], paragraph.text)
    for child in paragraph:
        if etree.QName(child).localname == "br":
            lines[-1].append(_inline(child, bindings))
            lines.append(
                _element(
                    "l",
                    {"n": str(len(lines) + 1)},
                )
            )
        else:
            lines[-1].append(_inline(child, bindings))
        _append_text(lines[-1], child.tail)
    return lines


def _block(
    node: etree._Element,
    bindings: Mapping[etree._Element, str],
) -> etree._Element:
    tag = etree.QName(node).localname
    attributes = _base_attributes(node, bindings[node])
    types = _types(node)
    if tag == "section":
        attributes["type"] = types[0].split(":")[-1] if types else "section"
        output = _element("div", attributes)
    elif tag == "hgroup":
        output = _element("head", {**attributes, "type": "hgroup"})
        for child in node:
            child_tag = etree.QName(child).localname
            child_attributes = _base_attributes(child, bindings[child])
            if child_tag == "p" and "bridgehead" in _types(child):
                child_attributes["rend"] = f"source-bridgehead {child_attributes.get('rend', '')}".strip()
            converted = _element("seg", {**child_attributes, "type": f"source-{child_tag}"})
            converted.text = child.text
            for grandchild in child:
                converted.append(_inline(grandchild, bindings))
                _append_text(converted, grandchild.tail)
            output.append(converted)
            _append_text(output, child.tail)
        return output
    elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        output = _element("head", {**attributes, "type": f"source-{tag}"})
    elif tag == "p":
        if "bridgehead" in types:
            attributes["rend"] = f"source-bridgehead {attributes.get('rend', '')}".strip()
        output = _element("p", attributes)
    elif tag == "blockquote" and "z3998:verse" in types:
        output = _element("lg", {**attributes, "type": "verse"})
        verse_paragraphs = [
            paragraph for paragraph in node if etree.QName(paragraph).localname == "p"
        ]
        if len(verse_paragraphs) != 1:
            raise ValueError("verse source must have exactly one paragraph carrier")
        output.set("corresp", f"{output.get('corresp')} {bindings[verse_paragraphs[0]]}")
        for paragraph in node:
            if etree.QName(paragraph).localname == "p":
                for line in _verse_lines(paragraph, bindings):
                    output.append(line)
        return output
    elif tag == "blockquote":
        output = _element("quote", attributes)
    elif tag in {"ol", "ul"}:
        output = _element("list", {**attributes, "type": "ordered" if tag == "ol" else "unordered"})
    elif tag == "li":
        output = _element("item", attributes)
    elif tag == "img":
        return _inline(node, bindings)
    else:
        return _inline(node, bindings)
    output.text = node.text
    block_tags = {
        "section", "header", "footer", "hgroup", "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "blockquote", "ol", "ul", "li", "img",
    }
    for child in node:
        child_tag = etree.QName(child).localname
        if child_tag in {"header", "footer"}:
            converted_children = [
                _block(grandchild, bindings)
                if etree.QName(grandchild).localname in block_tags
                else _inline(grandchild, bindings)
                for grandchild in child
            ]
            if not converted_children:
                raise ValueError(f"empty source {child_tag} cannot carry its observation binding")
            converted_children[0].set(
                "corresp",
                f"{bindings[child]} {converted_children[0].get('corresp', '')}".strip(),
            )
            for source_child, converted in zip(child, converted_children, strict=True):
                output.append(converted)
                _append_text(output, source_child.tail)
            _append_text(output, child.tail)
            continue
        converted = _block(child, bindings) if child_tag in block_tags else _inline(child, bindings)
        output.append(converted)
        _append_text(output, child.tail)
    return output


def _tei_header(
    profile: Mapping[str, object],
    source_member_set_sha256: str,
) -> etree._Element:
    metadata = profile["metadata"]
    assert isinstance(metadata, dict)
    header = _element("teiHeader")
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(_element("title", text=str(metadata["title"])))
    title_stmt.append(_element("author", text=str(metadata["popular_attribution"])))
    for role, person in metadata["principal_responsibilities"]:
        statement = _element("respStmt")
        statement.append(_element("resp", text=str(role)))
        statement.append(_element("name", text=str(person)))
        title_stmt.append(statement)
    file_desc.append(title_stmt)
    publication = _element("publicationStmt")
    publication.append(_element("publisher", text="Open Christian Data"))
    availability = _element("availability", {"status": "unknown"})
    availability.append(
        _element(
            "p",
            text=(
                "The underlying source text and artwork are believed to be in the United States public domain; "
                "other jurisdictions require review. Standard Ebooks contributor work is dedicated under CC0 1.0. "
                "This nonaccepted candidate is not publication authorization."
            ),
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    notes_stmt = _element("notesStmt")
    for conflict in profile["metadata_conflicts"]:
        notes_stmt.append(_element("note", {"type": "unresolved"}, str(conflict)))
    file_desc.append(notes_stmt)
    source_desc = _element("sourceDesc")
    bibliography = _element("bibl")
    bibliography.append(_element("title", text=str(metadata["title"])))
    bibliography.append(_element("author", text=str(metadata["popular_attribution"])))
    responsibility = _element("respStmt")
    responsibility.append(_element("resp", text="translator, annotator, and writer of preface"))
    responsibility.append(_element("name", text="William Benham"))
    bibliography.append(responsibility)
    annotation = _element("respStmt")
    annotation.append(_element("resp", text="annotator"))
    annotation.append(_element("name", text="H. C. Beeching"))
    bibliography.append(annotation)
    bibliography.append(_element("publisher", text="Standard Ebooks"))
    for link in metadata["source_links"]:
        bibliography.append(_element("ptr", {"target": str(link)}))
    bibliography.append(_element("idno", {"type": "sha256"}, source_member_set_sha256))
    source_desc.append(bibliography)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _svg_strings(roots: Mapping[str, etree._ElementTree]) -> list[dict[str, object]]:
    result = []
    for logical in sorted(name for name in roots if name.endswith(".svg")):
        tree = roots[logical]
        for node in tree.iter():
            tag = etree.QName(node).localname
            if tag not in {"title", "desc", "text"} or not node.text or not node.text.strip():
                continue
            result.append(
                {
                    "member": logical,
                    "path": tree.getpath(node),
                    "kind": tag,
                    "text": node.text.strip(),
                    "text_sha256": _sha(node.text.strip().encode("utf-8")),
                }
            )
    return result


def _projection_targets(
    tei: etree._Element,
    provenance: Mapping[str, object],
) -> list[dict[str, object]]:
    targets: dict[str, list[dict[str, str]]] = {}
    tree = tei.getroottree()
    for node in tei.iter():
        for position, binding in enumerate(node.get("corresp", "").split(), 1):
            if binding.startswith("urn:ocd-source-observation:"):
                targets.setdefault(binding, []).append(
                    {
                        "kind": "tei-corresp",
                        "path": f"{tree.getpath(node)}/@corresp[{position}]",
                    }
                )

    def visit(value: object, pointer: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                escaped = str(key).replace("~", "~0").replace("/", "~1")
                visit(value[key], f"{pointer}/{escaped}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{pointer}/{index}")
        elif isinstance(value, str):
            for position, binding in enumerate(value.split(), 1):
                if binding.startswith("urn:ocd-source-observation:"):
                    targets.setdefault(binding, []).append(
                        {
                            "kind": "provenance-value",
                            "path": f"{pointer}#token={position}",
                        }
                    )

    visit(provenance, "$")
    return [
        {
            "binding": binding,
            "targets": sorted(values, key=lambda item: (item["kind"], item["path"])),
        }
        for binding, values in sorted(targets.items())
    ]


def _apply_projection_dispositions(
    observations: list[dict[str, object]],
    projection_targets: list[dict[str, object]],
) -> tuple[int, int, str]:
    source_bindings = {str(item["source_binding"]) for item in observations}
    candidate_bindings = {str(item["binding"]) for item in projection_targets}
    extras = sorted(candidate_bindings - source_bindings)
    if extras:
        raise ValueError(f"candidate projection invented source bindings: {extras[:3]}")
    for observation in observations:
        binding = str(observation["source_binding"])
        if binding in candidate_bindings:
            observation["disposition"] = "represented"
            observation["candidate_binding"] = binding
        else:
            observation["disposition"] = "evidence-only"
            observation.pop("candidate_binding", None)
    dispositions = [str(item["disposition"]) for item in observations]
    return (
        dispositions.count("represented"),
        dispositions.count("evidence-only"),
        _sha(_canonical(dispositions)),
    )


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = _profile(source_manifest)
    _policy(source_manifest)
    loaded_paths = _assert_runtime_origins(source_manifest.repository_root)
    members = _primary_members(source_manifest)
    scope = profile["source_scope"]
    assert isinstance(scope, dict)
    observed_set = [
        {"path": logical, "bytes": len(content), "sha256": _sha(content)}
        for logical, _, content in members
    ]
    if len(members) != 142 or sum(len(content) for _, _, content in members) != 5_110_829:
        raise ValueError("retained Kempis member census drifted")
    member_set_sha = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": observed_set})
    )
    if member_set_sha != scope["member_set_sha256"]:
        raise ValueError("retained Kempis member identity drifted")
    source_root = members[0][1].parents[0]
    while source_root.name != SOURCE_SLUG:
        source_root = source_root.parent
    _verify_checkout(source_root, profile, [row["path"] for row in observed_set])
    config = source_manifest.authority_path("local-source-config").read_bytes()
    if len(config) != 1_197 or _sha(config) != scope["config_sha256"]:
        raise ValueError("Kempis local source config drifted")

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    roots: dict[str, etree._ElementTree] = {}
    binding_maps: dict[str, dict[etree._Element, str]] = {}
    observations: list[dict[str, object]] = []
    non_xml: list[dict[str, object]] = []
    kinds = {"element": 0, "attribute": 0, "text": 0}
    for logical, path, content in members:
        try:
            tree = etree.parse(str(path), parser)
        except etree.XMLSyntaxError:
            non_xml.append(
                {
                    "member": logical,
                    "bytes": len(content),
                    "sha256": _sha(content),
                    "disposition": profile["non_xml_dispositions"][logical],
                }
            )
            continue
        roots[logical] = tree
        member_observations, member_bindings = _observations(logical, tree)
        observations.extend(member_observations)
        binding_maps[logical] = member_bindings
        for observation in member_observations:
            kinds[str(observation["kind"])] += 1
    if (
        len(roots),
        len(non_xml),
        len(observations),
        kinds,
    ) != (135, 7, 10_009, {"element": 3_582, "attribute": 4_283, "text": 2_144}):
        raise ValueError("complete Kempis XML/non-XML accounting drifted")

    opf = roots["src/epub/content.opf"]
    ns = {"opf": OPF}
    href_by_id = {
        item.get("id"): item.get("href")
        for item in opf.xpath("//opf:manifest/opf:item", namespaces=ns)
    }
    spine = [
        href_by_id[item.get("idref")]
        for item in opf.xpath("//opf:spine/opf:itemref", namespaces=ns)
    ]
    if len(spine) != 126:
        raise ValueError("Kempis OPF spine cardinality drifted")
    semantics = _semantic_bindings(roots, spine, binding_maps)

    tei = _element("TEI", {"version": "4.9.0"})
    tei.append(_tei_header(profile, member_set_sha))
    text = _element("text")
    body_out = _element("body")
    text.append(body_out)
    tei.append(text)
    for href in spine:
        logical = f"src/epub/{href}"
        source_tree = roots[logical]
        source_body = source_tree.find(f".//{{{XHTML}}}body")
        if source_body is None:
            raise ValueError(f"spine member {logical} has no body")
        sections = source_body.findall(f"{{{XHTML}}}section")
        if len(sections) != 1:
            raise ValueError(f"spine member {logical} top-level section count drifted")
        converted = _block(sections[0], binding_maps[logical])
        matter = next(
            token
            for token in _types(source_body)
            if token in {"frontmatter", "bodymatter", "backmatter"}
        )
        converted.set("ana", f"#{matter}")
        converted.set(XML_LANG, str(source_tree.getroot().get(XML_LANG)))
        converted.set(
            "corresp",
            f"{converted.get('corresp')} {binding_maps[logical][source_tree.getroot()]}",
        )
        body_out.append(converted)
    tei_bytes = etree.tostring(
        tei, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )

    semantic_digests = {
        key: _sha(_canonical(value))
        for key, value in semantics.items()
        if isinstance(value, list)
    }
    if semantic_digests != profile["semantic_digests"]:
        raise ValueError("Kempis occurrence-bound semantic inventory drifted")
    producer_closure_sha, producer_closure = _producer_closure(
        source_manifest.repository_root
    )
    if producer_closure_sha != profile["producer_import_closure_sha256"]:
        raise ValueError("Kempis producer recursive import closure drifted")

    svg_strings = _svg_strings(roots)
    image_members = [
        row
        for row in observed_set
        if row["path"]
        in {
            "images/cover.jpg",
            "images/cover.source.jpg",
            "images/cover.svg",
            "images/titlepage.svg",
            "src/epub/images/cover.svg",
            "src/epub/images/logo.svg",
            "src/epub/images/titlepage.svg",
        }
    ]
    provenance = {
        "contract": "ocd-imitation-of-christ-provenance-v1",
        "status": "nonaccepted",
        "retained_commit": scope["commit"],
        "retained_tree": scope["tree"],
        "source_member_set_sha256": member_set_sha,
        "config_sha256": scope["config_sha256"],
        "spine": spine,
        "toc": semantics["toc"],
        "landmarks": semantics["landmarks"],
        "image_members": image_members,
        "packaged_images": semantics["images"],
        "svg_strings": svg_strings,
        "css_semantics": profile["css_semantics"],
        "metadata": profile["metadata"],
        "metadata_conflicts": profile["metadata_conflicts"],
        "rights": profile["rights"],
        "loaded_module_paths": loaded_paths,
        "producer_import_closure_sha256": producer_closure_sha,
        "producer_import_closure": producer_closure,
    }
    projection_targets = _projection_targets(tei, provenance)
    expected_projection_bindings: set[str] = set()
    for href in spine:
        logical = f"src/epub/{href}"
        source_tree = roots[logical]
        expected_projection_bindings.add(binding_maps[logical][source_tree.getroot()])
        source_section = source_tree.find(f".//{{{XHTML}}}body/{{{XHTML}}}section")
        if source_section is None:
            raise ValueError("spine section disappeared during projection accounting")
        expected_projection_bindings.update(
            binding_maps[logical][node] for node in source_section.iter()
        )
    expected_projection_bindings.update(
        str(record["binding"])
        for key in ("toc", "landmarks")
        for record in semantics[key]
    )
    if {str(item["binding"]) for item in projection_targets} != expected_projection_bindings:
        raise ValueError("candidate omitted or invented a source-derived projection carrier")
    represented, evidence_only, ordered_disposition_sha = _apply_projection_dispositions(
        observations, projection_targets
    )
    represented_bindings = {str(item["candidate_binding"]) for item in observations if item["disposition"] == "represented"}
    evidence_bindings = {str(item["source_binding"]) for item in observations if item["disposition"] == "evidence-only"}
    projected_bindings = [str(item["binding"]) for item in projection_targets]
    if represented_bindings != set(projected_bindings) or represented_bindings & evidence_bindings:
        raise ValueError("candidate projection/source disposition bijection failed")
    accountability = {
        "contract": "ocd-imitation-of-christ-source-accountability-v1",
        "schema": "imitation-of-christ.source-accountability.schema.json",
        "source_members": observed_set,
        "source_member_set_sha256": member_set_sha,
        "xml_member_count": 135,
        "non_xml_member_count": 7,
        "xml_observation_count": 10_009,
        "element_count": 3_582,
        "attribute_count": 4_283,
        "text_count": 2_144,
        "source_binding_count": len(represented_bindings | evidence_bindings),
        "represented_binding_count": len(represented_bindings),
        "evidence_only_binding_count": len(evidence_bindings),
        "candidate_binding_count": len(projected_bindings),
        "candidate_binding_set_sha256": _sha(_canonical(projected_bindings)),
        "represented_count": represented,
        "evidence_only_count": evidence_only,
        "ordered_dispositions_sha256": ordered_disposition_sha,
        "omitted_count": 0,
        "duplicate_count": 0,
        "observations": observations,
        "projection_targets": projection_targets,
        "non_xml_dispositions": non_xml,
        "semantic_bindings": semantics,
        "semantic_digests": semantic_digests,
    }
    unresolved = [
        {
            "id": identifier,
            "status": "unresolved",
            "detail": str(profile["unresolved_claims"][identifier]),
        }
        for identifier in _policy(source_manifest)["required_unresolved_ids"]
    ]
    readme = (
        "# Source and rights\n\n"
        "This is an explicitly nonaccepted reconstruction candidate from the exact retained Standard Ebooks checkout. "
        "It preserves the retained attribution dispute, date uncertainty, the 1874 dedication versus 1877 colophon conflict, "
        "the local Project Gutenberg #26222 claim versus the retained #1653 basis, and the complete contributor set.\n\n"
        "Source links: https://github.com/standardebooks/thomas-a-kempis_the-imitation-of-christ_william-benham ; "
        "https://standardebooks.org/ebooks/thomas-a-kempis/the-imitation-of-christ/william-benham ; "
        "https://www.gutenberg.org/ebooks/1653 .\n\n"
        "The retained license says the underlying text and artwork are believed public domain in the United States, warns that "
        "other jurisdictions may differ, and separately dedicates Standard Ebooks contributions under CC0 1.0. These categories "
        "are not conflated. Machine validation is not human textual acceptance or publication authorization.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
