"""Independent retained-byte reader for LIB-055 / 37c-142."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
from io import BytesIO
import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "edwards-religious-affections-independent-retained-byte-oracle"
ORACLE_VERSION = "1"
WORK_ID = "edwards-religious-affections"
SOURCE_PATH = "raw/ccel/edwards/affections.xml"
SOURCE_SHA256 = "2ffd4300ada5d0cc5b3929ed5b61ed0e1053042a065419ee35943facc79738ce"
SOURCE_BYTES = 1_183_960
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"tei": TEI_NS}
EXPECTED_DIVISION_IDS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii")
EXPECTED_ELEMENT_COUNT = 3420
EXPECTED_BODY_COUNT = 3373
EXPECTED_COMMENT_COUNT = 8
EXPECTED_STYLESHEET_PI_COUNT = 2
EXPECTED_UNRESOLVED_IDS = (
    "work-boundary",
    "textual-form-and-translation",
    "edition-and-date",
    "parts-and-source-structure",
    "witness-relationship",
    "rights-clearance",
)
_TEI_ELEMENT_BY_SOURCE_NAME = {
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
_EXPECTED_SOURCE_TAG_COUNTS = {
    "DC": 1,
    "DC.Creator": 2,
    "DC.Date": 1,
    "DC.Format": 1,
    "DC.Identifier": 1,
    "DC.Language": 1,
    "DC.Publisher": 1,
    "DC.Rights": 1,
    "DC.Source": 2,
    "DC.Subject": 7,
    "DC.Title": 1,
    "DC.Type": 1,
    "ThML": 1,
    "ThML.body": 1,
    "ThML.head": 1,
    "a": 1129,
    "added": 1,
    "authorID": 1,
    "bkgID": 1,
    "bookID": 1,
    "br": 3,
    "comments": 1,
    "description": 1,
    "div": 1,
    "div1": 8,
    "div2": 24,
    "electronicEdInfo": 1,
    "generalInfo": 1,
    "h1": 1,
    "h2": 2,
    "i": 179,
    "insertIndex": 1,
    "note": 86,
    "p": 876,
    "printSourceInfo": 1,
    "property": 4,
    "pubHistory": 1,
    "published": 1,
    "publisherID": 1,
    "scripCom": 1,
    "scripRef": 1048,
    "selector": 2,
    "series": 1,
    "span": 15,
    "style": 2,
    "version": 1,
    "workID": 1,
}
_EXPECTED_BODY_TAG_COUNTS = {
    "a": 1129,
    "added": 1,
    "div": 1,
    "div1": 8,
    "div2": 24,
    "h1": 1,
    "h2": 2,
    "i": 179,
    "insertIndex": 1,
    "note": 86,
    "p": 876,
    "scripCom": 1,
    "scripRef": 1048,
    "span": 15,
}


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
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
        raise ValueError(f"{label} must be an object")
    return record


def _bound_authority(source_manifest, name: str):
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("manifest authority inventory is invalid")
    result = [entry for entry in authorities if entry.get("name") == name]
    if len(result) != 1:
        raise ValueError(f"manifest does not bind one {name!r} authority")
    return result[0]


def _tag(element: etree._Element) -> str:
    if not isinstance(element.tag, str):
        raise ValueError("element inventory encountered a non-element")
    return etree.QName(element).localname


def _walk(element: etree._Element):
    if isinstance(element.tag, str):
        yield element
    for child in element:
        if isinstance(child.tag, str):
            yield from _walk(child)


def _previous_siblings(node: etree._Element | None) -> list[etree._Element]:
    result: list[etree._Element] = []
    while node is not None:
        result.append(node)
        node = node.getprevious()
    return list(reversed(result))


def _next_siblings(node: etree._Element | None) -> list[etree._Element]:
    result: list[etree._Element] = []
    while node is not None:
        result.append(node)
        node = node.getnext()
    return result


def _tree_nodes(root: etree._Element):
    yield root
    for child in root:
        if isinstance(child.tag, str):
            yield from _tree_nodes(child)
        elif isinstance(child, etree._Comment) or isinstance(
            child, etree._ProcessingInstruction
        ):
            yield child
        else:
            raise ValueError("source contains an unsupported in-root node")


def _shell(tree: etree._ElementTree) -> list[dict[str, object]]:
    root = tree.getroot()
    groups = (
        ("prolog", _previous_siblings(root.getprevious())),
        ("inside-root", [node for node in _tree_nodes(root) if not isinstance(node.tag, str)]),
        ("epilog", _next_siblings(root.getnext())),
    )
    output: list[dict[str, object]] = []
    for place, nodes in groups:
        for node in nodes:
            if isinstance(node, etree._Comment):
                output.append(
                    {
                        "location": place,
                        "kind": "comment",
                        "source_path": tree.getpath(node),
                        "text": node.text or "",
                    }
                )
            elif isinstance(node, etree._ProcessingInstruction):
                output.append(
                    {
                        "location": place,
                        "kind": "processing-instruction",
                        "source_path": tree.getpath(node),
                        "target": node.target,
                        "text": node.text or "",
                    }
                )
            else:
                raise ValueError("source shell contains an unsupported node")
    return output


def _independent_profile(tree: etree._ElementTree) -> dict[str, object]:
    root = tree.getroot()
    children = [element for element in root if isinstance(element.tag, str)]
    if len(children) != 2 or [_tag(item) for item in children] != ["ThML.head", "ThML.body"]:
        raise ValueError("the retained ThML head/body envelope changed")
    head, body = children
    all_nodes = list(_walk(root))
    head_nodes = list(_walk(head))
    body_nodes = list(_walk(body))
    body_content = body_nodes[1:]
    ordered_roots = [child for child in body if isinstance(child.tag, str)]
    before = _previous_siblings(root.getprevious())
    after = _next_siblings(root.getnext())
    inside_comments = [
        item for item in _tree_nodes(root) if isinstance(item, etree._Comment)
    ]
    all_pis = [
        item
        for item in (*before, *_tree_nodes(root), *after)
        if isinstance(item, etree._ProcessingInstruction)
    ]
    profile = {
        "root": _tag(root),
        "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "doctype": {
            "name": _tag(root),
            "public_id": tree.docinfo.public_id,
            "system_url": tree.docinfo.system_url,
        },
        "element_count": len(all_nodes),
        "head_element_count_including_wrapper": len(head_nodes),
        "body_element_count_including_wrapper": len(body_nodes),
        "prolog_comment_count": sum(isinstance(item, etree._Comment) for item in before),
        "in_root_comment_count": len(inside_comments),
        "post_root_comment_count": sum(isinstance(item, etree._Comment) for item in after),
        "stylesheet_processing_instruction_count": sum(
            item.target == "xml-stylesheet" for item in all_pis
        ),
        "post_root_processing_instruction_count": sum(
            isinstance(item, etree._ProcessingInstruction) for item in after
        ),
        "source_tag_counts": dict(
            sorted(Counter(_tag(item) for item in all_nodes).items())
        ),
        "body_tag_counts_excluding_wrapper": dict(
            sorted(Counter(_tag(item) for item in body_content).items())
        ),
        "top_level_div1_ids": [item.get("id") for item in ordered_roots],
        "top_level_div1_source_titles": [item.get("title") for item in ordered_roots],
    }
    if profile["element_count"] != EXPECTED_ELEMENT_COUNT:
        raise ValueError("retained source element count changed")
    if profile["body_element_count_including_wrapper"] != EXPECTED_BODY_COUNT:
        raise ValueError("retained ThML body element count changed")
    if profile["source_tag_counts"] != _EXPECTED_SOURCE_TAG_COUNTS:
        raise ValueError("retained source tag census changed")
    if profile["body_tag_counts_excluding_wrapper"] != _EXPECTED_BODY_TAG_COUNTS:
        raise ValueError("retained body tag census changed")
    if tuple(profile["top_level_div1_ids"]) != EXPECTED_DIVISION_IDS:
        raise ValueError("top-level source division identities or order changed")
    if profile["doctype"] != {
        "name": "ThML",
        "public_id": "-//CCEL/DTD Theological Markup Language//EN",
        "system_url": "http://www.ccel.org/dtd/ThML10.dtd",
    }:
        raise ValueError("retained document DOCTYPE changed")
    if profile["prolog_comment_count"] + profile["in_root_comment_count"] + profile[
        "post_root_comment_count"
    ] != EXPECTED_COMMENT_COUNT:
        raise ValueError("retained source comment census changed")
    if profile["stylesheet_processing_instruction_count"] != EXPECTED_STYLESHEET_PI_COUNT:
        raise ValueError("retained stylesheet processing-instruction census changed")
    return profile


def _accounted_elements(tree: etree._ElementTree) -> list[dict[str, object]]:
    root = tree.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    if head is None or body is None:
        raise ValueError("source header or body is absent")
    head_paths = {tree.getpath(item) for item in _walk(head)}
    body_path = tree.getpath(body)
    body_paths = {tree.getpath(item) for item in _walk(body)}
    rows: list[dict[str, object]] = []
    for index, node in enumerate(_walk(root)):
        path = tree.getpath(node)
        name = _tag(node)
        if node is root:
            disposition, target_name = "document-root-mapped-to-tei", "TEI"
        elif path in head_paths:
            disposition, target_name = (
                "header-retained-in-accountability; selected-fields-in-tei-header",
                None,
            )
        elif path == body_path:
            disposition, target_name = "body-wrapper-mapped-to-tei", "body"
        elif path in body_paths:
            try:
                target_name = _TEI_ELEMENT_BY_SOURCE_NAME[name]
            except KeyError as exc:
                raise ValueError(f"source body element {name!r} has no TEI disposition") from exc
            disposition = "body-element-mapped-to-tei"
        else:
            raise ValueError(f"source element outside the pinned envelope at {path}")
        direct = node.text or ""
        tail = node.tail or ""
        row: dict[str, object] = {
            "order": index,
            "source_path": path,
            "parent_source_path": (
                tree.getpath(node.getparent()) if node.getparent() is not None else None
            ),
            "tag": name,
            "attributes": dict(sorted(node.attrib.items())),
            "direct_text_chars": len(direct),
            "direct_text_sha256": _sha(direct.encode("utf-8")),
            "tail_text_chars": len(tail),
            "tail_text_sha256": _sha(tail.encode("utf-8")),
            "disposition": disposition,
            "tei_element": target_name,
        }
        if path in head_paths:
            row["source_direct_text"] = node.text
        rows.append(row)
    return rows


def _tei_name(tag: str) -> str:
    try:
        return _TEI_ELEMENT_BY_SOURCE_NAME[tag]
    except KeyError as exc:
        raise ValueError(f"unsupported retained body carrier {tag!r}") from exc


def _expected_attributes(source: etree._Element, tag: str) -> dict[str, str]:
    actual: dict[str, str] = {}
    if source.get("id") is not None:
        actual[f"{{{XML_NS}}}id"] = source.get("id", "")
    if tag == "div1":
        actual["type"] = "source-div1"
    elif tag == "div2":
        actual["type"] = "source-div2"
    elif tag == "added":
        actual["type"] = "source-added"
    elif tag == "div" and source.get("class") is not None:
        actual["type"] = source.get("class", "")
    elif tag in {"h1", "h2"}:
        actual["type"] = f"source-{tag}"
    elif tag == "note":
        for field in ("place", "n"):
            if field in source.attrib:
                actual[field] = source.get(field, "")
    elif tag == "a":
        if source.get("class") is not None:
            actual["type"] = source.get("class", "")
        if source.get("href") is not None:
            actual["target"] = source.get("href", "")
    elif tag == "scripRef":
        actual["type"] = "scripture"
        if source.get("osisRef") is not None:
            actual["target"] = source.get("osisRef", "")
        if source.get("passage") is not None:
            actual["n"] = source.get("passage", "")
    elif tag == "scripCom":
        actual["type"] = "scripture-commentary-marker"
        if source.get("osisRef") is not None:
            actual["corresp"] = source.get("osisRef", "")
        if source.get("passage") is not None:
            actual["n"] = source.get("passage", "")
    elif tag == "insertIndex":
        actual["type"] = "index-insertion"
        if source.get("type") is not None:
            actual["subtype"] = source.get("type", "")
    elif tag == "i":
        actual["rend"] = "italic"
    elif tag == "span" and source.get("style") is not None:
        actual["rend"] = source.get("style", "")
    elif tag == "p":
        renditions = [
            source.get(field)
            for field in ("class", "style")
            if source.get(field) is not None
        ]
        if renditions:
            actual["rend"] = " ; ".join(renditions)
    return actual


def _provider_metadata(root: etree._Element) -> dict[str, object]:
    head = root.find("ThML.head")
    if head is None:
        raise ValueError("retained source header is absent")
    title = head.find(".//DC.Title")
    author = next(
        (
            item
            for item in head.findall(".//DC.Creator")
            if item.get("sub") == "Author" and item.get("scheme") == "short-form"
        ),
        None,
    )
    publisher = head.find(".//DC.Publisher")
    date = head.find(".//DC.Date")
    identifier = head.find(".//DC.Identifier")
    language = head.find(".//DC.Language")
    description = head.find(".//description")
    if any(
        item is None
        for item in (title, author, publisher, date, identifier, language, description)
    ):
        raise ValueError("required source-record metadata field is absent")
    return {
        "title": title.text or "",
        "author": author.text or "",
        "publisher": publisher.text or "",
        "date": date.text or "",
        "date_sub": date.get("sub"),
        "identifier": identifier.text or "",
        "language": language.text or "",
        "subjects": [item.text or "" for item in head.findall(".//DC.Subject")],
        "description": description.text or "",
    }


def _verify_header(tei: etree._Element, source_root: etree._Element, raw: bytes) -> None:
    metadata = _provider_metadata(source_root)
    title = tei.find("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", NS)
    author = tei.find("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", NS)
    publisher = tei.find("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher", NS)
    date = tei.find("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:date", NS)
    record_uri = tei.find(
        "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:idno[@type='source-record-uri']",
        NS,
    )
    work_id = tei.find(
        "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:idno[@type='ocd-work-id']",
        NS,
    )
    language = tei.find("./tei:teiHeader/tei:profileDesc/tei:langUsage/tei:language", NS)
    keywords = tei.find("./tei:teiHeader/tei:profileDesc/tei:textClass/tei:keywords", NS)
    terms = tei.findall(
        "./tei:teiHeader/tei:profileDesc/tei:textClass/tei:keywords/tei:term", NS
    )
    source_description = tei.find(
        "./tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note[@type='source-record-description']",
        NS,
    )
    metadata_status = tei.find(
        "./tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note[@type='source-metadata-status']",
        NS,
    )
    source_member_note = tei.find("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:p", NS)
    if title is None or title.get("type") != "source-record-title" or title.text != metadata["title"]:
        raise ValueError("TEI title does not preserve the source-record title")
    if author is None or author.text != metadata["author"]:
        raise ValueError("TEI author does not preserve the source-record creator")
    if publisher is None or publisher.text != metadata["publisher"]:
        raise ValueError("TEI publisher does not preserve the source-record publisher")
    if (
        date is None
        or date.get("type") != "source-record-created"
        or date.get("when") != metadata["date"]
        or date.text != metadata["date"]
        or metadata["date_sub"] != "Created"
    ):
        raise ValueError("TEI date changed the source-record-created date meaning")
    if record_uri is None or record_uri.text != metadata["identifier"]:
        raise ValueError("TEI source-record identifier drifted")
    if work_id is None or work_id.text != WORK_ID:
        raise ValueError("TEI OCD work binding drifted")
    if language is None or language.get("ident") != metadata["language"] or language.text != metadata[
        "language"
    ]:
        raise ValueError("TEI language does not preserve the source-record value")
    if [item.text or "" for item in terms] != metadata["subjects"]:
        raise ValueError("TEI source-record subjects drifted or were reordered")
    if keywords is None or keywords.get("scheme") != "CCEL-DC.Subject":
        raise ValueError("TEI source-record subject scheme drifted")
    if source_description is None or source_description.text != metadata["description"]:
        raise ValueError("TEI source-record description drifted")
    if (
        metadata_status is None
        or metadata_status.text
        != "Provider metadata is transcribed as a source observation; it does not establish a print edition or publication date."
    ):
        raise ValueError("TEI source-metadata uncertainty statement drifted")
    expected_source_note = (
        f"Retained ThML XML member {SOURCE_PATH}; {len(raw):,} bytes; "
        f"SHA-256 {_sha(raw)}. The source record does not resolve edition, part, or physical witness identity."
    )
    if source_member_note is None or source_member_note.text != expected_source_note:
        raise ValueError("TEI retained-member note does not bind the exact witness")


def _source_body_comments(body: etree._Element) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for parent in _walk(body):
        for child in parent:
            if isinstance(child, etree._Comment):
                values.append((child.text or "", child.tail or ""))
            elif isinstance(child, etree._ProcessingInstruction):
                values.append((f"?{child.target} {child.text or ''}", child.tail or ""))
    return values


def _tei_body_comments(body: etree._Element) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for parent in _walk(body):
        for child in parent:
            if isinstance(child, etree._Comment):
                values.append((child.text or "", child.tail or ""))
            elif isinstance(child, etree._ProcessingInstruction):
                values.append((f"?{child.target} {child.text or ''}", child.tail or ""))
    return values


def _verify_body(source_root: etree._Element, tei: etree._Element) -> int:
    source_body = source_root.find("ThML.body")
    tei_body = tei.find("./tei:text/tei:body", NS)
    if source_body is None or tei_body is None:
        raise ValueError("source or candidate body is absent")
    if source_body.text != tei_body.text:
        raise ValueError("source body leading text or whitespace changed")
    if _source_body_comments(source_body) != _tei_body_comments(tei_body):
        raise ValueError("source body comments or processing instructions changed")
    source_nodes = list(_walk(source_body))[1:]
    candidate_nodes = list(_walk(tei_body))[1:]
    if len(source_nodes) != EXPECTED_BODY_COUNT - 1 or len(candidate_nodes) != len(source_nodes):
        raise ValueError("source and candidate body element counts do not reconcile")
    for index, (source, candidate) in enumerate(zip(source_nodes, candidate_nodes, strict=True)):
        source_name = _tag(source)
        expected_name = _tei_name(source_name)
        if _tag(candidate) != expected_name:
            raise ValueError(
                f"body carrier {index} changed order or TEI mapping: {source_name!r} to {_tag(candidate)!r}"
            )
        if source.text != candidate.text or source.tail != candidate.tail:
            raise ValueError(f"body carrier text/tail drift at source order {index}")
        if dict(candidate.attrib) != _expected_attributes(source, source_name):
            raise ValueError(f"body carrier attributes drift at source order {index}")
    direct_divisions = tei_body.findall("./tei:div", NS)
    if tuple(
        item.get(f"{{{XML_NS}}}id") for item in direct_divisions
    ) != EXPECTED_DIVISION_IDS:
        raise ValueError("candidate does not preserve the eight ordered source divisions")
    return len(candidate_nodes)


def _authority_bytes(source_manifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _verify_route_identity(source_manifest, raw: bytes) -> None:
    record = source_manifest.record
    if (
        record.get("ticket") != "37c-142"
        or record.get("owner_route") != "LIB-055"
        or record.get("source_id") != "edwards-religious-affections-lib055-retained-xml"
    ):
        raise ValueError("source manifest is not the exact LIB-055 / 37c-142 route")
    identity = record.get("identity")
    if not hasattr(identity, "get") or identity.get("work_id") != WORK_ID:
        raise ValueError("source manifest work identity is not 37c-142")
    for unknown in ("textual_form", "edition", "parts", "witness_claim", "translator", "original_publication_year"):
        if identity.get(unknown) is not None:
            raise ValueError(f"source manifest invents unresolved identity field {unknown}")
    authorities = record.get("authorities")
    primary = [item for item in authorities if item.get("role") == "primary-source"]
    if len(primary) != 1:
        raise ValueError("37c-142 must bind exactly one primary retained member")
    if (
        primary[0].get("path") != SOURCE_PATH
        or primary[0].get("bytes") != len(raw)
        or primary[0].get("bytes") != SOURCE_BYTES
        or primary[0].get("sha256") != _sha(raw)
        or primary[0].get("sha256") != SOURCE_SHA256
    ):
        raise ValueError("37c-142 retained source member differs from the pinned bytes")
    scope = record.get("scope")
    if not hasattr(scope, "get"):
        raise ValueError("source manifest work scope is invalid")
    if (
        scope.get("member_count") != 1
        or tuple(scope.get("member_order", ())) != (SOURCE_PATH,)
        or tuple(scope.get("top_level_div1_ids", ())) != EXPECTED_DIVISION_IDS
        or scope.get("selector") != "ThML[1] (complete retained document envelope)"
    ):
        raise ValueError("source manifest scope is not the exact complete 37c-142 member")
    work_identity = _strict_json(_authority_bytes(source_manifest, "work-identity"), "work identity")
    if work_identity != {
        "contract": "ocd-reconstruction-work-identity-v1",
        "work_id": WORK_ID,
    }:
        raise ValueError("work identity authority differs from the exact work binding")


def _verify_profile_and_policy(source_manifest, raw: bytes, document: dict[str, object]):
    profile_bytes = _authority_bytes(source_manifest, "feature-profile")
    profile = _strict_json(profile_bytes, "source feature profile")
    if (
        profile.get("contract") != "edwards-religious-affections-source-feature-profile-v1"
        or profile.get("work_id") != WORK_ID
        or profile.get("document") != document
        or profile.get("source_member")
        != {"path": SOURCE_PATH, "bytes": len(raw), "sha256": _sha(raw)}
    ):
        raise ValueError("source feature profile does not match the independently read bytes")
    policy_bytes = _authority_bytes(source_manifest, "policy")
    policy = _strict_json(policy_bytes, "independent-validation policy")
    if (
        policy.get("contract")
        != "edwards-religious-affections-independent-validation-policy-v1"
        or policy.get("work_id") != WORK_ID
    ):
        raise ValueError("independent-validation policy identity mismatch")
    unresolved = policy.get("unresolved_records")
    if not isinstance(unresolved, list) or tuple(
        item.get("question_id") for item in unresolved if isinstance(item, dict)
    ) != EXPECTED_UNRESOLVED_IDS:
        raise ValueError("policy no longer preserves all required identity/rights questions")
    if any(item.get("status") != "unresolved" for item in unresolved if isinstance(item, dict)):
        raise ValueError("an unresolved identity/rights question was silently settled")
    return profile_bytes, profile, policy_bytes, policy


def _verify_candidate_auxiliaries(
    source_manifest,
    candidate,
    raw: bytes,
    profile_bytes: bytes,
    policy: dict[str, object],
) -> None:
    source_authority = _bound_authority(source_manifest, "source-affections")
    expected_readme = _authority_bytes(source_manifest, "source-readme")
    if candidate.member_bytes("README.source.md") != expected_readme:
        raise ValueError("candidate source attribution README differs from its bound authority")
    actual_lines = candidate.member_bytes("unresolved.jsonl").splitlines()
    questions = policy["unresolved_records"]
    observed = [_strict_json(line, "unresolved record") for line in actual_lines]
    if observed != questions:
        raise ValueError("candidate unresolved questions differ from the bound evidence policy")
    expected_provenance = {
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
            "path": source_authority["path"],
            "bytes": len(raw),
            "sha256": _sha(raw),
        },
        "feature_profile_sha256": _sha(profile_bytes),
        "unresolved_question_ids": [item["question_id"] for item in questions],
        "rights_clearance": "unresolved",
        "human_acceptance": "not-recorded",
        "promotion": "not-authorized",
        "publication": "not-authorized",
    }
    provenance = _strict_json(candidate.member_bytes("provenance.json"), "candidate provenance")
    if provenance != expected_provenance:
        raise ValueError("candidate provenance or nonaccepted disposition drifted")


def _verify_accountability(source_manifest, candidate, tree, raw, document) -> None:
    actual = _strict_json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    source = _bound_authority(source_manifest, "source-affections")
    expected_scope = json.loads(_canonical(dict(source_manifest.record["scope"])))
    head = tree.getroot().find("ThML.head")
    body = tree.getroot().find("ThML.body")
    if head is None or body is None:
        raise ValueError("source header/body missing while reconciling accountability")
    comments = _shell(tree)
    expected_envelope = {
        "xml_declaration": {
            "version": tree.docinfo.xml_version,
            "encoding": tree.docinfo.encoding,
            "standalone": tree.docinfo.standalone,
        },
        "doctype": {
            "name": _tag(tree.getroot()),
            "public_id": tree.docinfo.public_id,
            "system_url": tree.docinfo.system_url,
            "declaration_sha256": _sha(tree.docinfo.doctype.encode("utf-8")),
        },
        "shell_nodes": comments,
        "counts": {
            "elements": document["element_count"],
            "head_elements_including_wrapper": document[
                "head_element_count_including_wrapper"
            ],
            "body_elements_including_wrapper": document[
                "body_element_count_including_wrapper"
            ],
            "comments": EXPECTED_COMMENT_COUNT,
            "stylesheet_processing_instructions": EXPECTED_STYLESHEET_PI_COUNT,
        },
        "document_profile": document,
    }
    expected_member = {"path": source["path"], "bytes": len(raw), "sha256": _sha(raw)}
    if (
        actual.get("contract") != "edwards-religious-affections-source-accountability-v1"
        or actual.get("work_id") != WORK_ID
        or actual.get("source_member") != expected_member
        or actual.get("scope") != expected_scope
        or actual.get("source_envelope") != expected_envelope
    ):
        raise ValueError("source-accountability header, shell, scope, or source binding drifted")
    expected_rows = _accounted_elements(tree)
    if actual.get("elements") != expected_rows:
        raise ValueError("source-accountability does not reconcile each source element")


def _verify_tei_schema(source_manifest, document: etree._ElementTree) -> None:
    schema_path = source_manifest.authority_path("tei-schema")
    _compiled_schema(str(schema_path)).assertValid(document)


@lru_cache(maxsize=2)
def _compiled_schema(path: str) -> etree.XMLSchema:
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    schema_tree = etree.parse(path, parser)
    return etree.XMLSchema(schema_tree)


def _closure_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _import_closure_sha256() -> str:
    root = _closure_root()
    members = []
    for logical in (
        "build/tei/ccel_puritan_lib055_edwards_religious_affections_oracle.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/reconstruction/contract.py",
    ):
        value = (root / logical).read_bytes()
        members.append({"path": logical, "bytes": len(value), "sha256": _sha(value)})
    return _sha(
        _canonical(
            {
                "contract": "ocd-37c-142-oracle-import-closure-v1",
                "members": members,
                "lxml_version": etree.LXML_VERSION,
                "libxml_version": etree.LIBXML_VERSION,
            }
        )
    )


def validate(source_manifest, candidate):
    source_manifest.verify()
    candidate.verify_integrity()
    _verify_route_identity(source_manifest, source_manifest.authority_path("source-affections").read_bytes())
    raw = source_manifest.authority_path("source-affections").read_bytes()
    parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
    )
    source_tree = etree.parse(BytesIO(raw), parser)
    root = source_tree.getroot()
    document = _independent_profile(source_tree)
    if document["element_count"] != EXPECTED_ELEMENT_COUNT:
        raise ValueError("independent reader found an unexpected source element count")
    profile_bytes, profile, policy_bytes, policy = _verify_profile_and_policy(
        source_manifest,
        raw,
        document,
    )
    _verify_candidate_auxiliaries(
        source_manifest,
        candidate,
        raw,
        profile_bytes,
        policy,
    )
    _verify_accountability(source_manifest, candidate, source_tree, raw, document)
    tei_bytes = candidate.member_bytes("content.tei.xml")
    tei_parser = etree.XMLParser(
        load_dtd=False,
        no_network=True,
        resolve_entities=False,
        remove_comments=False,
        remove_pis=False,
        remove_blank_text=False,
    )
    tei_tree = etree.parse(BytesIO(tei_bytes), tei_parser)
    tei = tei_tree.getroot()
    if _tag(tei) != "TEI" or tei.tag != f"{{{TEI_NS}}}TEI":
        raise ValueError("candidate root is not TEI P5")
    _verify_tei_schema(source_manifest, tei_tree)
    _verify_header(tei, root, raw)
    _verify_body(root, tei)

    authorities = source_manifest.record["authorities"]
    authority_roles = {
        item.get("name"): item.get("role") for item in authorities
    }
    expected_roles = {
        "source-affections": "primary-source",
        "work-identity": "work-config",
        "feature-profile": "complete-source-feature-profile",
        "policy": "independent-validation-policy",
        "tei-schema": "tei-validation-schema",
        "package-schema": "candidate-package-schema",
        "source-readme": "source-attribution-readme",
        "ccel-permission": "exact-source-permission",
    }
    if any(authority_roles.get(name) != role for name, role in expected_roles.items()):
        raise ValueError("source manifest authority roles do not match LIB-055")
    package_schema = _bound_authority(source_manifest, "package-schema")
    xsd = _bound_authority(source_manifest, "tei-schema")
    policy_authority = _bound_authority(source_manifest, "policy")
    profile_authority = _bound_authority(source_manifest, "feature-profile")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).resolve(strict=True).read_bytes()),
        validator_import_closure_sha256=_import_closure_sha256(),
        source_sha256=_sha(raw),
        profile_sha256=str(profile_authority["sha256"]),
        package_schema_sha256=str(package_schema["sha256"]),
        xsd_sha256=str(xsd["sha256"]),
        policy_sha256=str(policy_authority["sha256"]),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


validate.oracle_id = ORACLE_ID
validate.oracle_version = ORACLE_VERSION
