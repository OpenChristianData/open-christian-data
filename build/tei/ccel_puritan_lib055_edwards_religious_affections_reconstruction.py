"""Work-local TEI producer for LIB-055 / 37c-142."""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree


CONVERTER_ID = "edwards-religious-affections-lib055-source-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "edwards-religious-affections"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SOURCE_LOGICAL_PATH = "raw/ccel/edwards/affections.xml"
PROFILE_NAME = "feature-profile"
POLICY_NAME = "policy"
IDENTITY_NAME = "work-identity"
README_NAME = "source-readme"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(value: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = item
        return result

    try:
        record = json.loads(value.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be a JSON object")
    return record


def _authority_record(source_manifest, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source-manifest authorities are invalid")
    matches = [item for item in authorities if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"source manifest must bind exactly one {name!r} authority")
    return matches[0]


def _authority_bytes(source_manifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _local_name(node: etree._Element) -> str:
    if not isinstance(node.tag, str):
        raise ValueError("expected an XML element")
    return etree.QName(node).localname


def _ordered_siblings(node: etree._Element | None, *, previous: bool) -> list[etree._Element]:
    result: list[etree._Element] = []
    while node is not None:
        result.append(node)
        node = node.getprevious() if previous else node.getnext()
    if previous:
        result.reverse()
    return result


def _document_profile(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    if _local_name(root) != "ThML":
        raise ValueError(f"unexpected retained root {_local_name(root)!r}")
    children = [child for child in root if isinstance(child.tag, str)]
    if [_local_name(child) for child in children] != ["ThML.head", "ThML.body"]:
        raise ValueError("retained ThML root must contain one ordered head/body pair")
    head, body = children
    all_elements = [node for node in root.iter() if isinstance(node.tag, str)]
    head_elements = [node for node in head.iter() if isinstance(node.tag, str)]
    body_elements = [node for node in body.iter() if isinstance(node.tag, str)]
    body_descendants = body_elements[1:]
    top_level = [
        child
        for child in body
        if isinstance(child.tag, str) and _local_name(child) == "div1"
    ]
    prolog = _ordered_siblings(root.getprevious(), previous=True)
    epilog = _ordered_siblings(root.getnext(), previous=False)
    root_comments = [node for node in root.iter() if isinstance(node, etree._Comment)]
    root_pis = [
        node for node in root.iter() if isinstance(node, etree._ProcessingInstruction)
    ]
    prolog_comments = [node for node in prolog if isinstance(node, etree._Comment)]
    epilog_comments = [node for node in epilog if isinstance(node, etree._Comment)]
    all_pis = [
        node
        for node in (*prolog, *root.iter(), *epilog)
        if isinstance(node, etree._ProcessingInstruction)
    ]
    info = tree.docinfo
    return {
        "root": _local_name(root),
        "xml_version": info.xml_version,
        "encoding": info.encoding,
        "doctype": {
            "name": _local_name(root),
            "public_id": info.public_id,
            "system_url": info.system_url,
        },
        "element_count": len(all_elements),
        "head_element_count_including_wrapper": len(head_elements),
        "body_element_count_including_wrapper": len(body_elements),
        "prolog_comment_count": len(prolog_comments),
        "in_root_comment_count": len(root_comments),
        "post_root_comment_count": len(epilog_comments),
        "stylesheet_processing_instruction_count": sum(
            node.target == "xml-stylesheet" for node in all_pis
        ),
        "post_root_processing_instruction_count": sum(
            isinstance(node, etree._ProcessingInstruction) for node in epilog
        ),
        "source_tag_counts": dict(
            sorted(Counter(_local_name(node) for node in all_elements).items())
        ),
        "body_tag_counts_excluding_wrapper": dict(
            sorted(Counter(_local_name(node) for node in body_descendants).items())
        ),
        "top_level_div1_ids": [node.get("id") for node in top_level],
        "top_level_div1_source_titles": [node.get("title") for node in top_level],
    }


def _shell_records(tree: etree._ElementTree) -> list[dict[str, object]]:
    root = tree.getroot()
    prolog = _ordered_siblings(root.getprevious(), previous=True)
    epilog = _ordered_siblings(root.getnext(), previous=False)
    records: list[dict[str, object]] = []
    for location, nodes in (
        ("prolog", prolog),
        ("inside-root", [node for node in root.iter() if not isinstance(node.tag, str)]),
        ("epilog", epilog),
    ):
        for node in nodes:
            if isinstance(node, etree._Comment):
                records.append(
                    {
                        "location": location,
                        "kind": "comment",
                        "source_path": tree.getpath(node),
                        "text": node.text or "",
                    }
                )
            elif isinstance(node, etree._ProcessingInstruction):
                records.append(
                    {
                        "location": location,
                        "kind": "processing-instruction",
                        "source_path": tree.getpath(node),
                        "target": node.target,
                        "text": node.text or "",
                    }
                )
            else:
                raise ValueError(
                    f"unsupported non-element source node at {tree.getpath(node)}"
                )
    return records


def _body_element_name(tag: str) -> str:
    names = {
        "div1": "div",
        "div2": "div",
        "added": "div",
        "div": "div",
        "h1": "head",
        "h2": "head",
        "p": "p",
        "note": "note",
        "scripRef": "ref",
        "a": "ref",
        "i": "hi",
        "span": "hi",
        "scripCom": "anchor",
        "insertIndex": "anchor",
        "br": "lb",
    }
    try:
        return names[tag]
    except KeyError as exc:
        raise ValueError(f"unsupported body element {tag!r}") from exc


def _copy_body_attributes(source: etree._Element, target: etree._Element, tag: str) -> None:
    source_id = source.get("id")
    if source_id is not None:
        target.set(f"{{{XML_NS}}}id", source_id)

    if tag == "div1":
        target.set("type", "source-div1")
    elif tag == "div2":
        target.set("type", "source-div2")
    elif tag == "added":
        target.set("type", "source-added")
    elif tag == "div":
        source_class = source.get("class")
        if source_class is not None:
            target.set("type", source_class)
    elif tag in {"h1", "h2"}:
        target.set("type", f"source-{tag}")
    elif tag == "note":
        for source_name in ("place", "n"):
            if source_name in source.attrib:
                target.set(source_name, source.get(source_name, ""))
    elif tag == "a":
        if source.get("class") is not None:
            target.set("type", source.get("class", ""))
        if source.get("href") is not None:
            target.set("target", source.get("href", ""))
    elif tag == "scripRef":
        target.set("type", "scripture")
        if source.get("osisRef") is not None:
            target.set("target", source.get("osisRef", ""))
        if source.get("passage") is not None:
            target.set("n", source.get("passage", ""))
    elif tag == "scripCom":
        target.set("type", "scripture-commentary-marker")
        if source.get("osisRef") is not None:
            target.set("corresp", source.get("osisRef", ""))
        if source.get("passage") is not None:
            target.set("n", source.get("passage", ""))
    elif tag == "insertIndex":
        target.set("type", "index-insertion")
        if source.get("type") is not None:
            target.set("subtype", source.get("type", ""))
    elif tag == "i":
        target.set("rend", "italic")
    elif tag == "span":
        if source.get("style") is not None:
            target.set("rend", source.get("style", ""))
    elif tag == "p":
        renditions = [
            source.get(name)
            for name in ("class", "style")
            if source.get(name) is not None
        ]
        if renditions:
            target.set("rend", " ; ".join(renditions))


def _append_source_children(
    source: etree._Element,
    target: etree._Element,
    *,
    tree: etree._ElementTree,
) -> None:
    target.text = source.text
    for child in source:
        if isinstance(child, etree._Comment):
            projected = etree.Comment(child.text or "")
        elif isinstance(child, etree._ProcessingInstruction):
            projected = etree.ProcessingInstruction(child.target, child.text or "")
        elif isinstance(child.tag, str):
            tag = _local_name(child)
            target_name = _body_element_name(tag)
            projected = etree.Element(f"{{{TEI_NS}}}{target_name}")
            _copy_body_attributes(child, projected, tag)
            _append_source_children(child, projected, tree=tree)
        else:
            raise ValueError(
                f"unsupported body node at {tree.getpath(child)}"
            )
        projected.tail = child.tail
        target.append(projected)


def _element_inventory(
    tree: etree._ElementTree,
    source_path: str,
) -> list[dict[str, object]]:
    root = tree.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("ThML header or body is absent")
    head_paths = {tree.getpath(node) for node in head.iter() if isinstance(node.tag, str)}
    body_paths = {tree.getpath(node) for node in body.iter() if isinstance(node.tag, str)}
    records: list[dict[str, object]] = []
    for order, node in enumerate(item for item in root.iter() if isinstance(item.tag, str)):
        source_node_path = tree.getpath(node)
        tag = _local_name(node)
        if node is root:
            disposition = "document-root-mapped-to-tei"
            tei_element = "TEI"
        elif source_node_path in head_paths:
            disposition = "header-retained-in-accountability; selected-fields-in-tei-header"
            tei_element = None
        elif source_node_path == tree.getpath(body):
            disposition = "body-wrapper-mapped-to-tei"
            tei_element = "body"
        elif source_node_path in body_paths:
            disposition = "body-element-mapped-to-tei"
            tei_element = _body_element_name(tag)
        else:
            raise ValueError(f"element lies outside the declared envelope: {source_node_path}")
        direct_text = node.text or ""
        tail_text = node.tail or ""
        record: dict[str, object] = {
            "order": order,
            "source_path": source_node_path,
            "parent_source_path": (
                tree.getpath(node.getparent()) if node.getparent() is not None else None
            ),
            "tag": tag,
            "attributes": dict(sorted(node.attrib.items())),
            "direct_text_chars": len(direct_text),
            "direct_text_sha256": _sha(direct_text.encode("utf-8")),
            "tail_text_chars": len(tail_text),
            "tail_text_sha256": _sha(tail_text.encode("utf-8")),
            "disposition": disposition,
            "tei_element": tei_element,
        }
        if source_node_path in head_paths:
            record["source_direct_text"] = node.text
        records.append(record)
    return records


def _provider_values(root: etree._Element) -> dict[str, object]:
    head = root.find("ThML.head")
    if head is None:
        raise ValueError("ThML head is absent")
    values: dict[str, object] = {}
    title = head.find(".//DC.Title")
    creators = head.findall(".//DC.Creator")
    creator = next(
        (
            item
            for item in creators
            if item.get("sub") == "Author" and item.get("scheme") == "short-form"
        ),
        None,
    )
    publisher = head.find(".//DC.Publisher")
    date = head.find(".//DC.Date")
    identifier = head.find(".//DC.Identifier")
    language = head.find(".//DC.Language")
    description = head.find(".//description")
    if any(item is None for item in (title, creator, publisher, date, identifier, language, description)):
        raise ValueError("required provider-record metadata field is absent")
    values["title"] = title.text or ""
    values["creator"] = creator.text or ""
    values["publisher"] = publisher.text or ""
    values["created_date"] = date.text or ""
    values["created_date_subtype"] = date.get("sub")
    values["identifier"] = identifier.text or ""
    values["language"] = language.text or ""
    values["subjects"] = [item.text or "" for item in head.findall(".//DC.Subject")]
    values["description"] = description.text or ""
    return values


def _build_tei(
    tree: etree._ElementTree,
    source_path: str,
    source_bytes: int,
    source_sha256: str,
) -> bytes:
    source_root = tree.getroot()
    values = _provider_values(source_root)
    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    tei_header = etree.SubElement(tei, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(tei_header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title", type="source-record-title").text = values[
        "title"
    ]
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}author").text = values["creator"]
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}publisher").text = values["publisher"]
    etree.SubElement(
        publication,
        f"{{{TEI_NS}}}date",
        type="source-record-created",
        when=values["created_date"],
    ).text = values["created_date"]
    etree.SubElement(publication, f"{{{TEI_NS}}}idno", type="source-record-uri").text = values[
        "identifier"
    ]
    etree.SubElement(publication, f"{{{TEI_NS}}}idno", type="ocd-work-id").text = WORK_ID
    notes_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}notesStmt")
    etree.SubElement(
        notes_stmt,
        f"{{{TEI_NS}}}note",
        type="source-metadata-status",
    ).text = "Provider metadata is transcribed as a source observation; it does not establish a print edition or publication date."
    etree.SubElement(notes_stmt, f"{{{TEI_NS}}}note", type="source-record-description").text = values[
        "description"
    ]
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    etree.SubElement(
        source_desc,
        f"{{{TEI_NS}}}p",
    ).text = (
        f"Retained ThML XML member {source_path}; {source_bytes:,} bytes; "
        f"SHA-256 {source_sha256}. The source record does not resolve edition, part, or physical witness identity."
    )
    encoding_desc = etree.SubElement(tei_header, f"{{{TEI_NS}}}encodingDesc")
    project_desc = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}projectDesc")
    etree.SubElement(
        project_desc,
        f"{{{TEI_NS}}}p",
    ).text = "This is a nonaccepted technical reconstruction. Human acceptance, rights clearance, and publication are separate decisions."
    profile_desc = etree.SubElement(tei_header, f"{{{TEI_NS}}}profileDesc")
    lang_usage = etree.SubElement(profile_desc, f"{{{TEI_NS}}}langUsage")
    etree.SubElement(
        lang_usage,
        f"{{{TEI_NS}}}language",
        ident=values["language"],
    ).text = values["language"]
    text_class = etree.SubElement(profile_desc, f"{{{TEI_NS}}}textClass")
    keywords = etree.SubElement(text_class, f"{{{TEI_NS}}}keywords", scheme="CCEL-DC.Subject")
    for subject in values["subjects"]:
        etree.SubElement(keywords, f"{{{TEI_NS}}}term").text = subject
    text = etree.SubElement(tei, f"{{{TEI_NS}}}text")
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    source_body = source_root.find("ThML.body")
    if source_body is None:
        raise ValueError("ThML body is absent")
    _append_source_children(source_body, body, tree=tree)
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True)


def _source_accountability(
    source_manifest,
    tree: etree._ElementTree,
    raw: bytes,
    profile: Mapping[str, object],
) -> bytes:
    root = tree.getroot()
    profile_record = profile.get("document")
    if not isinstance(profile_record, Mapping):
        raise ValueError("feature profile document census is invalid")
    observed = _document_profile(tree)
    if dict(profile_record) != observed:
        raise ValueError("retained source envelope differs from the bound feature profile")
    envelope = {
        "xml_declaration": {
            "version": tree.docinfo.xml_version,
            "encoding": tree.docinfo.encoding,
            "standalone": tree.docinfo.standalone,
        },
        "doctype": {
            "name": _local_name(root),
            "public_id": tree.docinfo.public_id,
            "system_url": tree.docinfo.system_url,
            "declaration_sha256": _sha(tree.docinfo.doctype.encode("utf-8")),
        },
        "shell_nodes": _shell_records(tree),
        "counts": {
            "elements": observed["element_count"],
            "head_elements_including_wrapper": observed[
                "head_element_count_including_wrapper"
            ],
            "body_elements_including_wrapper": observed[
                "body_element_count_including_wrapper"
            ],
            "comments": (
                observed["prolog_comment_count"]
                + observed["in_root_comment_count"]
                + observed["post_root_comment_count"]
            ),
            "stylesheet_processing_instructions": observed[
                "stylesheet_processing_instruction_count"
            ],
        },
        "document_profile": observed,
    }
    source = _authority_record(source_manifest, "source-affections")
    return _json_bytes(
        {
            "contract": "edwards-religious-affections-source-accountability-v1",
            "work_id": WORK_ID,
            "source_member": {
                "path": source["path"],
                "bytes": len(raw),
                "sha256": _sha(raw),
            },
            "scope": dict(source_manifest.record["scope"]),
            "source_envelope": envelope,
            "elements": _element_inventory(tree, str(source["path"])),
        }
    )


def _provenance(
    source_manifest,
    raw: bytes,
    feature_profile: bytes,
    policy: Mapping[str, object],
) -> bytes:
    source = _authority_record(source_manifest, "source-affections")
    return _json_bytes(
        {
            "contract": "edwards-religious-affections-provenance-v1",
            "status": "nonaccepted",
            "ticket_id": "37c-142",
            "owner_route": "LIB-055",
            "work_id": WORK_ID,
            "source_manifest": {
                "path": source_manifest.path.relative_to(
                    source_manifest.repository_root
                ).as_posix(),
                "sha256": source_manifest.sha256,
            },
            "source_member": {
                "path": source["path"],
                "bytes": len(raw),
                "sha256": _sha(raw),
            },
            "feature_profile_sha256": _sha(feature_profile),
            "unresolved_question_ids": [
                item["question_id"] for item in policy["unresolved_records"]
            ],
            "rights_clearance": "unresolved",
            "human_acceptance": "not-recorded",
            "promotion": "not-authorized",
            "publication": "not-authorized",
        }
    )


def _convert(source_manifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("ticket") != "37c-142":
        raise ValueError("source manifest is not bound to ticket 37c-142")
    if source_manifest.record.get("owner_route") != "LIB-055":
        raise ValueError("source manifest is not owned by LIB-055")
    identity = _strict_json(_authority_bytes(source_manifest, IDENTITY_NAME), "work identity")
    if identity != {
        "contract": "ocd-reconstruction-work-identity-v1",
        "work_id": WORK_ID,
    }:
        raise ValueError("work identity binding does not match 37c-142")
    raw = _authority_bytes(source_manifest, "source-affections")
    source_record = _authority_record(source_manifest, "source-affections")
    if (
        source_record.get("path") != SOURCE_LOGICAL_PATH
        or source_record.get("bytes") != len(raw)
        or source_record.get("sha256") != _sha(raw)
    ):
        raise ValueError("retained Religious Affections source authority drifted")
    profile_bytes = _authority_bytes(source_manifest, PROFILE_NAME)
    profile = _strict_json(profile_bytes, "source feature profile")
    if profile.get("contract") != "edwards-religious-affections-source-feature-profile-v1":
        raise ValueError("source feature profile contract mismatch")
    if profile.get("work_id") != WORK_ID:
        raise ValueError("source feature profile work binding mismatch")
    if profile.get("source_member") != {
        "path": SOURCE_LOGICAL_PATH,
        "bytes": len(raw),
        "sha256": _sha(raw),
    }:
        raise ValueError("source feature profile member binding mismatch")
    policy_bytes = _authority_bytes(source_manifest, POLICY_NAME)
    policy = _strict_json(policy_bytes, "independent-validation policy")
    if (
        policy.get("contract")
        != "edwards-religious-affections-independent-validation-policy-v1"
        or policy.get("work_id") != WORK_ID
    ):
        raise ValueError("independent-validation policy identity mismatch")
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
    )
    tree = etree.parse(BytesIO(raw), parser)
    observed = _document_profile(tree)
    if observed != profile.get("document"):
        raise ValueError("retained source document differs from the feature profile")
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained ThML body is absent")
    for source_node in body.iter():
        if isinstance(source_node.tag, str) and source_node is not body:
            _body_element_name(_local_name(source_node))
    shell = _shell_records(tree)
    if len([item for item in shell if item["kind"] == "comment"]) != 8:
        raise ValueError("source comment census changed")
    if len(
        [
            item
            for item in shell
            if item["kind"] == "processing-instruction"
            and item.get("target") == "xml-stylesheet"
        ]
    ) != 2:
        raise ValueError("source stylesheet processing-instruction census changed")

    readme = _authority_bytes(source_manifest, README_NAME)
    unresolved = policy.get("unresolved_records")
    if not isinstance(unresolved, list) or any(not isinstance(item, dict) for item in unresolved):
        raise ValueError("policy unresolved-record inventory is invalid")
    unresolved_bytes = b"".join(_json_bytes(item) for item in unresolved)
    return {
        "content.tei.xml": _build_tei(
            tree,
            str(source_record["path"]),
            len(raw),
            _sha(raw),
        ),
        "source-accountability.json": _source_accountability(
            source_manifest,
            tree,
            raw,
            profile,
        ),
        "provenance.json": _provenance(
            source_manifest,
            raw,
            profile_bytes,
            policy,
        ),
        "unresolved.jsonl": unresolved_bytes,
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
