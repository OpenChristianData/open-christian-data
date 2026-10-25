"""Work-local ThML-to-TEI producer for LIB-055 / 37c-268.

The route binds the complete retained Matthew member. Candidate packaging and
review remain coordinator work; this callable only returns package-member
bytes in memory.
"""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree


CONVERTER_ID = "ryle-expository-thoughts-matthew-lib055-source-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "ryle-expository-thoughts-matthew"
TICKET_ID = "37c-268"
OWNER_ROUTE = "LIB-055"
SOURCE_PATH = "raw/ccel/ryle/matthew.xml"
SOURCE_BYTES = 763_304
SOURCE_SHA256 = "47639fe6d02e31d674fb055b1558d912bdf2747c5e2f8fa342b5df3b2d827a24"
MANIFEST_PATH = "sources/structured-text/ryle-expository-thoughts-matthew/lib055/37c-268.source-manifest.json"
PROFILE_PATH = "sources/structured-text/ryle-expository-thoughts-matthew/lib055/source-feature-profile.json"
POLICY_PATH = "sources/structured-text/ryle-expository-thoughts-matthew/lib055/validation-policy.json"
FOCUS_SELECTOR = "div1[@id='xiv']/div2[@id='xiv.v']"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_ROLES = {
    "source-member": "primary-source",
    "feature-profile": "complete-source-feature-profile",
    "policy": "independent-validation-policy",
    "ccel-permission": "exact-source-permission",
    "tei-schema": "tei-validation-schema",
    "package-schema": "candidate-package-schema",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _strict_json(data: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority(source_manifest, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    rows = [row for row in authorities if row.get("name") == name]
    if len(rows) != 1:
        raise ValueError(f"manifest must bind exactly one {name!r} authority")
    return rows[0]


def _authority_bytes(source_manifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _tag(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("expected an XML element")
    return etree.QName(node).localname


def _parse(raw: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        recover=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
        huge_tree=True,
    )
    try:
        tree = etree.parse(BytesIO(raw), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Ryle ThML source is malformed") from exc
    if any(item.level >= etree.ErrorLevels.ERROR for item in parser.error_log):
        raise ValueError("retained Ryle ThML parser reported an error")
    return tree


def _raw_prolog(raw: bytes) -> dict[str, object]:
    root_start = raw.find(b"<ThML")
    if root_start < 0:
        raise ValueError("retained ThML root start is absent from raw source bytes")
    prolog = raw[:root_start]
    return {
        "bytes_before_root": root_start,
        "sha256": _sha(prolog),
        "utf8": prolog.decode("utf-8"),
    }


def _siblings(first: etree._Element | None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    node = first
    while node is not None:
        if isinstance(node, etree._Comment):
            result.append({"kind": "comment", "text": node.text or ""})
        elif isinstance(node, etree._ProcessingInstruction):
            result.append(
                {
                    "kind": "processing-instruction",
                    "target": node.target,
                    "text": node.text or "",
                }
            )
        node = node.getnext()
    return result


def _shell(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    previous: list[etree._Element] = []
    node = root.getprevious()
    while node is not None:
        previous.append(node)
        node = node.getprevious()
    previous.reverse()
    doctype = tree.docinfo.doctype
    return {
        "xml_declaration": {
            "version": tree.docinfo.xml_version,
            "encoding": tree.docinfo.encoding,
            "standalone": tree.docinfo.standalone,
        },
        "doctype": {
            "name": tree.docinfo.root_name,
            "public_id": tree.docinfo.public_id,
            "system_url": tree.docinfo.system_url,
            "declaration": doctype,
            "declaration_sha256": _sha(doctype.encode("utf-8")),
        },
        "before_root_nodes": _siblings(previous[0] if previous else None),
        "after_root_nodes": _siblings(root.getnext()),
        "root_tail": root.tail,
    }


def _body_direct_nodes(
    tree: etree._ElementTree, body: etree._Element
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for ordinal, node in enumerate(body, start=1):
        if isinstance(node, etree._Comment):
            result.append(
                {
                    "ordinal": ordinal,
                    "kind": "comment",
                    "text": node.text or "",
                    "tail": node.tail or "",
                }
            )
        elif isinstance(node.tag, str):
            result.append(
                {
                    "ordinal": ordinal,
                    "kind": "element",
                    "tag": _tag(node),
                    "id": node.get("id"),
                    "title": node.get("title"),
                }
            )
        else:
            raise ValueError("unsupported direct node in ThML.body")
    return result


def _measure(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    if _tag(root) != "ThML" or [
        _tag(node) for node in root if isinstance(node.tag, str)
    ] != [
        "ThML.head",
        "ThML.body",
    ]:
        raise ValueError("source is not the expected complete ThML head/body envelope")
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("source head or body is absent")
    tag_counts = Counter(_tag(node) for node in elements)
    head_counts = Counter(
        _tag(node) for node in head.iter() if isinstance(node.tag, str)
    )
    body_counts = Counter(
        _tag(node) for node in body.iter() if isinstance(node.tag, str)
    )
    attributes: dict[str, set[str]] = {}
    for node in elements:
        attributes.setdefault(_tag(node), set()).update(node.attrib)
    ids = [node.get("id") for node in elements if node.get("id") is not None]
    paths = [tree.getpath(node) for node in elements]
    divisions = [node for node in body if isinstance(node.tag, str)]
    if any(_tag(node) != "div1" for node in divisions):
        raise ValueError("source body has an unaccounted top-level element")
    focus = root.xpath("./ThML.body/div1[@id='xiv']/div2[@id='xiv.v']")
    if len(focus) != 1 or focus[0].getparent().get("title") != "Matthew 13":
        raise ValueError("parent-qualified Matthew 14:22-36 source carrier changed")
    focus_refs = [node.get("osisRef") for node in focus[0].iter("scripCom")]
    matt14_titles = [
        node.get("title")
        for node in root.iter()
        if isinstance(node.tag, str)
        and _tag(node) in {"div1", "div2"}
        and node.get("title") in {"Matthew 14", "Matthew 14:1-21"}
    ]
    matt14_commentary = [
        node.get("osisRef")
        for node in root.iter("scripCom")
        if node.get("osisRef") == "Bible:Matt.14.1-Matt.14.21"
    ]
    links = [node.get("href", "") for node in body.iter("a")]
    source_ids = set(ids)
    body_comments = [node for node in body.iter() if isinstance(node, etree._Comment)]
    all_comments = [node for node in root.iter() if isinstance(node, etree._Comment)]
    return {
        "root": _tag(root),
        "root_attributes": dict(root.attrib),
        "ordered_root_elements": [
            _tag(node) for node in root if isinstance(node.tag, str)
        ],
        "shell": _shell(tree),
        "element_count": len(elements),
        "attribute_count": sum(len(node.attrib) for node in elements),
        "element_text_slots": sum(node.text is not None for node in elements),
        "element_tail_slots": sum(node.tail is not None for node in elements),
        "unique_element_paths": len(paths) == len(set(paths)),
        "source_id_count": len(ids),
        "unique_source_id_count": len(source_ids),
        "comment_count": len(all_comments),
        "head_comment_count": sum(
            1 for node in all_comments if head in node.iterancestors()
        ),
        "body_comment_count": len(body_comments),
        "head_tag_counts": dict(sorted(head_counts.items())),
        "body_tag_counts_including_wrapper": dict(sorted(body_counts.items())),
        "source_tag_counts": dict(sorted(tag_counts.items())),
        "source_attribute_names_by_element": {
            tag: sorted(names) for tag, names in sorted(attributes.items()) if names
        },
        "body_direct_nodes": _body_direct_nodes(tree, body),
        "body_direct_div1_ids_in_order": [node.get("id") for node in divisions],
        "body_direct_div1_titles_in_order": [node.get("title") for node in divisions],
        "focus_carrier": {
            "selector": FOCUS_SELECTOR,
            "matches": len(focus),
            "parent_id": focus[0].getparent().get("id"),
            "parent_title": focus[0].getparent().get("title"),
            "id": focus[0].get("id"),
            "title": focus[0].get("title"),
            "commentary_osis_refs": focus_refs,
        },
        "matthew_14_1_21_gap": {
            "top_level_or_nested_division_titles": matt14_titles,
            "exact_commentary_osis_refs": matt14_commentary,
            "disposition": "no-source-native-carrier; do-not-invent-or-reparent",
        },
        "links": {
            "count": len(links),
            "fragment_links": sum("#" in link for link in links),
            "all_fragment_targets_resolve": all(
                link.rsplit("#", 1)[1] in source_ids for link in links if "#" in link
            ),
        },
    }


def _verify_route(
    source_manifest, raw: bytes
) -> tuple[dict[str, object], dict[str, object]]:
    record = source_manifest.record
    if any(
        record.get(key) != value
        for key, value in (
            ("ticket", TICKET_ID),
            ("owner_route", OWNER_ROUTE),
            ("work_id", WORK_ID),
            ("source_id", "ryle-expository-thoughts-matthew-lib055-retained-xml"),
        )
    ):
        raise ValueError("manifest is not the exact LIB-055 / 37c-268 route")
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256:
        raise ValueError("retained Matthew XML differs from the pinned source member")
    source_row = _authority(source_manifest, "source-member")
    if any(
        source_row.get(key) != value
        for key, value in (
            ("path", SOURCE_PATH),
            ("bytes", SOURCE_BYTES),
            ("sha256", SOURCE_SHA256),
        )
    ):
        raise ValueError("manifest does not bind the exact retained Matthew member")
    roles = {row.get("name"): row.get("role") for row in record["authorities"]}
    if roles != _ROLES:
        raise ValueError(
            "manifest authority inventory differs from the work-local route"
        )
    scope = record.get("scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("selector") != "ThML[1] (complete retained document envelope)"
        or scope.get("selected_source_path") != "ThML[1]"
        or tuple(scope.get("member_order", ())) != (SOURCE_PATH,)
        or scope.get("member_count") != 1
        or scope.get("focus_selector") != FOCUS_SELECTOR
    ):
        raise ValueError("manifest scope or parent-qualified focus selector differs")
    profile = _strict_json(
        _authority_bytes(source_manifest, "feature-profile"), "feature profile"
    )
    policy = _strict_json(
        _authority_bytes(source_manifest, "policy"), "validation policy"
    )
    if profile.get("work_id") != WORK_ID or policy.get("work_id") != WORK_ID:
        raise ValueError("source profile or policy is misbound")
    if profile.get("source_member") != {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
        "format": "CCEL ThML XML",
    } or profile.get("raw_prolog") != _raw_prolog(raw):
        raise ValueError(
            "source profile does not bind the exact member and raw prolog bytes"
        )
    policy_scope = policy.get("scope")
    if (
        not isinstance(policy_scope, Mapping)
        or tuple(policy_scope.get("member_order", ())) != (SOURCE_PATH,)
        or policy_scope.get("focus_selector") != FOCUS_SELECTOR
        or policy_scope.get("exclusions") != []
    ):
        raise ValueError("policy does not cover the exact complete retained member")
    permission = _authority_bytes(source_manifest, "ccel-permission").decode("utf-8")
    if "parsing ThML/XML files for text is explicitly permitted" not in permission:
        raise ValueError("manifest does not bind the CCEL text-parsing permission")
    observed = record.get("identity")
    if not isinstance(observed, Mapping) or _plain(
        observed.get("source_record_metadata")
    ) != {
        "title": "Expository Thoughts on Matthew",
        "creator": ["J. C. Ryle", "Ryle, John C. (1816-1900)"],
        "language": "eng",
    }:
        raise ValueError(
            "manifest source-record observations differ from retained header"
        )
    if any(
        observed.get(field) is not None
        for field in (
            "textual_form",
            "edition",
            "parts",
            "witness_claim",
            "translator",
            "original_publication_year",
        )
    ):
        raise ValueError(
            "manifest promoted an unresolved work, edition, part, or witness claim"
        )
    return profile, policy


def _map_attrs(
    source: etree._Element, target: etree._Element, target_name: str
) -> None:
    tag = _tag(source)
    source_id = source.get("id")
    if source_id is not None:
        target.set(f"{{{XML_NS}}}id", source_id)
    if tag in {"div1", "div2", "div"}:
        target.set("type", f"source-{tag}")
        if source.get("title") is not None:
            target.set("n", source.get("title", ""))
        if source.get("class") is not None:
            target.set("subtype", source.get("class", ""))
        for name in ("prev", "next"):
            if source.get(name) is not None:
                target.set(name, source.get(name, ""))
        if tag == "div1" and source_id == "i":
            target.set("subtype", "front-matter")
        elif tag == "div1" and source_id == "xxix":
            target.set("subtype", "back-matter")
    elif tag == "p":
        renditions = []
        if source.get("class") is not None:
            renditions.append(source.get("class", ""))
        if source.get("style") is not None:
            renditions.append(f"source-style={source.get('style', '')}")
        if renditions:
            target.set("rend", " | ".join(renditions))
    elif tag == "a":
        if source.get("href") is None:
            raise ValueError("source anchor is missing href")
        target.set("target", source.get("href", ""))
        if source.get("class") is not None:
            target.set("type", source.get("class", ""))
    elif tag == "scripRef":
        target.set("type", "scripture")
        if source.get("osisRef") is not None:
            target.set("target", source.get("osisRef", ""))
        if source.get("passage") is not None:
            target.set("n", source.get("passage", ""))
    elif tag == "scripCom":
        target.set("type", "scripture-commentary-marker")
        if source.get("type") is not None:
            target.set("subtype", source.get("type", ""))
        if source.get("osisRef") is not None:
            target.set("corresp", source.get("osisRef", ""))
        if source.get("passage") is not None:
            target.set("n", source.get("passage", ""))
    elif tag == "insertIndex":
        target.set("type", "index-insertion")
        if source.get("type") is not None:
            target.set("subtype", source.get("type", ""))
    elif tag in {"h1", "h2", "h3"} and target_name == "head":
        target.set("type", f"source-{tag}")
    elif tag in {"h1", "h2", "h3"}:
        target.set("rend", f"source-heading-{tag}")
    elif tag == "i":
        target.set("rend", "italic")


def _target_name(source: etree._Element, first_element: bool) -> str:
    tag = _tag(source)
    fixed = {
        "div1": "div",
        "div2": "div",
        "div": "div",
        "p": "p",
        "a": "ref",
        "scripRef": "ref",
        "scripCom": "anchor",
        "insertIndex": "anchor",
        "br": "lb",
        "i": "hi",
    }
    if tag in fixed:
        return fixed[tag]
    if tag in {"h1", "h2", "h3"}:
        return "head" if first_element else "p"
    raise ValueError(f"unsupported retained body carrier {tag!r}")


def _append_body(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    first = next((node for node in source if isinstance(node.tag, str)), None)
    for child in source:
        if isinstance(child, etree._Comment):
            mapped = etree.Comment(child.text or "")
        elif isinstance(child.tag, str):
            name = _target_name(child, child is first)
            mapped = etree.Element(f"{{{TEI_NS}}}{name}")
            _map_attrs(child, mapped, name)
            if _tag(child) in {"scripCom", "insertIndex", "br"}:
                if (child.text or "").strip() or len(child):
                    raise ValueError(
                        f"empty source marker {_tag(child)!r} gained content"
                    )
            else:
                _append_body(child, mapped)
        else:
            raise ValueError(f"unsupported node in source {_tag(source)!r}")
        mapped.tail = child.tail
        target.append(mapped)


def _source_note(
    notes: etree._Element, tree: etree._ElementTree, node: etree._Element
) -> None:
    tag = _tag(node)
    note = etree.SubElement(
        notes, f"{{{TEI_NS}}}note", type="source-head-field", subtype=tag
    )
    note.set(
        "n",
        json.dumps(
            {"path": tree.getpath(node), "attributes": dict(node.attrib)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    if tag == "description":
        note.text = node.text
        for child in node:
            if not isinstance(child.tag, str):
                raise ValueError("unsupported node in source description")
            if _tag(child) == "i":
                mapped = etree.Element(f"{{{TEI_NS}}}hi", rend="italic")
                mapped.text = child.text
            elif _tag(child) == "br":
                mapped = etree.Element(f"{{{TEI_NS}}}lb")
            else:
                raise ValueError(
                    f"unsupported source-description carrier {_tag(child)!r}"
                )
            mapped.tail = child.tail
            note.append(mapped)
        return
    value = "".join(node.itertext())
    if not value and node.attrib:
        value = json.dumps(
            dict(node.attrib), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
    note.text = value or None
    if not value:
        note.set("rend", "source-empty")


def _tei_bytes(tree: etree._ElementTree) -> bytes:
    root = tree.getroot()
    head = root.find("ThML.head")
    source_body = root.find("ThML.body")
    if head is None or source_body is None:
        raise ValueError("ThML head or body is absent")
    title = head.find(".//DC.Title")
    creators = head.findall(".//DC.Creator")
    creator = next(
        (node for node in creators if node.get("scheme") == "short-form"), None
    )
    language = head.find(".//DC.Language")
    if any(node is None for node in (title, creator, language)):
        raise ValueError("required source-record title, creator, or language is absent")

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    header = etree.SubElement(tei, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(
        title_stmt, f"{{{TEI_NS}}}title", type="source-record-title"
    ).text = title.text or ""
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = creator.text or ""
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(
        publication, f"{{{TEI_NS}}}p"
    ).text = "Nonaccepted technical candidate; human acceptance and publication are not authorized."
    notes = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    etree.SubElement(notes, f"{{{TEI_NS}}}note", type="identity-boundary").text = (
        "This route binds one exact retained CCEL member to the existing LIB-055 catalog work ID. "
        "It does not settle the textual form, edition, parts, print witness, original-publication "
        "date, rights clearance, or full catalog-work boundary."
    )
    etree.SubElement(
        notes, f"{{{TEI_NS}}}note", type="source-gap", n="Matthew 14:1-21"
    ).text = (
        "No source-native carrier for Matthew 14:1-21 is present in this retained member. "
        "No top-level Matthew 14 root is supplied, and the distinct Matthew 14:22-36 carrier "
        "remains nested beneath the source Matthew 13 division."
    )
    for node in head.iter():
        if not isinstance(node.tag, str):
            if isinstance(node, etree._Comment):
                note = etree.SubElement(
                    notes, f"{{{TEI_NS}}}note", type="source-head-comment"
                )
                note.text = node.text or ""
            continue
        tag = _tag(node)
        if tag == "style" or tag in {
            "ThML.head",
            "generalInfo",
            "printSourceInfo",
            "electronicEdInfo",
        }:
            continue
        if tag.startswith("DC.") or tag in {
            "description",
            "published",
            "property",
            "authorID",
            "bkgID",
            "workID",
            "bookID",
            "version",
            "publisherID",
            "status",
            "comments",
            "editorialComments",
            "revisionHistory",
            "pubHistory",
            "selector",
        }:
            _source_note(notes, tree, node)
    shell_note = etree.SubElement(
        notes, f"{{{TEI_NS}}}note", type="source-document-shell"
    )
    shell_note.text = json.dumps(
        _shell(tree), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )

    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibl = etree.SubElement(
        source_desc, f"{{{TEI_NS}}}bibl", type="retained-source-member"
    )
    etree.SubElement(bibl, f"{{{TEI_NS}}}title", type="source-record-title").text = (
        title.text or ""
    )
    etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = creator.text or ""
    etree.SubElement(
        bibl, f"{{{TEI_NS}}}idno", type="source-member-path"
    ).text = SOURCE_PATH
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="ocd-work-id").text = WORK_ID
    etree.SubElement(
        bibl, f"{{{TEI_NS}}}note", type="source-member-binding"
    ).text = f"{SOURCE_BYTES} bytes; SHA-256 {SOURCE_SHA256}."
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = (
        "All ThML.body child divisions and comments are represented in source order. "
        "The title page and indexes remain identified by their source IDs and titles. "
        "The complete ThML head, prolog, comments, attributes, text/tails, and provider "
        "formatting are independently inventoried; external formatting is not rendered."
    )
    profile_desc = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    language_usage = etree.SubElement(profile_desc, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(
        language_usage, f"{{{TEI_NS}}}language", ident=language.text or ""
    ).text = language.text or ""

    text = etree.SubElement(
        tei, f"{{{TEI_NS}}}text", {f"{{{XML_NS}}}lang": language.text or ""}
    )
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    for source_node in source_body:
        if isinstance(source_node, etree._Comment):
            mapped = etree.Comment(source_node.text or "")
            mapped.tail = source_node.tail
            body.append(mapped)
        elif isinstance(source_node.tag, str) and _tag(source_node) == "div1":
            mapped = etree.SubElement(body, f"{{{TEI_NS}}}div")
            _map_attrs(source_node, mapped, "div")
            _append_body(source_node, mapped)
        else:
            raise ValueError("source body contains an unsupported direct carrier")
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True)


def _element_rows(tree: etree._ElementTree) -> list[dict[str, object]]:
    rows = []
    for ordinal, node in enumerate(
        (item for item in tree.getroot().iter() if isinstance(item.tag, str)), start=1
    ):
        text = node.text or ""
        tail = node.tail or ""
        rows.append(
            {
                "ordinal": ordinal,
                "path": tree.getpath(node),
                "parent_path": tree.getpath(node.getparent())
                if node.getparent() is not None
                else None,
                "tag": _tag(node),
                "attributes": dict(sorted(node.attrib.items())),
                "text_characters": len(text),
                "text_sha256": _sha(text.encode("utf-8")),
                "tail_characters": len(tail),
                "tail_sha256": _sha(tail.encode("utf-8")),
                "disposition": "mapped-or-explicitly-accounted-by-policy",
            }
        )
    return rows


def _comment_rows(tree: etree._ElementTree) -> list[dict[str, object]]:
    rows = []
    for ordinal, node in enumerate(
        (item for item in tree.getroot().iter() if isinstance(item, etree._Comment)),
        start=1,
    ):
        parent = node.getparent()
        rows.append(
            {
                "ordinal": ordinal,
                "path": tree.getpath(node),
                "parent_path": tree.getpath(parent) if parent is not None else None,
                "text": node.text or "",
                "tail": node.tail or "",
                "disposition": "represented-as-TEI-comment-or-header-note",
            }
        )
    return rows


def _accountability(
    source_manifest, tree: etree._ElementTree, profile: Mapping[str, object]
) -> bytes:
    body = tree.getroot().find("ThML.body")
    assert body is not None
    return _canonical(
        {
            "contract": "ocd-source-accountability-v1",
            "ticket": TICKET_ID,
            "owner_route": OWNER_ROUTE,
            "work_id": WORK_ID,
            "source_member": {
                "path": SOURCE_PATH,
                "bytes": SOURCE_BYTES,
                "sha256": SOURCE_SHA256,
            },
            "scope": _plain(source_manifest.record["scope"]),
            "source_envelope": {
                "profile": _plain(profile),
                "shell": _shell(tree),
                "raw_prolog": _raw_prolog(
                    _authority_bytes(source_manifest, "source-member")
                ),
            },
            "body_direct_nodes": _body_direct_nodes(tree, body),
            "elements": _element_rows(tree),
            "comments": _comment_rows(tree),
            "dispositions": {
                "unrepresented_body_divisions": [],
                "document_shell": "XML declaration, external DOCTYPE, and two stylesheet processing instructions recorded; DTD not fetched or copied.",
                "header": "All elements, attributes, comments, text, tails, and order inventoried; source-record fields are transcribed; provider formatting is accounted but not reproduced.",
                "matthew_14_1_21": "No source-native carrier; gap disclosed in profile, policy, and TEI header; no replacement root invented.",
                "xiv_v": "Represented as a child of the source xiv / Matthew 13 division; never reparented.",
            },
            "profile_sha256": _sha(
                _authority_bytes(source_manifest, "feature-profile")
            ),
            "policy_sha256": _sha(_authority_bytes(source_manifest, "policy")),
        }
    )


def _provenance(source_manifest, raw: bytes) -> bytes:
    return _canonical(
        {
            "contract": "ocd-source-to-tei-provenance-v1",
            "ticket": TICKET_ID,
            "owner_route": OWNER_ROUTE,
            "work_id": WORK_ID,
            "source_member": {
                "path": SOURCE_PATH,
                "bytes": len(raw),
                "sha256": _sha(raw),
            },
            "source_manifest": {
                "path": source_manifest.path.relative_to(
                    source_manifest.repository_root
                ).as_posix(),
                "sha256": source_manifest.sha256,
            },
            "converter": _plain(source_manifest.record["converter"]),
            "feature_profile_sha256": _sha(
                _authority_bytes(source_manifest, "feature-profile")
            ),
            "policy_sha256": _sha(_authority_bytes(source_manifest, "policy")),
            "scope_selector": source_manifest.record["scope"]["selector"],
            "focus_selector": FOCUS_SELECTOR,
            "candidate_status": "nonaccepted",
            "human_acceptance": "not-assessed",
            "publication_status": "not-authorized",
            "notes": "Produced as in-memory route output only; candidate generation and CVW admission remain coordinator work.",
        }
    )


def _unresolved(source_manifest) -> bytes:
    identity = source_manifest.record.get("identity")
    claims = identity.get("unresolved") if isinstance(identity, Mapping) else None
    if not isinstance(claims, Mapping) or not claims:
        raise ValueError("manifest must keep unresolved source identity claims visible")
    return b"".join(
        _canonical(
            {
                "claim": name,
                "status": "unresolved",
                "work_id": WORK_ID,
                "statement": value,
            }
        )
        for name, value in claims.items()
    )


def _readme() -> bytes:
    return (
        "# Source attribution\n\n"
        "This source route uses the retained CCEL ThML file `raw/ccel/ryle/matthew.xml`, "
        "sourced via CCEL.org. CCEL permits parsing ThML/XML for text; its copyright applies "
        "to CCEL files and formatting, not the underlying public-domain texts. Do not sell "
        "CCEL files or derivatives of their formatting. This attribution is not a rights "
        "clearance or publication authorization.\n"
    ).encode("utf-8")


def _convert(source_manifest) -> Mapping[str, bytes]:
    """Return the five non-manifest candidate members in memory; write nothing."""
    source_manifest.verify()
    raw = _authority_bytes(source_manifest, "source-member")
    profile, _policy = _verify_route(source_manifest, raw)
    tree = _parse(raw)
    measured = _measure(tree)
    if profile.get("document") != measured:
        raise ValueError(
            "source envelope differs from the pinned work-specific feature profile"
        )
    return {
        "README.source.md": _readme(),
        "content.tei.xml": _tei_bytes(tree),
        "provenance.json": _provenance(source_manifest, raw),
        "source-accountability.json": _accountability(source_manifest, tree, measured),
        "unresolved.jsonl": _unresolved(source_manifest),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
