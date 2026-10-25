"""Independent source-to-TEI oracle for LIB-055 / 37c-268.

This module does not import the producer or legacy CCEL parser. Its source
enumeration and expected TEI traversal are separate implementations. The
family-neutral reconstruction seam is used only to assemble final mechanical
attestation for a coordinator-created CandidatePackage.
"""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ryle-expository-thoughts-matthew-lib055-independent-source-oracle"
ORACLE_VERSION = "1"
WORK_ID = "ryle-expository-thoughts-matthew"
TICKET_ID = "37c-268"
OWNER_ROUTE = "LIB-055"
SOURCE_PATH = "raw/ccel/ryle/matthew.xml"
SOURCE_BYTES = 763_304
SOURCE_SHA256 = "47639fe6d02e31d674fb055b1558d912bdf2747c5e2f8fa342b5df3b2d827a24"
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


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _json(data: bytes, label: str) -> dict[str, object]:
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


def _authority(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [
        row for row in source_manifest.record["authorities"] if row.get("name") == name
    ]
    if len(matches) != 1:
        raise ValueError(f"oracle requires exactly one {name!r} authority")
    return matches[0]


def _authority_bytes(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _name(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("oracle expected an XML element")
    return etree.QName(node).localname


def _read(raw: bytes) -> etree._ElementTree:
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
        result = etree.parse(BytesIO(raw), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(
            "independent oracle could not parse retained ThML bytes"
        ) from exc
    if any(item.level >= etree.ErrorLevels.ERROR for item in parser.error_log):
        raise ValueError("independent source parser reported an XML error")
    return result


def _raw_prolog_bytes(raw: bytes) -> dict[str, object]:
    start = raw.find(b"<ThML")
    if start < 0:
        raise ValueError("oracle cannot locate the retained root in raw bytes")
    prolog = raw[:start]
    return {
        "bytes_before_root": start,
        "sha256": _digest(prolog),
        "utf8": prolog.decode("utf-8"),
    }


def _siblings(first: etree._Element | None) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    current = first
    while current is not None:
        if isinstance(current, etree._Comment):
            found.append({"kind": "comment", "text": current.text or ""})
        elif isinstance(current, etree._ProcessingInstruction):
            found.append(
                {
                    "kind": "processing-instruction",
                    "target": current.target,
                    "text": current.text or "",
                }
            )
        current = current.getnext()
    return found


def _shell_facts(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    preceding: list[etree._Element] = []
    current = root.getprevious()
    while current is not None:
        preceding.append(current)
        current = current.getprevious()
    preceding.reverse()
    declaration = tree.docinfo.doctype
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
            "declaration": declaration,
            "declaration_sha256": _digest(declaration.encode("utf-8")),
        },
        "before_root_nodes": _siblings(preceding[0] if preceding else None),
        "after_root_nodes": _siblings(root.getnext()),
        "root_tail": root.tail,
    }


def _direct_body_facts(body: etree._Element) -> list[dict[str, object]]:
    result = []
    for position, node in enumerate(body, start=1):
        if isinstance(node, etree._Comment):
            result.append(
                {
                    "ordinal": position,
                    "kind": "comment",
                    "text": node.text or "",
                    "tail": node.tail or "",
                }
            )
        elif isinstance(node.tag, str):
            result.append(
                {
                    "ordinal": position,
                    "kind": "element",
                    "tag": _name(node),
                    "id": node.get("id"),
                    "title": node.get("title"),
                }
            )
        else:
            raise ValueError("oracle found an unsupported ThML.body child")
    return result


def _source_facts(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    if _name(root) != "ThML":
        raise ValueError("oracle source root is not ThML")
    element_children = [node for node in root if isinstance(node.tag, str)]
    if [_name(node) for node in element_children] != ["ThML.head", "ThML.body"]:
        raise ValueError(
            "oracle source head/body order differs from the pinned envelope"
        )
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("oracle source head or body is absent")
    nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    head_nodes = [node for node in head.iter() if isinstance(node.tag, str)]
    body_nodes = [node for node in body.iter() if isinstance(node.tag, str)]
    all_counts = Counter(_name(node) for node in nodes)
    head_counts = Counter(_name(node) for node in head_nodes)
    body_counts = Counter(_name(node) for node in body_nodes)
    attribute_names: dict[str, set[str]] = {}
    for node in nodes:
        attribute_names.setdefault(_name(node), set()).update(node.attrib.keys())
    ids = [node.get("id") for node in nodes if node.get("id") is not None]
    paths = [tree.getpath(node) for node in nodes]
    divisions = [node for node in body if isinstance(node.tag, str)]
    if any(_name(node) != "div1" for node in divisions):
        raise ValueError("oracle encountered an unsupported top-level body element")
    selected = root.xpath("./ThML.body/div1[@id='xiv']/div2[@id='xiv.v']")
    if len(selected) != 1:
        raise ValueError(
            "oracle parent-qualified selector does not resolve exactly once"
        )
    parent = selected[0].getparent()
    if (
        parent is None
        or parent.get("id") != "xiv"
        or parent.get("title") != "Matthew 13"
    ):
        raise ValueError(
            "oracle found the Matthew 14:22-36 carrier detached from Matthew 13"
        )
    marker_refs = [part.get("osisRef") for part in selected[0].iter("scripCom")]
    absent_titles = [
        item.get("title")
        for item in root.iter()
        if isinstance(item.tag, str)
        and _name(item) in {"div1", "div2"}
        and item.get("title") in {"Matthew 14", "Matthew 14:1-21"}
    ]
    absent_markers = [
        item.get("osisRef")
        for item in root.iter("scripCom")
        if item.get("osisRef") == "Bible:Matt.14.1-Matt.14.21"
    ]
    ids_set = set(ids)
    urls = [item.get("href", "") for item in body.iter("a")]
    comments = [item for item in root.iter() if isinstance(item, etree._Comment)]
    body_comments = [item for item in body.iter() if isinstance(item, etree._Comment)]
    return {
        "root": _name(root),
        "root_attributes": dict(root.attrib),
        "ordered_root_elements": [_name(node) for node in element_children],
        "shell": _shell_facts(tree),
        "element_count": len(nodes),
        "attribute_count": sum(len(node.attrib) for node in nodes),
        "element_text_slots": sum(node.text is not None for node in nodes),
        "element_tail_slots": sum(node.tail is not None for node in nodes),
        "unique_element_paths": len(paths) == len(set(paths)),
        "source_id_count": len(ids),
        "unique_source_id_count": len(ids_set),
        "comment_count": len(comments),
        "head_comment_count": sum(
            1 for item in comments if head in item.iterancestors()
        ),
        "body_comment_count": len(body_comments),
        "head_tag_counts": dict(sorted(head_counts.items())),
        "body_tag_counts_including_wrapper": dict(sorted(body_counts.items())),
        "source_tag_counts": dict(sorted(all_counts.items())),
        "source_attribute_names_by_element": {
            tag: sorted(values)
            for tag, values in sorted(attribute_names.items())
            if values
        },
        "body_direct_nodes": _direct_body_facts(body),
        "body_direct_div1_ids_in_order": [node.get("id") for node in divisions],
        "body_direct_div1_titles_in_order": [node.get("title") for node in divisions],
        "focus_carrier": {
            "selector": FOCUS_SELECTOR,
            "matches": len(selected),
            "parent_id": parent.get("id"),
            "parent_title": parent.get("title"),
            "id": selected[0].get("id"),
            "title": selected[0].get("title"),
            "commentary_osis_refs": marker_refs,
        },
        "matthew_14_1_21_gap": {
            "top_level_or_nested_division_titles": absent_titles,
            "exact_commentary_osis_refs": absent_markers,
            "disposition": "no-source-native-carrier; do-not-invent-or-reparent",
        },
        "links": {
            "count": len(urls),
            "fragment_links": sum("#" in url for url in urls),
            "all_fragment_targets_resolve": all(
                url.rsplit("#", 1)[1] in ids_set for url in urls if "#" in url
            ),
        },
    }


def _bound_source(
    source_manifest: SourceManifest,
) -> tuple[bytes, dict[str, object], dict[str, object]]:
    source_manifest.verify()
    record = source_manifest.record
    if (record.get("ticket"), record.get("owner_route"), record.get("work_id")) != (
        TICKET_ID,
        OWNER_ROUTE,
        WORK_ID,
    ):
        raise ValueError("oracle received a different work or owner route")
    if (
        record.get("source_id")
        != "ryle-expository-thoughts-matthew-lib055-retained-xml"
    ):
        raise ValueError("oracle received a different source identity")
    role_map = {
        item.get("name"): item.get("role") for item in record.get("authorities", ())
    }
    if role_map != _ROLES:
        raise ValueError("oracle authority roles differ from the bound route")
    source_row = _authority(source_manifest, "source-member")
    if any(
        source_row.get(key) != value
        for key, value in (
            ("path", SOURCE_PATH),
            ("bytes", SOURCE_BYTES),
            ("sha256", SOURCE_SHA256),
        )
    ):
        raise ValueError("oracle source-member pin differs")
    scope = record.get("scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("selector") != "ThML[1] (complete retained document envelope)"
        or scope.get("focus_selector") != FOCUS_SELECTOR
        or tuple(scope.get("member_order", ())) != (SOURCE_PATH,)
    ):
        raise ValueError(
            "oracle manifest does not bind the complete envelope and exact focus selector"
        )
    profile = _json(
        _authority_bytes(source_manifest, "feature-profile"), "feature profile"
    )
    policy = _json(_authority_bytes(source_manifest, "policy"), "validation policy")
    if profile.get("work_id") != WORK_ID or policy.get("work_id") != WORK_ID:
        raise ValueError("oracle profile or policy is misbound")
    if profile.get("source_member") != {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
        "format": "CCEL ThML XML",
    }:
        raise ValueError("oracle profile source-member identity differs")
    policy_scope = policy.get("scope")
    if (
        not isinstance(policy_scope, Mapping)
        or policy_scope.get("focus_selector") != FOCUS_SELECTOR
        or policy_scope.get("exclusions") != []
    ):
        raise ValueError("oracle policy does not declare the exact source route")
    raw = _authority_bytes(source_manifest, "source-member")
    if len(raw) != SOURCE_BYTES or _digest(raw) != SOURCE_SHA256:
        raise ValueError("oracle retained source bytes differ from their exact binding")
    if profile.get("raw_prolog") != _raw_prolog_bytes(raw):
        raise ValueError(
            "oracle raw prolog bytes differ from the complete source-envelope profile"
        )
    permission = _authority_bytes(source_manifest, "ccel-permission").decode("utf-8")
    if "parsing ThML/XML files for text is explicitly permitted" not in permission:
        raise ValueError("oracle lacks the bound CCEL parsing-permission record")
    return raw, profile, policy


def _expected_attributes(source: etree._Element, target_name: str) -> dict[str, str]:
    tag = _name(source)
    attrs: dict[str, str] = {}
    if source.get("id") is not None:
        attrs[f"{{{XML_NS}}}id"] = source.get("id", "")
    if tag in {"div1", "div2", "div"}:
        attrs["type"] = f"source-{tag}"
        if source.get("title") is not None:
            attrs["n"] = source.get("title", "")
        if source.get("class") is not None:
            attrs["subtype"] = source.get("class", "")
        for name in ("prev", "next"):
            if source.get(name) is not None:
                attrs[name] = source.get(name, "")
        if tag == "div1" and source.get("id") == "i":
            attrs["subtype"] = "front-matter"
        elif tag == "div1" and source.get("id") == "xxix":
            attrs["subtype"] = "back-matter"
    elif tag == "p":
        renditions = []
        if source.get("class") is not None:
            renditions.append(source.get("class", ""))
        if source.get("style") is not None:
            renditions.append(f"source-style={source.get('style', '')}")
        if renditions:
            attrs["rend"] = " | ".join(renditions)
    elif tag == "a":
        if source.get("href") is None:
            raise ValueError("oracle found a source link without href")
        attrs["target"] = source.get("href", "")
        if source.get("class") is not None:
            attrs["type"] = source.get("class", "")
    elif tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("osisRef") is not None:
            attrs["target"] = source.get("osisRef", "")
        if source.get("passage") is not None:
            attrs["n"] = source.get("passage", "")
    elif tag == "scripCom":
        attrs["type"] = "scripture-commentary-marker"
        if source.get("type") is not None:
            attrs["subtype"] = source.get("type", "")
        if source.get("osisRef") is not None:
            attrs["corresp"] = source.get("osisRef", "")
        if source.get("passage") is not None:
            attrs["n"] = source.get("passage", "")
    elif tag == "insertIndex":
        attrs["type"] = "index-insertion"
        if source.get("type") is not None:
            attrs["subtype"] = source.get("type", "")
    elif tag in {"h1", "h2", "h3"} and target_name == "head":
        attrs["type"] = f"source-{tag}"
    elif tag in {"h1", "h2", "h3"}:
        attrs["rend"] = f"source-heading-{tag}"
    elif tag == "i":
        attrs["rend"] = "italic"
    return attrs


def _expected_name(source: etree._Element, is_first: bool) -> str:
    translated = {
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
    name = _name(source)
    if name in translated:
        return translated[name]
    if name in {"h1", "h2", "h3"}:
        return "head" if is_first else "p"
    raise ValueError(f"oracle found an unmapped source carrier {name!r}")


def _expected_body_children(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    first = next((node for node in source if isinstance(node.tag, str)), None)
    for child in source:
        if isinstance(child, etree._Comment):
            made = etree.Comment(child.text or "")
        elif isinstance(child.tag, str):
            local = _expected_name(child, child is first)
            made = etree.Element(f"{{{TEI_NS}}}{local}")
            for name, value in _expected_attributes(child, local).items():
                made.set(name, value)
            if _name(child) in {"scripCom", "insertIndex", "br"}:
                if (child.text or "").strip() or len(child):
                    raise ValueError(
                        "oracle empty-marker expectation no longer matches source"
                    )
            else:
                _expected_body_children(child, made)
        else:
            raise ValueError("oracle found an unsupported body node")
        made.tail = child.tail
        target.append(made)


def _expected_head_note(
    parent: etree._Element, tree: etree._ElementTree, source: etree._Element
) -> None:
    tag = _name(source)
    made = etree.SubElement(
        parent, f"{{{TEI_NS}}}note", type="source-head-field", subtype=tag
    )
    made.set(
        "n",
        json.dumps(
            {"path": tree.getpath(source), "attributes": dict(source.attrib)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    if tag == "description":
        made.text = source.text
        for child in source:
            if not isinstance(child.tag, str):
                raise ValueError("oracle found a non-element description child")
            if _name(child) == "i":
                mapped = etree.Element(f"{{{TEI_NS}}}hi", rend="italic")
                mapped.text = child.text
            elif _name(child) == "br":
                mapped = etree.Element(f"{{{TEI_NS}}}lb")
            else:
                raise ValueError("oracle found an unsupported description markup")
            mapped.tail = child.tail
            made.append(mapped)
    else:
        value = "".join(source.itertext())
        if not value and source.attrib:
            value = json.dumps(
                dict(source.attrib),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        made.text = value or None
        if not value:
            made.set("rend", "source-empty")


def _expected_tei(source_tree: etree._ElementTree) -> etree._Element:
    source_root = source_tree.getroot()
    head = source_root.find("ThML.head")
    source_body = source_root.find("ThML.body")
    if head is None or source_body is None:
        raise ValueError("oracle source lacks its complete head/body envelope")
    title = head.find(".//DC.Title")
    people = head.findall(".//DC.Creator")
    author = next((item for item in people if item.get("scheme") == "short-form"), None)
    language = head.find(".//DC.Language")
    if title is None or author is None or language is None:
        raise ValueError("oracle source title, author, or language is absent")

    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_statement = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(
        title_statement, f"{{{TEI_NS}}}title", type="source-record-title"
    ).text = title.text or ""
    etree.SubElement(title_statement, f"{{{TEI_NS}}}author").text = author.text or ""
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
    for item in head.iter():
        if not isinstance(item.tag, str):
            if isinstance(item, etree._Comment):
                etree.SubElement(
                    notes, f"{{{TEI_NS}}}note", type="source-head-comment"
                ).text = item.text or ""
            continue
        local = _name(item)
        if local == "style" or local in {
            "ThML.head",
            "generalInfo",
            "printSourceInfo",
            "electronicEdInfo",
        }:
            continue
        if local.startswith("DC.") or local in {
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
            _expected_head_note(notes, source_tree, item)
    shell_note = etree.SubElement(
        notes, f"{{{TEI_NS}}}note", type="source-document-shell"
    )
    shell_note.text = json.dumps(
        _shell_facts(source_tree),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    source_description = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibliography = etree.SubElement(
        source_description, f"{{{TEI_NS}}}bibl", type="retained-source-member"
    )
    etree.SubElement(
        bibliography, f"{{{TEI_NS}}}title", type="source-record-title"
    ).text = title.text or ""
    etree.SubElement(bibliography, f"{{{TEI_NS}}}author").text = author.text or ""
    etree.SubElement(
        bibliography, f"{{{TEI_NS}}}idno", type="source-member-path"
    ).text = SOURCE_PATH
    etree.SubElement(
        bibliography, f"{{{TEI_NS}}}idno", type="ocd-work-id"
    ).text = WORK_ID
    etree.SubElement(
        bibliography, f"{{{TEI_NS}}}note", type="source-member-binding"
    ).text = f"{SOURCE_BYTES} bytes; SHA-256 {SOURCE_SHA256}."
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(project, f"{{{TEI_NS}}}p").text = (
        "All ThML.body child divisions and comments are represented in source order. "
        "The title page and indexes remain identified by their source IDs and titles. "
        "The complete ThML head, prolog, comments, attributes, text/tails, and provider "
        "formatting are independently inventoried; external formatting is not rendered."
    )
    profile = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    usage = etree.SubElement(profile, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(usage, f"{{{TEI_NS}}}language", ident=language.text or "").text = (
        language.text or ""
    )
    text = etree.SubElement(
        root, f"{{{TEI_NS}}}text", {f"{{{XML_NS}}}lang": language.text or ""}
    )
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    for item in source_body:
        if isinstance(item, etree._Comment):
            made = etree.Comment(item.text or "")
            made.tail = item.tail
            body.append(made)
        elif isinstance(item.tag, str) and _name(item) == "div1":
            made = etree.SubElement(body, f"{{{TEI_NS}}}div")
            for key, value in _expected_attributes(item, "div").items():
                made.set(key, value)
            _expected_body_children(item, made)
        else:
            raise ValueError("oracle found an unsupported direct source-body carrier")
    return root


def _tree_signature(node: etree._Element) -> object:
    if isinstance(node, etree._Comment):
        return ("comment", node.text, node.tail)
    if not isinstance(node.tag, str):
        raise ValueError("candidate contains an unsupported XML node")
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text,
        tuple(_tree_signature(child) for child in node),
        node.tail,
    )


def _element_ledger(tree: etree._ElementTree) -> list[dict[str, object]]:
    rows = []
    for order, element in enumerate(
        (item for item in tree.getroot().iter() if isinstance(item.tag, str)), start=1
    ):
        before = element.text or ""
        after = element.tail or ""
        parent = element.getparent()
        rows.append(
            {
                "ordinal": order,
                "path": tree.getpath(element),
                "parent_path": tree.getpath(parent) if parent is not None else None,
                "tag": _name(element),
                "attributes": dict(sorted(element.attrib.items())),
                "text_characters": len(before),
                "text_sha256": _digest(before.encode("utf-8")),
                "tail_characters": len(after),
                "tail_sha256": _digest(after.encode("utf-8")),
                "disposition": "mapped-or-explicitly-accounted-by-policy",
            }
        )
    return rows


def _comment_ledger(tree: etree._ElementTree) -> list[dict[str, object]]:
    results = []
    for sequence, comment in enumerate(
        (node for node in tree.getroot().iter() if isinstance(node, etree._Comment)),
        start=1,
    ):
        parent = comment.getparent()
        results.append(
            {
                "ordinal": sequence,
                "path": tree.getpath(comment),
                "parent_path": tree.getpath(parent) if parent is not None else None,
                "text": comment.text or "",
                "tail": comment.tail or "",
                "disposition": "represented-as-TEI-comment-or-header-note",
            }
        )
    return results


def validate_tei_bytes(
    source_manifest: SourceManifest, candidate_tei: bytes
) -> Mapping[str, object]:
    """Compare readable TEI bytes with independently traversed retained XML."""
    raw, profile, _policy = _bound_source(source_manifest)
    source_tree = _read(raw)
    observed = _source_facts(source_tree)
    if profile.get("document") != observed:
        raise ValueError(
            "independent source-envelope census differs from the pinned feature profile"
        )
    try:
        candidate_tree = etree.parse(
            BytesIO(candidate_tei),
            etree.XMLParser(
                load_dtd=False,
                no_network=True,
                resolve_entities=False,
                remove_comments=False,
                remove_pis=False,
                remove_blank_text=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is malformed") from exc
    candidate_root = candidate_tree.getroot()
    if (
        candidate_tree.docinfo.doctype
        or candidate_root.getprevious() is not None
        or candidate_root.getnext() is not None
        or candidate_tree.xpath("//processing-instruction()")
    ):
        raise ValueError(
            "candidate TEI copied document-shell declarations or processing instructions"
        )
    expected = _expected_tei(source_tree)
    if _tree_signature(candidate_root) != _tree_signature(expected):
        raise ValueError(
            "candidate TEI differs in source order, wording, hierarchy, attachment, or metadata"
        )
    schema_file = source_manifest.authority_path("tei-schema")
    schema = etree.XMLSchema(
        etree.parse(
            str(schema_file),
            etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False),
        )
    )
    if not schema.validate(candidate_tree):
        raise ValueError(
            f"candidate TEI fails the bound schema: {schema.error_log.last_error}"
        )
    return {
        "status": "pass",
        "source_sha256": SOURCE_SHA256,
        "source_elements": observed["element_count"],
        "source_comments": observed["comment_count"],
        "parent_qualified_selector": FOCUS_SELECTOR,
        "matthew_14_1_21": "explicit-source-gap",
    }


def _import_closure_sha256(repository_root: Path) -> str:
    components = (
        "build/tei/ryle_expository_thoughts_matthew_lib055_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
    )
    files = [
        {"path": item, "sha256": _digest((repository_root / item).read_bytes())}
        for item in components
    ]
    runtime = {
        "lxml": list(etree.LXML_VERSION),
        "libxml2_compiled": list(etree.LIBXML_COMPILED_VERSION),
        "libxml2_runtime": list(etree.LIBXML_VERSION),
        "jsonschema": importlib.metadata.version("jsonschema"),
    }
    return _digest(
        _canonical(
            {
                "contract": "ocd-validator-import-closure-v1",
                "files": files,
                "runtime": runtime,
            }
        )
    )


def _check_accountability(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    tree: etree._ElementTree,
    observed: Mapping[str, object],
) -> None:
    record = _json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    body = tree.getroot().find("ThML.body")
    assert body is not None
    if record.get("contract") != "ocd-source-accountability-v1" or (
        record.get("ticket"),
        record.get("owner_route"),
        record.get("work_id"),
    ) != (TICKET_ID, OWNER_ROUTE, WORK_ID):
        raise ValueError("source-accountability route identity differs")
    if record.get("source_member") != {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
    }:
        raise ValueError(
            "source accountability does not bind the exact retained member"
        )
    if record.get("scope") != _plain(source_manifest.record["scope"]):
        raise ValueError("source-accountability scope differs from the manifest")
    envelope = record.get("source_envelope")
    if (
        not isinstance(envelope, Mapping)
        or envelope.get("profile") != _plain(observed)
        or envelope.get("shell") != observed.get("shell")
        or envelope.get("raw_prolog")
        != _raw_prolog_bytes(_authority_bytes(source_manifest, "source-member"))
    ):
        raise ValueError(
            "source-accountability head/prolog envelope differs from independent evidence"
        )
    if record.get("body_direct_nodes") != _direct_body_facts(body):
        raise ValueError(
            "source-accountability direct body order or comment attachment differs"
        )
    if record.get("elements") != _element_ledger(tree):
        raise ValueError(
            "source-accountability element inventory differs from independent enumeration"
        )
    if record.get("comments") != _comment_ledger(tree):
        raise ValueError(
            "source-accountability comments differ from independent enumeration"
        )
    expected_dispositions = {
        "unrepresented_body_divisions": [],
        "document_shell": "XML declaration, external DOCTYPE, and two stylesheet processing instructions recorded; DTD not fetched or copied.",
        "header": "All elements, attributes, comments, text, tails, and order inventoried; source-record fields are transcribed; provider formatting is accounted but not reproduced.",
        "matthew_14_1_21": "No source-native carrier; gap disclosed in profile, policy, and TEI header; no replacement root invented.",
        "xiv_v": "Represented as a child of the source xiv / Matthew 13 division; never reparented.",
    }
    if record.get("dispositions") != expected_dispositions:
        raise ValueError("source-accountability gap or exclusion disposition differs")
    if record.get("profile_sha256") != _digest(
        _authority_bytes(source_manifest, "feature-profile")
    ) or record.get("policy_sha256") != _digest(
        _authority_bytes(source_manifest, "policy")
    ):
        raise ValueError("source-accountability profile/policy bindings are stale")


def _expected_readme() -> bytes:
    return (
        "# Source attribution\n\n"
        "This source route uses the retained CCEL ThML file `raw/ccel/ryle/matthew.xml`, "
        "sourced via CCEL.org. CCEL permits parsing ThML/XML for text; its copyright applies "
        "to CCEL files and formatting, not the underlying public-domain texts. Do not sell "
        "CCEL files or derivatives of their formatting. This attribution is not a rights "
        "clearance or publication authorization.\n"
    ).encode("utf-8")


def _check_provenance(
    source_manifest: SourceManifest, candidate: CandidatePackage, raw: bytes
) -> None:
    provenance = _json(candidate.member_bytes("provenance.json"), "provenance")
    expected = {
        "contract": "ocd-source-to-tei-provenance-v1",
        "ticket": TICKET_ID,
        "owner_route": OWNER_ROUTE,
        "work_id": WORK_ID,
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(raw),
            "sha256": _digest(raw),
        },
        "source_manifest": {
            "path": source_manifest.path.relative_to(
                source_manifest.repository_root
            ).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "converter": _plain(source_manifest.record["converter"]),
        "feature_profile_sha256": _digest(
            _authority_bytes(source_manifest, "feature-profile")
        ),
        "policy_sha256": _digest(_authority_bytes(source_manifest, "policy")),
        "scope_selector": source_manifest.record["scope"]["selector"],
        "focus_selector": FOCUS_SELECTOR,
        "candidate_status": "nonaccepted",
        "human_acceptance": "not-assessed",
        "publication_status": "not-authorized",
        "notes": "Produced as in-memory route output only; candidate generation and CVW admission remain coordinator work.",
    }
    if provenance != expected:
        raise ValueError("candidate provenance is stale or misbound")


def _check_unresolved(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> None:
    identity = source_manifest.record.get("identity")
    claims = identity.get("unresolved") if isinstance(identity, Mapping) else None
    if not isinstance(claims, Mapping):
        raise ValueError("manifest does not bind unresolved identity claims")
    lines = candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()
    observed = [_json(line.encode("utf-8"), "unresolved claim") for line in lines]
    expected = [
        {"claim": key, "status": "unresolved", "work_id": WORK_ID, "statement": value}
        for key, value in claims.items()
    ]
    if observed != expected:
        raise ValueError("candidate dropped, changed, or reordered an unresolved claim")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    """Verify a coordinator-created package against independent source facts."""
    raw, profile, _policy = _bound_source(source_manifest)
    source_tree = _read(raw)
    observed = _source_facts(source_tree)
    if profile.get("document") != observed:
        raise ValueError("oracle source census differs from the bound feature profile")
    manifest_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    package = _plain(candidate.manifest)
    if (
        not isinstance(package, dict)
        or package.get("status") != "nonaccepted"
        or package.get("source_id") != source_manifest.record.get("source_id")
        or package.get("source_manifest")
        != {"path": manifest_path, "sha256": source_manifest.sha256}
        or package.get("converter") != _plain(source_manifest.record["converter"])
        or package.get("package_schema")
        != _plain(source_manifest.record["package_schema"])
    ):
        raise ValueError("candidate package does not bind the exact nonaccepted route")
    if set(candidate.member_names) != {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }:
        raise ValueError("candidate package members differ from the LIB-055 route")
    if candidate.member_bytes("README.source.md") != _expected_readme():
        raise ValueError(
            "candidate attribution/readme differs from the bound CCEL permission policy"
        )
    _check_accountability(source_manifest, candidate, source_tree, observed)
    _check_provenance(source_manifest, candidate, raw)
    _check_unresolved(source_manifest, candidate)
    validate_tei_bytes(source_manifest, candidate.member_bytes("content.tei.xml"))

    validator = source_manifest.record["validator"]
    source_row = _authority(source_manifest, "source-member")
    profile_row = _authority(source_manifest, "feature-profile")
    package_schema = source_manifest.record["package_schema"]
    schema_row = _authority(source_manifest, "tei-schema")
    policy_row = _authority(source_manifest, "policy")
    facts = MechanicalFacts(
        validator_implementation_sha256=str(validator["implementation_sha256"]),
        validator_import_closure_sha256=_import_closure_sha256(
            source_manifest.repository_root
        ),
        source_sha256=str(source_row["sha256"]),
        profile_sha256=str(profile_row["sha256"]),
        package_schema_sha256=str(package_schema["sha256"]),
        xsd_sha256=str(schema_row["sha256"]),
        policy_sha256=str(policy_row["sha256"]),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
