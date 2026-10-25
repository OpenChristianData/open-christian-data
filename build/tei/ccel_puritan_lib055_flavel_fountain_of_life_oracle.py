"""Independent retained-source and TEI oracle for LIB-055 / 37c-173.

This checker intentionally does not import the work-local producer or the
legacy CCEL JSON parser. Its source traversal and TEI expectation are local to
this work, while mechanical-fact assembly uses the shared final attestation
seam required by LIB-055.
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


ORACLE_ID = "flavel-fountain-of-life-lib055-independent-retained-source-oracle"
ORACLE_VERSION = "1"
WORK_ID = "flavel-fountain-of-life"
TICKET_ID = "37c-173"
OWNER_ROUTE = "LIB-055"
SOURCE_PATH = "raw/ccel/flavel/fountain.xml"
SOURCE_BYTES = 1_838_431
SOURCE_SHA256 = "111721671b393a9652c1c45df97a51d13b515ba8e899aa9faa0178adaf8c4da1"
PROFILE_PATH = (
    "sources/structured-text/flavel-fountain-of-life/lib055/source-feature-profile.json"
)
POLICY_PATH = (
    "sources/structured-text/flavel-fountain-of-life/lib055/validation-policy.json"
)
README_PATH = "sources/structured-text/flavel-fountain-of-life/lib055/README.source.md"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_ROLES = {
    "source-member": "primary-source",
    "work-identity": "work-config",
    "feature-profile": "complete-source-feature-profile",
    "policy": "independent-validation-policy",
    "source-readme": "source-attribution-readme",
    "ccel-permission": "exact-source-permission",
    "tei-schema": "tei-validation-schema",
    "package-schema": "candidate-package-schema",
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _authority(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    rows = [
        row for row in source_manifest.record["authorities"] if row.get("name") == name
    ]
    if len(rows) != 1:
        raise ValueError(f"oracle requires exactly one {name!r} authority")
    return rows[0]


def _authority_bytes(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _tag(element: etree._Element) -> str:
    if not isinstance(element.tag, str):
        raise ValueError("oracle expected an XML element")
    return etree.QName(element).localname


def _read(raw: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
        huge_tree=True,
    )
    try:
        tree = etree.parse(BytesIO(raw), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("oracle could not parse retained source XML") from exc
    if any(record.level >= etree.ErrorLevels.ERROR for record in parser.error_log):
        raise ValueError("oracle source parser reported an error")
    return tree


def _source_facts(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    top = [child for child in root if isinstance(child.tag, str)]
    if _tag(root) != "ThML" or [_tag(child) for child in top] != [
        "ThML.head",
        "ThML.body",
    ]:
        raise ValueError("oracle source root/head/body order differs")
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("oracle source head or body is missing")
    all_elements = [element for element in root.iter() if isinstance(element.tag, str)]
    body_elements = [element for element in body.iter() if isinstance(element.tag, str)]
    total_by_tag = Counter(_tag(element) for element in all_elements)
    body_by_tag = Counter(_tag(element) for element in body_elements)
    attrs_by_tag: dict[str, list[str]] = {}
    for element in all_elements:
        attrs_by_tag.setdefault(_tag(element), []).extend(element.attrib.keys())
    attrs = {
        tag: sorted(set(names)) for tag, names in sorted(attrs_by_tag.items()) if names
    }
    ids = [
        element.get("id") for element in all_elements if element.get("id") is not None
    ]
    body_roots = [element for element in body if isinstance(element.tag, str)]
    main = next((element for element in body_roots if element.get("id") == "v"), None)
    index = next((element for element in body_roots if element.get("id") == "vi"), None)
    if main is None or index is None:
        raise ValueError("oracle cannot locate expected source divisions")
    hrefs = [
        element.get("href", "")
        for element in body.iter()
        if isinstance(element.tag, str) and _tag(element) == "a"
    ]
    fragments = [href.rsplit("#", 1)[-1] for href in hrefs if "#" in href]
    previous = []
    node = root.getprevious()
    while node is not None:
        previous.append(node)
        node = node.getprevious()
    following = []
    node = root.getnext()
    while node is not None:
        following.append(node)
        node = node.getnext()
    element_paths = [tree.getpath(element) for element in all_elements]
    return {
        "root": _tag(root),
        "root_attributes": dict(root.attrib),
        "ordered_root_elements": [_tag(node) for node in top],
        "doctype": {
            "name": tree.docinfo.root_name,
            "public_id": tree.docinfo.public_id,
            "system_url": tree.docinfo.system_url,
        },
        "xml_declaration": {
            "version": tree.docinfo.xml_version,
            "encoding": tree.docinfo.encoding,
        },
        "outside_root_comments": sum(
            isinstance(node, etree._Comment) for node in previous + following
        ),
        "processing_instructions": len(tree.xpath("//processing-instruction()")),
        "post_root_non_whitespace_bytes": int(bool((root.tail or "").strip()))
        + sum(isinstance(node.tag, str) for node in following),
        "element_count": len(all_elements),
        "attribute_count": sum(len(element.attrib) for element in all_elements),
        "element_text_slots": sum(element.text is not None for element in all_elements),
        "element_tail_slots": sum(element.tail is not None for element in all_elements),
        "unique_element_paths": len(element_paths) == len(set(element_paths)),
        "source_id_count": len(ids),
        "unique_source_id_count": len(set(ids)),
        "body_direct_div1_ids_in_order": [element.get("id") for element in body_roots],
        "body_direct_div1_titles_in_order": [
            element.get("title") for element in body_roots
        ],
        "main_div1_id": main.get("id"),
        "main_div1_direct_div2_ids_in_order": [
            child.get("id")
            for child in main
            if isinstance(child.tag, str) and _tag(child) == "div2"
        ],
        "index_div2_ids_in_order": [
            child.get("id")
            for child in index
            if isinstance(child.tag, str) and _tag(child) == "div2"
        ],
        "source_tag_counts": dict(sorted(total_by_tag.items())),
        "body_tag_counts_including_wrapper": dict(sorted(body_by_tag.items())),
        "source_attribute_names_by_element": attrs,
        "links": {
            "count": len(hrefs),
            "fragment_links": len(fragments),
            "all_fragments_resolve_to_source_ids": all(
                fragment in set(ids) for fragment in fragments
            ),
        },
        "carriers_absent": [
            tag for tag in ("note", "pb", "table", "img") if tag not in total_by_tag
        ],
        "member_disposition": "included-in-full",
    }


def _bound_source(
    source_manifest: SourceManifest,
) -> tuple[bytes, dict[str, object], dict[str, object]]:
    row = source_manifest.record
    if any(
        row.get(key) != value
        for key, value in (
            ("ticket", TICKET_ID),
            ("owner_route", OWNER_ROUTE),
            ("work_id", WORK_ID),
            ("source_id", "flavel-fountain-of-life-lib055-retained-xml"),
        )
    ):
        raise ValueError("oracle received another work, ticket, or owner route")
    if {item.get("name"): item.get("role") for item in row["authorities"]} != _ROLES:
        raise ValueError(
            "oracle manifest authorities are missing, extra, or misclassified"
        )
    member = _authority(source_manifest, "source-member")
    if any(
        member.get(key) != value
        for key, value in (
            ("path", SOURCE_PATH),
            ("bytes", SOURCE_BYTES),
            ("sha256", SOURCE_SHA256),
        )
    ):
        raise ValueError(
            "oracle source-member authority is not the exact Fountain member"
        )
    raw = _authority_bytes(source_manifest, "source-member")
    if len(raw) != SOURCE_BYTES or _digest(raw) != SOURCE_SHA256:
        raise ValueError("oracle retained source bytes do not match the current claim")
    scope = row.get("scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("selector") != "ThML[1] (complete retained document envelope)"
        or tuple(scope.get("member_order", ())) != (SOURCE_PATH,)
        or scope.get("member_count") != 1
    ):
        raise ValueError("oracle scope is not the complete retained source member")
    profile = _json(
        _authority_bytes(source_manifest, "feature-profile"), "feature profile"
    )
    policy = _json(_authority_bytes(source_manifest, "policy"), "validation policy")
    if any(item.get("work_id") != WORK_ID for item in (profile, policy)):
        raise ValueError("oracle profile or policy belongs to another work")
    if profile.get("source_member", {}).get("sha256") != SOURCE_SHA256:
        raise ValueError("oracle feature profile does not bind the exact source hash")
    rules = policy.get("scope")
    if (
        not isinstance(rules, Mapping)
        or tuple(rules.get("member_order", ())) != (SOURCE_PATH,)
        or rules.get("exclusions") != []
    ):
        raise ValueError("oracle policy excludes material from the declared envelope")
    permission = _authority_bytes(source_manifest, "ccel-permission").decode("utf-8")
    if (
        "parsing ThML/XML files for text is explicitly permitted" not in permission
        or "do not sell CCEL files or derivatives of their formatting" not in permission
    ):
        raise ValueError("oracle lacks the exact CCEL permission statement")
    if b"sourced via CCEL.org" not in _authority_bytes(
        source_manifest, "source-readme"
    ):
        raise ValueError("oracle lacks the source attribution README")
    return raw, profile, policy


def _new_tei(tag: str, **attributes: str) -> etree._Element:
    return etree.Element(f"{{{TEI_NS}}}{tag}", attrib=attributes)


def _expected_attributes(source: etree._Element, mapped_name: str) -> dict[str, str]:
    tag = _tag(source)
    result: dict[str, str] = {}
    source_id = source.get("id")
    if source_id is not None:
        result[f"{{{XML_NS}}}id"] = source_id
    if tag in ("div1", "div2", "div"):
        result["type"] = "source-" + tag
        if source.get("title") is not None:
            result["n"] = source.get("title", "")
        if source.get("class") is not None:
            result["subtype"] = source.get("class", "")
        for pointer in ("prev", "next"):
            if pointer in source.attrib:
                result[pointer] = source.get(pointer, "")
    elif tag.startswith("h") and tag[1:] in {"1", "2", "3", "4"}:
        result["type" if mapped_name == "head" else "rend"] = (
            f"source-{tag}" if mapped_name == "head" else f"source-heading-{tag}"
        )
    elif tag == "p" and source.get("class") is not None:
        result["rend"] = source.get("class", "")
    elif tag == "a":
        result["target"] = source.get("href", "")
        if source.get("class") is not None:
            result["type"] = source.get("class", "")
    elif tag == "scripRef":
        result["type"] = "scripture"
        if "osisRef" in source.attrib:
            result["target"] = source.get("osisRef", "")
        if "passage" in source.attrib:
            result["n"] = source.get("passage", "")
    elif tag == "scripCom":
        result["type"] = "scripture-commentary-marker"
        if "type" in source.attrib:
            result["subtype"] = source.get("type", "")
        if "osisRef" in source.attrib:
            result["corresp"] = source.get("osisRef", "")
        if "passage" in source.attrib:
            result["n"] = source.get("passage", "")
    elif tag == "insertIndex":
        result["type"] = "index-insertion"
        if "type" in source.attrib:
            result["subtype"] = source.get("type", "")
    return result


def _mapped_tag(source: etree._Element, is_first: bool) -> str:
    name = _tag(source)
    names = {
        "div1": "div",
        "div2": "div",
        "div": "div",
        "p": "p",
        "a": "ref",
        "scripRef": "ref",
        "scripCom": "anchor",
        "insertIndex": "anchor",
        "br": "lb",
    }
    if name in names:
        return names[name]
    if name in {"h1", "h2", "h3", "h4"}:
        return "head" if is_first else "p"
    raise ValueError(f"oracle has no approved mapping for source element {name!r}")


def _copy_expected_body(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    first_element = next(
        (child for child in source if isinstance(child.tag, str)), None
    )
    for child in source:
        if isinstance(child, etree._Comment):
            output = etree.Comment(child.text or "")
        elif isinstance(child.tag, str):
            name = _mapped_tag(child, child is first_element)
            output = _new_tei(name)
            for key, value in _expected_attributes(child, name).items():
                output.set(key, value)
            if _tag(child) in {"scripCom", "insertIndex"} and (
                (child.text or "").strip() or len(child)
            ):
                raise ValueError("oracle rejects content under an empty source marker")
            if _tag(child) not in {"scripCom", "insertIndex"}:
                _copy_expected_body(child, output)
        else:
            raise ValueError("oracle encountered an unsupported source node")
        output.tail = child.tail
        target.append(output)


def _expected_tei(tree: etree._ElementTree) -> etree._Element:
    root = tree.getroot()
    head_src = root.find("ThML.head")
    body_src = root.find("ThML.body")
    assert head_src is not None and body_src is not None
    title = head_src.find(".//DC.Title")
    creator = next(
        (
            item
            for item in head_src.findall(".//DC.Creator")
            if item.get("scheme") == "short-form"
        ),
        None,
    )
    language = head_src.find(".//DC.Language")
    identifier = head_src.find(".//DC.Identifier")
    assert (
        title is not None
        and creator is not None
        and language is not None
        and identifier is not None
    )
    tei = _new_tei("TEI")
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
    ).text = "Nonaccepted technical candidate; publication is not authorized."
    notes = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    etree.SubElement(
        notes, f"{{{TEI_NS}}}note", type="source-metadata-boundary"
    ).text = "The header below transcribes retained source-record observations. It does not establish a catalog-work boundary, print edition, original-publication date, translator, parts, witness lineage, or publication rights."
    description = head_src.find(".//description")
    if description is not None:
        desc_note = etree.SubElement(
            notes, f"{{{TEI_NS}}}note", type="source-description"
        )
        desc_note.text = description.text
        for child in description:
            if _tag(child) == "i":
                mapped = etree.SubElement(desc_note, f"{{{TEI_NS}}}hi", rend="italic")
                mapped.text = child.text
            elif _tag(child) == "br":
                mapped = etree.SubElement(desc_note, f"{{{TEI_NS}}}lb")
            else:
                raise ValueError(
                    "oracle source description has an unsupported inline carrier"
                )
            mapped.tail = child.tail
    for field in head_src.iter():
        if isinstance(field.tag, str) and _tag(field).startswith("DC."):
            note = etree.SubElement(
                notes,
                f"{{{TEI_NS}}}note",
                type="source-record-field",
                subtype=_tag(field),
            )
            note.set(
                "n",
                json.dumps(
                    dict(field.attrib),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            note.text = "".join(field.itertext()) or None
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    bibl = etree.SubElement(
        source_desc, f"{{{TEI_NS}}}bibl", type="retained-source-record"
    )
    etree.SubElement(bibl, f"{{{TEI_NS}}}title", type="source-record-title").text = (
        title.text or ""
    )
    etree.SubElement(bibl, f"{{{TEI_NS}}}author").text = creator.text or ""
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="source-record-uri").text = (
        identifier.text or ""
    )
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="ocd-work-id").text = WORK_ID
    etree.SubElement(
        bibl, f"{{{TEI_NS}}}note", type="source-member-binding"
    ).text = f"Complete retained document envelope at {SOURCE_PATH}; {SOURCE_BYTES} bytes; SHA-256 {SOURCE_SHA256}."
    etree.SubElement(
        bibl, f"{{{TEI_NS}}}note", type="identity-limit"
    ).text = "This source-member identity binding does not assert that the member proves the full catalog work or a specific print edition."
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    description_node = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(
        description_node, f"{{{TEI_NS}}}p"
    ).text = "The complete retained ThML body is mapped in source order. The XML shell and provider formatting are inventoried separately and are not copied as TEI markup."
    profile = etree.SubElement(header, f"{{{TEI_NS}}}profileDesc")
    usage = etree.SubElement(profile, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(usage, f"{{{TEI_NS}}}language", ident=language.text or "").text = (
        language.text or ""
    )
    text = etree.SubElement(
        tei, f"{{{TEI_NS}}}text", {f"{{{XML_NS}}}lang": language.text or ""}
    )
    front = etree.SubElement(text, f"{{{TEI_NS}}}front")
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    back = etree.SubElement(text, f"{{{TEI_NS}}}back")
    groups = {"i": front, "ii": front, "iii": front, "iv": front, "v": body, "vi": back}
    for division in body_src:
        if (
            not isinstance(division.tag, str)
            or _tag(division) != "div1"
            or division.get("id") not in groups
        ):
            raise ValueError(
                "oracle encountered a top-level source division outside the declared six"
            )
        mapped = etree.SubElement(groups[division.get("id")], f"{{{TEI_NS}}}div")
        for key, value in _expected_attributes(division, "div").items():
            mapped.set(key, value)
        _copy_expected_body(division, mapped)
    return tei


def _signature(node: etree._Element) -> object:
    if isinstance(node, etree._Comment):
        return ("comment", node.text, node.tail)
    if not isinstance(node.tag, str):
        raise ValueError("oracle TEI contains an unsupported node kind")
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text,
        tuple(_signature(child) for child in node),
        node.tail,
    )


def validate_tei_bytes(
    source_manifest: SourceManifest, candidate_tei: bytes
) -> Mapping[str, object]:
    """Compare an in-memory TEI member to expectations derived from source bytes."""
    raw, profile, _policy = _bound_source(source_manifest)
    source_tree = _read(raw)
    measured = _source_facts(source_tree)
    if profile.get("document") != measured:
        raise ValueError("oracle source envelope census differs from the bound profile")
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
        raise ValueError("candidate TEI contains copied document-shell syntax")
    expected = _expected_tei(source_tree)
    if _signature(candidate_root) != _signature(expected):
        raise ValueError(
            "candidate TEI differs from source-derived order, content, attachment, or attributes"
        )
    schema_path = source_manifest.authority_path("tei-schema")
    schema_parser = etree.XMLParser(
        load_dtd=False, no_network=True, resolve_entities=False
    )
    schema = etree.XMLSchema(etree.parse(str(schema_path), schema_parser))
    if not schema.validate(candidate_tree):
        error = schema.error_log.last_error
        raise ValueError(f"candidate TEI fails the bound TEI P5 schema: {error}")
    return {
        "status": "pass",
        "source_sha256": SOURCE_SHA256,
        "source_elements": measured["element_count"],
        "top_level_divisions": measured["body_direct_div1_ids_in_order"],
    }


def _element_inventory(tree: etree._ElementTree) -> list[dict[str, object]]:
    result = []
    for index, element in enumerate(
        (item for item in tree.getroot().iter() if isinstance(item.tag, str)), start=1
    ):
        text, tail = element.text or "", element.tail or ""
        result.append(
            {
                "ordinal": index,
                "path": tree.getpath(element),
                "parent_path": tree.getpath(element.getparent())
                if element.getparent() is not None
                else None,
                "tag": _tag(element),
                "attributes": dict(sorted(element.attrib.items())),
                "text_characters": len(text),
                "text_sha256": _digest(text.encode("utf-8")),
                "tail_characters": len(tail),
                "tail_sha256": _digest(tail.encode("utf-8")),
            }
        )
    return result


def _shell_inventory(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()

    def siblings(first: etree._Element | None) -> list[dict[str, str]]:
        items = []
        node = first
        while node is not None:
            if isinstance(node, etree._Comment):
                items.append({"kind": "comment", "text": node.text or ""})
            elif isinstance(node, etree._ProcessingInstruction):
                items.append(
                    {
                        "kind": "processing-instruction",
                        "text": node.text or "",
                        "target": node.target,
                    }
                )
            node = node.getnext()
        return items

    prior = []
    node = root.getprevious()
    while node is not None:
        prior.append(node)
        node = node.getprevious()
    prior.reverse()
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
            "declaration_sha256": _digest(tree.docinfo.doctype.encode("utf-8")),
        },
        "before_root_nodes": siblings(prior[0] if prior else None),
        "after_root_nodes": siblings(root.getnext()),
        "root_tail": root.tail,
    }


def _expected_accountability(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    profile: Mapping[str, object],
) -> bytes:
    body = tree.getroot().find("ThML.body")
    assert body is not None
    divisions = []
    for number, node in enumerate(
        (child for child in body if isinstance(child.tag, str)), start=1
    ):
        divisions.append(
            {
                "ordinal": number,
                "path": tree.getpath(node),
                "id": node.get("id"),
                "title": node.get("title"),
                "child_div2_ids": [
                    child.get("id")
                    for child in node
                    if isinstance(child.tag, str) and _tag(child) == "div2"
                ],
                "disposition": "represented-in-TEI",
            }
        )
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
                "profile": dict(profile),
                "shell": _shell_inventory(tree),
            },
            "body_divisions": divisions,
            "elements": _element_inventory(tree),
            "dispositions": {
                "unrepresented_body_divisions": [],
                "external_doctype": "recorded-not-fetched-or-copied",
                "xml_declaration_and_outside_root_comment": "recorded-in-shell-accountability",
                "source_header_provider_configuration": "all elements, attributes, text/tails, and positions inventoried; formatting/configuration is not reproduced",
            },
            "profile_sha256": _digest(
                _authority_bytes(source_manifest, "feature-profile")
            ),
            "policy_sha256": _digest(_authority_bytes(source_manifest, "policy")),
        }
    )


def _expected_provenance(source_manifest: SourceManifest, raw: bytes) -> bytes:
    return _canonical(
        {
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
            "candidate_status": "nonaccepted",
            "human_acceptance": "not-assessed",
            "publication_status": "not-authorized",
            "notes": "Generated only when the coordinator invokes the candidate interface; identity, edition, parts, witness, and rights questions remain unresolved.",
        }
    )


def _expected_unresolved(source_manifest: SourceManifest) -> bytes:
    identity = _json(
        _authority_bytes(source_manifest, "work-identity"), "work identity"
    )
    claims = identity.get("unresolved")
    if not isinstance(claims, Mapping) or not claims:
        raise ValueError("oracle found no work-local unresolved-claim inventory")
    return b"".join(
        _canonical(
            {
                "claim": key,
                "status": "unresolved",
                "work_id": WORK_ID,
                "statement": value,
            }
        )
        for key, value in claims.items()
    )


def _import_closure_sha256(repository_root: Path) -> str:
    logical = (
        "build/tei/ccel_puritan_lib055_flavel_fountain_of_life_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
    )
    files = [
        {"path": path, "sha256": _digest((repository_root / path).read_bytes())}
        for path in logical
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


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    """Validate a coordinator-generated candidate against independent source expectations."""
    source_manifest.verify()
    candidate.verify_integrity()
    raw, profile, _policy = _bound_source(source_manifest)
    source_tree = _read(raw)
    measured = _source_facts(source_tree)
    if profile.get("document") != measured:
        raise ValueError("oracle source census differs from the pinned profile")
    package = _plain(candidate.manifest)
    manifest_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
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
        raise ValueError(
            "candidate package does not bind the exact nonaccepted work route"
        )
    expected_members = {
        "README.source.md",
        "content.tei.xml",
        "manifest.json",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    if set(candidate.member_names) != expected_members:
        raise ValueError(
            "candidate package members differ from the complete route contract"
        )
    if candidate.member_bytes("README.source.md") != _authority_bytes(
        source_manifest, "source-readme"
    ):
        raise ValueError(
            "candidate source attribution README differs from its bound authority"
        )
    if candidate.member_bytes("source-accountability.json") != _expected_accountability(
        source_manifest, source_tree, measured
    ):
        raise ValueError(
            "candidate accounting does not reconcile to independent source enumeration"
        )
    if candidate.member_bytes("provenance.json") != _expected_provenance(
        source_manifest, raw
    ):
        raise ValueError(
            "candidate provenance does not bind source and route authorities"
        )
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved(
        source_manifest
    ):
        raise ValueError("candidate dropped an unresolved identity or rights claim")
    validate_tei_bytes(source_manifest, candidate.member_bytes("content.tei.xml"))
    validator = source_manifest.record["validator"]
    source_row = _authority(source_manifest, "source-member")
    profile_row = _authority(source_manifest, "feature-profile")
    package_schema = source_manifest.record["package_schema"]
    xsd = _authority(source_manifest, "tei-schema")
    policy_row = _authority(source_manifest, "policy")
    facts = MechanicalFacts(
        validator_implementation_sha256=str(validator["implementation_sha256"]),
        validator_import_closure_sha256=_import_closure_sha256(
            source_manifest.repository_root
        ),
        source_sha256=str(source_row["sha256"]),
        profile_sha256=str(profile_row["sha256"]),
        package_schema_sha256=str(package_schema["sha256"]),
        xsd_sha256=str(xsd["sha256"]),
        policy_sha256=str(policy_row["sha256"]),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
