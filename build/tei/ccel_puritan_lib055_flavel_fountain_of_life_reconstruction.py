"""Work-specific source-to-TEI producer for LIB-055 / 37c-173.

This module is deliberately limited to the retained Fountain of Life ThML
member. Candidate packaging remains the coordinator's responsibility.
"""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from typing import Mapping

from lxml import etree


CONVERTER_ID = "flavel-fountain-of-life-lib055-source-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "flavel-fountain-of-life"
TICKET_ID = "37c-173"
OWNER_ROUTE = "LIB-055"
SOURCE_PATH = "raw/ccel/flavel/fountain.xml"
SOURCE_BYTES = 1_838_431
SOURCE_SHA256 = "111721671b393a9652c1c45df97a51d13b515ba8e899aa9faa0178adaf8c4da1"
MANIFEST_PATH = "sources/structured-text/flavel-fountain-of-life/lib055/37c-173.source-manifest.json"
PROFILE_PATH = (
    "sources/structured-text/flavel-fountain-of-life/lib055/source-feature-profile.json"
)
POLICY_PATH = (
    "sources/structured-text/flavel-fountain-of-life/lib055/validation-policy.json"
)
IDENTITY_PATH = (
    "sources/structured-text/flavel-fountain-of-life/lib055/work-identity.json"
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


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(value: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = item
        return result

    try:
        record = json.loads(value.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be a JSON object")
    return record


def _authority(source_manifest, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    rows = [row for row in authorities if row.get("name") == name]
    if len(rows) != 1:
        raise ValueError(f"source manifest must bind exactly one {name!r} authority")
    return rows[0]


def _authority_bytes(source_manifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _local(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("expected an XML element")
    return etree.QName(node).localname


def _parse(raw: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
        huge_tree=True,
    )
    tree = etree.parse(BytesIO(raw), parser)
    if any(entry.level >= etree.ErrorLevels.ERROR for entry in parser.error_log):
        raise ValueError("retained ThML parser reported an error")
    return tree


def _measure(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    if _local(root) != "ThML" or [
        _local(node) for node in root if isinstance(node.tag, str)
    ] != ["ThML.head", "ThML.body"]:
        raise ValueError("source is not the expected ordered ThML document")
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("source head or body is absent")
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    tags = Counter(_local(node) for node in elements)
    body_tags = Counter(
        _local(node) for node in body.iter() if isinstance(node.tag, str)
    )
    attrs = {
        tag: sorted(
            {name for node in elements if _local(node) == tag for name in node.attrib}
        )
        for tag in sorted(tags)
    }
    attrs = {tag: names for tag, names in attrs.items() if names}
    ids = [node.get("id") for node in elements if node.get("id") is not None]
    divisions = [
        node for node in body if isinstance(node.tag, str) and _local(node) == "div1"
    ]
    main = next((node for node in divisions if node.get("id") == "v"), None)
    indexes = next((node for node in divisions if node.get("id") == "vi"), None)
    if main is None or indexes is None:
        raise ValueError("source main-text or index division is absent")
    links = [
        node.get("href", "")
        for node in body.iter()
        if isinstance(node.tag, str) and _local(node) == "a"
    ]
    fragments = [link.rsplit("#", 1)[1] for link in links if "#" in link]
    id_set = set(ids)
    before: list[etree._Element] = []
    sibling = root.getprevious()
    while sibling is not None:
        before.append(sibling)
        sibling = sibling.getprevious()
    after: list[etree._Element] = []
    sibling = root.getnext()
    while sibling is not None:
        after.append(sibling)
        sibling = sibling.getnext()
    paths = [tree.getpath(node) for node in elements]
    return {
        "root": _local(root),
        "root_attributes": dict(root.attrib),
        "ordered_root_elements": [
            _local(node) for node in root if isinstance(node.tag, str)
        ],
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
            isinstance(node, etree._Comment) for node in before + after
        ),
        "processing_instructions": len(tree.xpath("//processing-instruction()")),
        "post_root_non_whitespace_bytes": int(
            root.tail is not None and bool(root.tail.strip())
        )
        + sum(
            isinstance(node, etree._Element) and isinstance(node.tag, str)
            for node in after
        ),
        "element_count": len(elements),
        "attribute_count": sum(len(node.attrib) for node in elements),
        "element_text_slots": sum(node.text is not None for node in elements),
        "element_tail_slots": sum(node.tail is not None for node in elements),
        "unique_element_paths": len(paths) == len(set(paths)),
        "source_id_count": len(ids),
        "unique_source_id_count": len(id_set),
        "body_direct_div1_ids_in_order": [node.get("id") for node in divisions],
        "body_direct_div1_titles_in_order": [node.get("title") for node in divisions],
        "main_div1_id": main.get("id"),
        "main_div1_direct_div2_ids_in_order": [
            node.get("id")
            for node in main
            if isinstance(node.tag, str) and _local(node) == "div2"
        ],
        "index_div2_ids_in_order": [
            node.get("id")
            for node in indexes
            if isinstance(node.tag, str) and _local(node) == "div2"
        ],
        "source_tag_counts": dict(sorted(tags.items())),
        "body_tag_counts_including_wrapper": dict(sorted(body_tags.items())),
        "source_attribute_names_by_element": attrs,
        "links": {
            "count": len(links),
            "fragment_links": len(fragments),
            "all_fragments_resolve_to_source_ids": all(
                item in id_set for item in fragments
            ),
        },
        "carriers_absent": [
            tag for tag in ("note", "pb", "table", "img") if not tags.get(tag)
        ],
        "member_disposition": "included-in-full",
    }


def _verify_route(
    source_manifest, raw: bytes
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    record = source_manifest.record
    if any(
        record.get(key) != value
        for key, value in (
            ("ticket", TICKET_ID),
            ("owner_route", OWNER_ROUTE),
            ("work_id", WORK_ID),
            ("source_id", "flavel-fountain-of-life-lib055-retained-xml"),
        )
    ):
        raise ValueError("manifest is not the exact LIB-055 / 37c-173 route")
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256:
        raise ValueError(
            "retained Fountain of Life bytes differ from the pinned source member"
        )
    source_record = _authority(source_manifest, "source-member")
    if any(
        source_record.get(key) != value
        for key, value in (
            ("path", SOURCE_PATH),
            ("bytes", SOURCE_BYTES),
            ("sha256", SOURCE_SHA256),
        )
    ):
        raise ValueError("source manifest does not bind the exact retained member")
    if {row.get("name"): row.get("role") for row in record["authorities"]} != _ROLES:
        raise ValueError(
            "manifest authority inventory differs from the work-local LIB-055 route"
        )
    scope = record.get("scope")
    if (
        not isinstance(scope, Mapping)
        or scope.get("selector") != "ThML[1] (complete retained document envelope)"
        or tuple(scope.get("member_order", ())) != (SOURCE_PATH,)
        or scope.get("member_count") != 1
    ):
        raise ValueError("manifest scope is not the complete retained ThML member")
    profile = _strict_json(
        _authority_bytes(source_manifest, "feature-profile"), "source feature profile"
    )
    policy = _strict_json(
        _authority_bytes(source_manifest, "policy"), "validation policy"
    )
    identity = _strict_json(
        _authority_bytes(source_manifest, "work-identity"), "work identity"
    )
    if (
        any(item.get("work_id") != WORK_ID for item in (profile, policy, identity))
        or identity.get("status") != "observed-only"
    ):
        raise ValueError("work-local profile, policy, or identity is misbound")
    if profile.get("source_member") != {
        "path": SOURCE_PATH,
        "bytes": SOURCE_BYTES,
        "sha256": SOURCE_SHA256,
        "format": "CCEL ThML XML",
    }:
        raise ValueError("source feature profile does not bind the exact member")
    policy_scope = policy.get("scope")
    if (
        not isinstance(policy_scope, Mapping)
        or tuple(policy_scope.get("member_order", ())) != (SOURCE_PATH,)
        or policy_scope.get("selector") != scope.get("selector")
        or policy_scope.get("exclusions") != []
    ):
        raise ValueError("validation policy does not account for the complete member")
    permission = _authority_bytes(source_manifest, "ccel-permission").decode("utf-8")
    readme = _authority_bytes(source_manifest, "source-readme")
    if (
        "parsing ThML/XML files for text is explicitly permitted" not in permission
        or "do not sell CCEL files or derivatives of their formatting" not in permission
        or b"sourced via CCEL.org" not in readme
    ):
        raise ValueError("CCEL permission or attribution authority is incomplete")
    expected_identity = {
        "title": "The Fountain of Life Opened Up",
        "creator": "John Flavel",
        "language": "eng",
    }
    if record.get("identity", {}).get("source_record_metadata") != expected_identity:
        raise ValueError(
            "manifest observed metadata differs from the bound source identity"
        )
    return profile, policy, identity


def _profile_check(
    tree: etree._ElementTree, profile: Mapping[str, object]
) -> dict[str, object]:
    measured = _measure(tree)
    if profile.get("document") != measured:
        raise ValueError(
            "retained source envelope differs from the bound feature profile"
        )
    preserve = profile.get("preservation")
    if (
        not isinstance(preserve, Mapping)
        or len(preserve.get("body_divisions", ())) != 6
    ):
        raise ValueError("profile does not account for all six source divisions")
    return measured


def _mapped_attributes(
    source: etree._Element, target: etree._Element, target_name: str
) -> None:
    tag = _local(source)
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
    elif tag in {"h1", "h2", "h3", "h4"}:
        if target_name == "head":
            target.set("type", f"source-{tag}")
        else:
            target.set("rend", f"source-heading-{tag}")
    elif tag == "p":
        if source.get("class") is not None:
            target.set("rend", source.get("class", ""))
    elif tag == "a":
        if source.get("href") is None:
            raise ValueError("source link has no href")
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


def _body_name(source: etree._Element, first_element: bool) -> str:
    tag = _local(source)
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
    }
    if tag in fixed:
        return fixed[tag]
    if tag in {"h1", "h2", "h3", "h4"}:
        return "head" if first_element else "p"
    raise ValueError(f"unsupported Fountain body element {tag!r}")


def _append_body(source: etree._Element, target: etree._Element) -> None:
    target.text = source.text
    first = next((child for child in source if isinstance(child.tag, str)), None)
    for child in source:
        if isinstance(child, etree._Comment):
            mapped = etree.Comment(child.text or "")
        elif isinstance(child.tag, str):
            name = _body_name(child, child is first)
            mapped = etree.Element(f"{{{TEI_NS}}}{name}")
            _mapped_attributes(child, mapped, name)
            if _local(child) in {"scripCom", "insertIndex"}:
                if (child.text or "").strip() or len(child):
                    raise ValueError(
                        f"source marker {_local(child)!r} is no longer empty"
                    )
            else:
                _append_body(child, mapped)
        else:
            raise ValueError(f"unsupported body node in {_local(source)!r}")
        mapped.tail = child.tail
        target.append(mapped)


def _metadata_value(node: etree._Element) -> str:
    return "".join(node.itertext())


def _tei_bytes(tree: etree._ElementTree) -> bytes:
    root = tree.getroot()
    head_source = root.find("ThML.head")
    body_source = root.find("ThML.body")
    if head_source is None or body_source is None:
        raise ValueError("ThML head or body is absent")
    title = head_source.find(".//DC.Title")
    creators = head_source.findall(".//DC.Creator")
    creator = next(
        (node for node in creators if node.get("scheme") == "short-form"), None
    )
    language = head_source.find(".//DC.Language")
    identifier = head_source.find(".//DC.Identifier")
    if any(node is None for node in (title, creator, language, identifier)):
        raise ValueError("required observed source-record metadata is absent")

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
    ).text = "Nonaccepted technical candidate; publication is not authorized."
    notes = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    etree.SubElement(
        notes, f"{{{TEI_NS}}}note", type="source-metadata-boundary"
    ).text = "The header below transcribes retained source-record observations. It does not establish a catalog-work boundary, print edition, original-publication date, translator, parts, witness lineage, or publication rights."
    description = head_source.find(".//description")
    if description is not None:
        note = etree.SubElement(notes, f"{{{TEI_NS}}}note", type="source-description")
        note.text = description.text
        for child in description:
            if not isinstance(child.tag, str):
                raise ValueError("unsupported source description node")
            if _local(child) == "i":
                mapped = etree.SubElement(note, f"{{{TEI_NS}}}hi", rend="italic")
                mapped.text = child.text
            elif _local(child) == "br":
                mapped = etree.SubElement(note, f"{{{TEI_NS}}}lb")
            else:
                raise ValueError(
                    f"unsupported source-description element {_local(child)!r}"
                )
            mapped.tail = child.tail
    for node in head_source.iter():
        if isinstance(node.tag, str) and _local(node).startswith("DC."):
            note = etree.SubElement(
                notes,
                f"{{{TEI_NS}}}note",
                type="source-record-field",
                subtype=_local(node),
            )
            note.set(
                "n",
                json.dumps(
                    dict(node.attrib),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            note.text = _metadata_value(node) or None
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
    project = etree.SubElement(encoding, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(
        project, f"{{{TEI_NS}}}p"
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
    main = etree.SubElement(text, f"{{{TEI_NS}}}body")
    back = etree.SubElement(text, f"{{{TEI_NS}}}back")
    for division in body_source:
        if not isinstance(division.tag, str):
            raise ValueError("unsupported top-level ThML body node")
        if _local(division) != "div1":
            raise ValueError(f"unexpected top-level body carrier {_local(division)!r}")
        destination = (
            front
            if division.get("id") in {"i", "ii", "iii", "iv"}
            else main
            if division.get("id") == "v"
            else back
            if division.get("id") == "vi"
            else None
        )
        if destination is None:
            raise ValueError("unknown top-level Fountain division ID")
        mapped = etree.SubElement(destination, f"{{{TEI_NS}}}div")
        _mapped_attributes(division, mapped, "div")
        _append_body(division, mapped)
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True)


def _element_rows(tree: etree._ElementTree) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
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
                "tag": _local(node),
                "attributes": dict(sorted(node.attrib.items())),
                "text_characters": len(text),
                "text_sha256": _sha(text.encode("utf-8")),
                "tail_characters": len(tail),
                "tail_sha256": _sha(tail.encode("utf-8")),
            }
        )
    return rows


def _shell(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    before: list[dict[str, str]] = []
    sibling = root.getprevious()
    while sibling is not None:
        if isinstance(sibling, etree._Comment):
            before.append({"kind": "comment", "text": sibling.text or ""})
        elif isinstance(sibling, etree._ProcessingInstruction):
            before.append(
                {
                    "kind": "processing-instruction",
                    "text": sibling.text or "",
                    "target": sibling.target,
                }
            )
        sibling = sibling.getprevious()
    before.reverse()
    after: list[dict[str, str]] = []
    sibling = root.getnext()
    while sibling is not None:
        if isinstance(sibling, etree._Comment):
            after.append({"kind": "comment", "text": sibling.text or ""})
        elif isinstance(sibling, etree._ProcessingInstruction):
            after.append(
                {
                    "kind": "processing-instruction",
                    "text": sibling.text or "",
                    "target": sibling.target,
                }
            )
        sibling = sibling.getnext()
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
            "declaration_sha256": _sha(tree.docinfo.doctype.encode("utf-8")),
        },
        "before_root_nodes": before,
        "after_root_nodes": after,
        "root_tail": root.tail,
    }


def _accountability(
    source_manifest, tree: etree._ElementTree, profile: Mapping[str, object]
) -> bytes:
    body = tree.getroot().find("ThML.body")
    assert body is not None
    divisions = []
    for ordinal, node in enumerate(
        (item for item in body if isinstance(item.tag, str)), start=1
    ):
        divisions.append(
            {
                "ordinal": ordinal,
                "path": tree.getpath(node),
                "id": node.get("id"),
                "title": node.get("title"),
                "child_div2_ids": [
                    child.get("id")
                    for child in node
                    if isinstance(child.tag, str) and _local(child) == "div2"
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
            "scope": dict(source_manifest.record["scope"]),
            "source_envelope": {"profile": dict(profile), "shell": _shell(tree)},
            "body_divisions": divisions,
            "elements": _element_rows(tree),
            "dispositions": {
                "unrepresented_body_divisions": [],
                "external_doctype": "recorded-not-fetched-or-copied",
                "xml_declaration_and_outside_root_comment": "recorded-in-shell-accountability",
                "source_header_provider_configuration": "all elements, attributes, text/tails, and positions inventoried; formatting/configuration is not reproduced",
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
            "converter": dict(source_manifest.record["converter"]),
            "feature_profile_sha256": _sha(
                _authority_bytes(source_manifest, "feature-profile")
            ),
            "policy_sha256": _sha(_authority_bytes(source_manifest, "policy")),
            "scope_selector": source_manifest.record["scope"]["selector"],
            "candidate_status": "nonaccepted",
            "human_acceptance": "not-assessed",
            "publication_status": "not-authorized",
            "notes": "Generated only when the coordinator invokes the candidate interface; identity, edition, parts, witness, and rights questions remain unresolved.",
        }
    )


def _unresolved(identity: Mapping[str, object]) -> bytes:
    rows = identity.get("unresolved")
    if not isinstance(rows, Mapping) or not rows:
        raise ValueError("work identity must preserve unresolved claims")
    return b"".join(
        _canonical(
            {
                "claim": key,
                "status": "unresolved",
                "work_id": WORK_ID,
                "statement": value,
            }
        )
        for key, value in rows.items()
    )


def _convert(source_manifest) -> Mapping[str, bytes]:
    """Return source-bound package members in memory; never writes a candidate."""
    source_manifest.verify()
    raw = _authority_bytes(source_manifest, "source-member")
    profile, _policy, identity = _verify_route(source_manifest, raw)
    tree = _parse(raw)
    measured = _profile_check(tree, profile)
    return {
        "README.source.md": _authority_bytes(source_manifest, "source-readme"),
        "content.tei.xml": _tei_bytes(tree),
        "provenance.json": _provenance(source_manifest, raw),
        "source-accountability.json": _accountability(source_manifest, tree, measured),
        "unresolved.jsonl": _unresolved(identity),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
