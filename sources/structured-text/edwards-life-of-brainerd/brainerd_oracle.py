"""Independent mechanical oracle for the Edwards Brainerd candidate.

This module deliberately re-reads the retained ThML source and reconstructs
its carrier facts without importing the entry-local converter.  It checks the
source envelope, work/member/edition binding, structure, mixed content,
accountability ledgers, TEI schema, and candidate handoff members before
delegating only the closed attestation assembly to the family-neutral helper.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "edwards-brainerd-independent-oracle"
ORACLE_VERSION = "1"
WORK_ID = "edwards-life-of-brainerd"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

SOURCE_TO_TEI = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "div5": "div",
    "h1": "p",
    "h2": "p",
    "h3": "p",
    "h4": "p",
    "h5": "p",
    "h6": "p",
    "p": "p",
    "i": "hi",
    "b": "hi",
    "note": "note",
    "pb": "pb",
    "scripRef": "ref",
}
DIV_TAGS = frozenset({"div1", "div2", "div3", "div4", "div5"})
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
SUPPORTED_TAGS = frozenset(SOURCE_TO_TEI)
EXPECTED_SCOPE = {
    "selector": "ThML/ThML.body/div1[@id='ix']",
    "selected_source_path": "ThML[1]/ThML.body[1]/div1[1]",
    "selected_source_id": "ix",
    "member_count": 1,
    "member_order": ["raw/ccel/edwards/brainerd.xml"],
    "boundary": "Complete selected div1 subtree in source order, including headings, inline tags, notes, page breaks, and scripture references.",
}
EXPECTED_IDENTITY = {
    "work_id": WORK_ID,
    "title": "The Life of David Brainerd",
    "author": "Jonathan Edwards",
    "textual_form": "English prose source witness",
    "edition": "CCEL ThML edition (sourced via CCEL.org). Extracted from works2 volume. Edwards' memoir of the missionary David Brainerd (1718-1747).",
    "parts": ["selected div1 id=ix"],
    "witnesses": ["raw/ccel/edwards/brainerd.xml"],
    "translator": None,
    "original_publication_year": 1749,
}
IMPORT_CLOSURE = (
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
)


def _q(name: str) -> str:
    return f"{{{TEI_NS}}}{name}"


def _xml_id() -> str:
    return f"{{{XML_NS}}}id"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _strict_json(content: bytes, label: str) -> dict[str, object]:
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
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _children(node: etree._Element) -> list[etree._Element]:
    result: list[etree._Element] = []
    for child in node:
        if not isinstance(child.tag, str):
            raise ValueError("Brainerd source or candidate contains a non-element child")
        result.append(child)
    return result


def _node_path(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and isinstance(current.tag, str):
        parent = current.getparent()
        if parent is None:
            position = 1
        else:
            try:
                raw_index = parent.index(current)
            except (AttributeError, ValueError) as exc:
                raise ValueError("source node is detached while addressing it") from exc
            position = sum(
                1
                for sibling in list(parent)[: raw_index + 1]
                if isinstance(sibling.tag, str) and _local(sibling) == _local(current)
            )
        parts.append(f"{_local(current)}[{position}]")
        current = parent
    return "/".join(reversed(parts))


def _source_feature(node: etree._Element, ordinal: int) -> dict[str, object]:
    parent = node.getparent()
    if parent is None:
        raise ValueError("Brainerd source carrier has no parent")
    try:
        child_index = parent.index(node) + 1
    except (AttributeError, ValueError) as exc:
        raise ValueError("Brainerd source carrier is detached") from exc
    direct_text = node.text or ""
    full_text = "".join(node.itertext())
    tail = node.tail or ""
    node_children = _children(node)
    return {
        "ordinal": ordinal,
        "source_path": _node_path(node),
        "parent_source_path": _node_path(parent),
        "element_child_index": child_index,
        "source_tag": _local(node),
        "source_id": node.get("id"),
        "source_attributes": dict(node.attrib),
        "source_text_sha256": _sha(full_text.encode("utf-8")),
        "source_text_characters": len(full_text),
        "direct_text_sha256": _sha(direct_text.encode("utf-8")),
        "direct_text_characters": len(direct_text),
        "source_tail_sha256": _sha(tail.encode("utf-8")),
        "source_tail_characters": len(tail),
        "child_tags": [_local(child) for child in node_children],
        "child_ids": [child.get("id") for child in node_children],
        "child_count": len(node_children),
    }


def _target_xml_id(source: etree._Element, ordinal: int) -> str:
    source_id = source.get("id")
    return source_id if source_id else f"brainerd-source-{ordinal:06d}"


def _expected_target_attributes(source: etree._Element, ordinal: int) -> dict[str, str]:
    source_tag = _local(source)
    attributes = {_xml_id(): _target_xml_id(source, ordinal)}
    if source_tag in DIV_TAGS:
        attributes["type"] = source_tag
        if source.get("n") is not None:
            attributes["n"] = str(source.get("n"))
    elif source_tag in HEADING_TAGS:
        attributes["rend"] = f"source-heading {source_tag}"
    elif source_tag == "p":
        if source.get("class") is not None:
            attributes["rend"] = str(source.get("class"))
    elif source_tag == "i":
        attributes["rend"] = "italic"
    elif source_tag == "b":
        attributes["rend"] = "bold"
    elif source_tag == "note":
        if source.get("place") is not None:
            attributes["place"] = str(source.get("place"))
        if source.get("n") is not None:
            attributes["n"] = str(source.get("n"))
    elif source_tag == "pb":
        if source.get("n") is not None:
            attributes["n"] = str(source.get("n"))
        if source.get("href") is not None:
            attributes["facs"] = str(source.get("href"))
    elif source_tag == "scripRef":
        attributes["type"] = source_tag
        if source.get("osisRef") is not None:
            attributes["target"] = str(source.get("osisRef"))
    return attributes


def _source_envelope(
    raw: bytes,
    root: etree._Element,
    body: etree._Element,
    selected: etree._Element,
) -> tuple[dict[str, object], dict[str, object]]:
    root_start = raw.find(b"<ThML>")
    root_end = raw.rfind(b"</ThML>") + len(b"</ThML>")
    if root_start < 0 or root_end < len(b"</ThML>"):
        raise ValueError("Brainerd source root byte envelope is not locatable")
    prefix = raw[:root_start]
    suffix = raw[root_end:]
    base = {
        "xml_declaration": prefix.decode("ascii"),
        "prefix_bytes": len(prefix),
        "prefix_sha256": _sha(prefix),
        "root_tag": _local(root),
        "root_children": [_local(child) for child in _children(root)],
        "body_tag": _local(body),
        "body_children": [
            {"tag": _local(child), "id": child.get("id")}
            for child in _children(body)
        ],
        "selected_source_path": _node_path(selected),
        "selected_source_id": selected.get("id"),
        "selected_root_tail": {
            "characters": len(selected.tail or ""),
            "sha256": _sha((selected.tail or "").encode("utf-8")),
        },
        "suffix_bytes": len(suffix),
        "suffix_sha256": _sha(suffix),
        "doctype": False,
        "comments": 0,
        "processing_instructions": 0,
    }
    profile = {
        **base,
        "root_attributes": dict(root.attrib),
        "body_attributes": dict(body.attrib),
        "selected_attributes": dict(selected.attrib),
    }
    return base, profile


def _parse_source(
    source_manifest: object,
) -> tuple[bytes, etree._Element, etree._Element, etree._Element, dict[str, object]]:
    authority_path = getattr(source_manifest, "authority_path", None)
    if not callable(authority_path):
        raise ValueError("source manifest authority resolver is unavailable")
    source_path = authority_path("source")
    raw = source_path.read_bytes()
    if b"<!DOCTYPE" in raw or b"<!--" in raw:
        raise ValueError("Brainerd source contains an unsupported document-shell construct")
    if b"<?" in raw and b"<?xml" not in raw:
        raise ValueError("Brainerd source contains an unsupported processing instruction")
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        remove_comments=False,
        strip_cdata=False,
    )
    try:
        root = etree.fromstring(raw, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Brainerd source is not well-formed XML") from exc
    if _local(root) != "ThML":
        raise ValueError("Brainerd source root is not the expected ThML envelope")
    root_children = _children(root)
    if len(root_children) != 1 or _local(root_children[0]) != "ThML.body":
        raise ValueError("Brainerd source does not have one ThML.body child")
    body = root_children[0]
    body_children = _children(body)
    if len(body_children) != 1:
        raise ValueError("Brainerd source does not have one retained member")
    selected = body_children[0]
    if _local(selected) != "div1" or selected.get("id") != "ix":
        raise ValueError("Brainerd selected member is not div1 id=ix")
    for node in selected.iter():
        if not isinstance(node.tag, str):
            raise ValueError("Brainerd selected source contains a non-element node")
        if _local(node) not in SUPPORTED_TAGS:
            raise ValueError(f"unsupported Brainerd source element {_local(node)!r}")
    _, profile_envelope = _source_envelope(raw, root, body, selected)
    return raw, root, body, selected, profile_envelope


def _walk_source(
    node: etree._Element,
    records: list[dict[str, object]],
) -> None:
    ordinal = len(records) + 1
    source_tag = _local(node)
    if source_tag not in SUPPORTED_TAGS:
        raise ValueError(f"unsupported Brainerd source element {source_tag!r}")
    records.append(
        {
            "ordinal": ordinal,
            "source": _source_feature(node, ordinal),
            "mapping": {
                "tei_tag": SOURCE_TO_TEI[source_tag],
                "tei_xml_id": _target_xml_id(node, ordinal),
                "disposition": "preserved",
            },
        }
    )
    for child in _children(node):
        _walk_source(child, records)


def _compare_tree(
    source: etree._Element,
    target: etree._Element,
    records: list[dict[str, object]],
    cursor: list[int],
) -> None:
    ordinal = cursor[0] + 1
    cursor[0] = ordinal
    source_tag = _local(source)
    expected_tag = SOURCE_TO_TEI[source_tag]
    if _local(target) != expected_tag:
        raise ValueError(
            f"TEI mapping mismatch at ordinal {ordinal}: expected {expected_tag}, got {_local(target)}"
        )
    expected_attrs = _expected_target_attributes(source, ordinal)
    if dict(target.attrib) != expected_attrs:
        raise ValueError(f"TEI attributes mismatch at source path {_node_path(source)}")
    if target.text != source.text:
        raise ValueError(f"TEI direct text mismatch at source path {_node_path(source)}")
    if target.tail != source.tail:
        raise ValueError(f"TEI tail mismatch at source path {_node_path(source)}")
    source_children = _children(source)
    target_children = _children(target)
    if len(source_children) != len(target_children):
        raise ValueError(f"TEI child count mismatch at source path {_node_path(source)}")
    for source_child, target_child in zip(source_children, target_children):
        _compare_tree(source_child, target_child, records, cursor)


def _expected_profile(
    raw: bytes,
    config_bytes: bytes,
    config: Mapping[str, object],
    selected: etree._Element,
    profile_envelope: Mapping[str, object],
    records: list[dict[str, object]],
) -> dict[str, object]:
    tag_counts = Counter(record["source"]["source_tag"] for record in records)
    structural_ids = [
        record["source"]["source_id"]
        for record in records
        if str(record["source"]["source_tag"]).startswith("div")
    ]
    markers: list[dict[str, object]] = []
    for node in selected.iter():
        if not isinstance(node.tag, str) or _local(node) not in DIV_TAGS:
            continue
        descendants = list(node.iterdescendants())
        if any(
            isinstance(descendant.tag, str)
            and (_local(descendant) in DIV_TAGS or _local(descendant) == "p")
            for descendant in descendants
        ):
            continue
        node_children = _children(node)
        markers.append(
            {
                "source_id": node.get("id"),
                "source_tag": _local(node),
                "child_tags": [_local(child) for child in node_children],
                "child_ids": [child.get("id") for child in node_children],
            }
        )
    mixed = Counter()
    for node in selected.iter():
        if not isinstance(node.tag, str):
            continue
        node_children = _children(node)
        if node_children and (
            bool(node.text) or any(bool(child.tail) for child in node_children)
        ):
            mixed[_local(node)] += 1
    non_null_ids = [record["source"]["source_id"] for record in records if record["source"]["source_id"] is not None]
    source_hash = _sha(raw)
    return {
        "contract": "edwards-brainerd-source-feature-profile-v1",
        "work_id": WORK_ID,
        "source_member": {
            "path": "raw/ccel/edwards/brainerd.xml",
            "bytes": len(raw),
            "sha256": source_hash,
            "role": "primary-source",
        },
        "work_config": {
            "path": "sources/structured-text/edwards-life-of-brainerd/config.json",
            "sha256": _sha(config_bytes),
            "source_file": "raw/ccel/edwards/brainerd.xml",
            "source_hash": config["source_hash"],
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "language": config["language"],
            "translator": config["translator"],
            "volume_xml": "works2",
            "volume_div_id": "ix",
        },
        "scope": EXPECTED_SCOPE,
        "envelope": dict(profile_envelope),
        "carrier_count": len(records),
        "carrier_digest": _sha(_canonical([record["source"] for record in records])),
        "tag_counts": dict(sorted(tag_counts.items())),
        "structural_ids_in_source_order": structural_ids,
        "structural_markers_without_div_or_p_descendants": markers,
        "mixed_content": {
            "definition": "A carrier has at least one element child and either non-empty direct text or at least one non-empty element tail.",
            "parent_count": sum(mixed.values()),
            "by_tag": dict(sorted(mixed.items())),
        },
        "source_id_observations": {
            "carrier_ids_non_null": len(non_null_ids),
            "carrier_ids_null": len(records) - len(non_null_ids),
            "all_carrier_ids_present": len(non_null_ids) == len(records),
            "unique_non_null_carrier_ids": len(non_null_ids) == len(set(non_null_ids)),
        },
        "unsupported_source_elements": [],
        "well_formed_source_envelope": True,
    }


def _expected_accountability(
    raw: bytes,
    source_authority: Mapping[str, object],
    source_scope: Mapping[str, object],
    envelope: Mapping[str, object],
    records: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "contract": "edwards-brainerd-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member": {
            "path": source_authority["path"],
            "bytes": len(raw),
            "sha256": _sha(raw),
            "role": source_authority["role"],
        },
        "scope": _plain(source_scope),
        "envelope": dict(envelope),
        "carrier_count": len(records),
        "carrier_digest": _sha(_canonical([record["source"] for record in records])),
        "carriers": records,
        "unsupported_source_elements": [],
        "explicit_exclusions": [
            {
                "region": "XML declaration and ThML/ThML.body wrapper tags",
                "reason": "represented as TEI envelope/provenance rather than repeated as body content",
            },
            {
                "region": "selected div1 tail whitespace",
                "reason": "serialization whitespace outside the selected work subtree; retained in mapped root tail and envelope evidence",
            },
        ],
    }


def _expected_readme(
    config: Mapping[str, object],
    raw: bytes,
    source_scope: Mapping[str, object],
    envelope: Mapping[str, object],
    records: list[dict[str, object]],
) -> bytes:
    counts = Counter(record["source"]["source_tag"] for record in records)
    lines = [
        f"# {config['title']}",
        "",
        "This is a nonaccepted, source-bound TEI candidate for technical review.",
        "Human acceptance, rights clearance, accepted-master promotion, and publication are separate decisions.",
        "",
        f"- Work ID: `{WORK_ID}`",
        "- Source member: `raw/ccel/edwards/brainerd.xml`",
        f"- Source SHA-256: `{_sha(raw)}`",
        f"- Source scope: `{source_scope['selector']}`",
        f"- Source envelope: `{envelope['root_tag']} -> {envelope['body_tag']}` with selected `div1 id=\"ix\"`",
        f"- Preserved source carriers: `{len(records)}`",
        f"- Carrier digest: `{_sha(_canonical([record['source'] for record in records]))}`",
        "",
        "The readable TEI preserves source order and mixed inline content, including 88 inline footnotes, 146 page breaks, and 246 scripture references.",
        "ThML h1-h6 elements are emitted as standard TEI p elements with rend=source-heading hN so their source order remains valid under the bound TEI schema.",
        "The source navigation-title attributes remain in `source-accountability.json`; they are not emitted as duplicate printed headings.",
        "The original print-edition collation and translator attribution remain unresolved.",
        "",
        "Source attribution: CCEL ThML witness as identified by the retained work configuration.",
    ]
    lines.append(
        "Source tag counts: "
        + ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _authority_record(source_manifest: object, name: str) -> Mapping[str, object]:
    record = getattr(source_manifest, "record", None)
    if not isinstance(record, Mapping):
        raise ValueError("source manifest record is unavailable")
    authorities = record.get("authorities")
    if not isinstance(authorities, (list, tuple)):
        raise ValueError("source manifest authorities are unavailable")
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("name") == name:
            return authority
    raise ValueError(f"source manifest has no {name!r} authority")


def _authority_bytes(source_manifest: object, name: str) -> bytes:
    resolver = getattr(source_manifest, "authority_path", None)
    if not callable(resolver):
        raise ValueError("source manifest authority resolver is unavailable")
    return resolver(name).read_bytes()


def _import_closure_digest(root: Path) -> str:
    records = []
    for logical_path in IMPORT_CLOSURE:
        path = (root / logical_path).resolve(strict=True)
        records.append({"path": logical_path, "sha256": _sha(path.read_bytes())})
    return _sha(_canonical(records))


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _plain(value: object) -> object:
    """Convert frozen manifest containers to ordinary JSON-shaped values."""

    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _check_manifest_and_config(
    source_manifest: object,
    config: Mapping[str, object],
    config_bytes: bytes,
    raw: bytes,
) -> tuple[Mapping[str, object], Mapping[str, object], Mapping[str, object]]:
    manifest_record = _require_mapping(
        getattr(source_manifest, "record", None), "source manifest record"
    )
    if manifest_record.get("contract") != "ocd-source-manifest-v1":
        raise ValueError("source manifest contract mismatch")
    if manifest_record.get("source_id") != WORK_ID:
        raise ValueError("source manifest work identity mismatch")
    if _plain(manifest_record.get("identity")) != EXPECTED_IDENTITY:
        raise ValueError("source manifest identity or edition binding mismatch")
    source_scope = _require_mapping(manifest_record.get("scope"), "source manifest scope")
    if _plain(source_scope) != EXPECTED_SCOPE:
        raise ValueError("source manifest source scope mismatch")
    source_authority = _authority_record(source_manifest, "source")
    if source_authority.get("role") != "primary-source":
        raise ValueError("Brainerd source authority is not primary-source")
    if source_authority.get("path") != "raw/ccel/edwards/brainerd.xml":
        raise ValueError("Brainerd primary-source path mismatch")
    if source_authority.get("bytes") != len(raw) or source_authority.get("sha256") != _sha(raw):
        raise ValueError("Brainerd primary-source digest mismatch")
    source_file = str(config.get("source_file", "")).replace("\\", "/")
    if (
        config.get("resource_id") != WORK_ID
        or config.get("title") != EXPECTED_IDENTITY["title"]
        or config.get("author") != EXPECTED_IDENTITY["author"]
        or source_file != source_authority["path"]
        or config.get("source_hash") != "sha256:" + _sha(raw)
        or config.get("source_url") != "https://www.ccel.org/ccel/edwards/works2.xml"
        or config.get("source_format") != "ThML XML"
        or config.get("source_edition") != EXPECTED_IDENTITY["edition"]
        or config.get("language") != "en"
        or config.get("original_language") != "en"
        or config.get("translator") is not None
        or config.get("original_publication_year") != 1749
    ):
        raise ValueError("Brainerd work config source or edition binding mismatch")
    if _sha(config_bytes) != _authority_record(source_manifest, "work-config")["sha256"]:
        raise ValueError("Brainerd work config authority digest mismatch")
    if _authority_record(source_manifest, "work-config").get("role") != "work-config":
        raise ValueError("Brainerd work config authority role mismatch")
    package_schema = _authority_record(source_manifest, "package-schema")
    xsd = _authority_record(source_manifest, "tei-schema")
    profile = _authority_record(source_manifest, "feature-profile")
    policy = _authority_record(source_manifest, "policy")
    expected_roles = {
        "package-schema": "candidate-package-schema",
        "tei-schema": "tei-validation-schema",
        "feature-profile": "complete-source-feature-profile",
        "policy": "independent-validation-policy",
    }
    for name, role in expected_roles.items():
        if _authority_record(source_manifest, name).get("role") != role:
            raise ValueError(f"Brainerd authority role mismatch for {name}")
    package_binding = _require_mapping(manifest_record.get("package_schema"), "package schema")
    if dict(package_binding) != {
        "path": package_schema["path"],
        "sha256": package_schema["sha256"],
    }:
        raise ValueError("candidate package schema binding mismatch")
    return profile, xsd, policy


def _check_policy(policy: Mapping[str, object]) -> list[Mapping[str, object]]:
    if policy.get("contract") != "edwards-brainerd-independent-validation-policy-v1":
        raise ValueError("Brainerd validation policy contract mismatch")
    if policy.get("work_id") != WORK_ID:
        raise ValueError("Brainerd validation policy work identity mismatch")
    if policy.get("source_scope") != {
        "selector": EXPECTED_SCOPE["selector"],
        "selected_source_path": EXPECTED_SCOPE["selected_source_path"],
        "selected_source_id": EXPECTED_SCOPE["selected_source_id"],
        "member_policy": "Exactly one retained XML member; no archive siblings are in scope.",
    }:
        raise ValueError("Brainerd validation policy scope mismatch")
    if policy.get("supported_source_tags") != [
        "div1", "div2", "div3", "div4", "div5", "h1", "h2", "h3", "h4", "h5", "h6",
        "p", "i", "b", "note", "pb", "scripRef",
    ]:
        raise ValueError("Brainerd validation policy supported tags mismatch")
    if policy.get("source_to_tei") != SOURCE_TO_TEI:
        raise ValueError("Brainerd validation policy mapping mismatch")
    unresolved = policy.get("unresolved_records")
    if not isinstance(unresolved, list) or not all(isinstance(item, Mapping) for item in unresolved):
        raise ValueError("Brainerd validation policy unresolved records are invalid")
    return unresolved


def _check_tei(
    candidate: object,
    source_manifest: object,
    selected: etree._Element,
    records: list[dict[str, object]],
    config: Mapping[str, object],
    xsd_path: Path,
) -> bytes:
    member_bytes = getattr(candidate, "member_bytes", None)
    if not callable(member_bytes):
        raise ValueError("candidate member reader is unavailable")
    content = member_bytes("content.tei.xml")
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        recover=False,
        remove_comments=False,
        strip_cdata=False,
    )
    try:
        document = etree.fromstring(content, parser)
        schema = etree.XMLSchema(etree.parse(str(xsd_path), parser))
        schema.assertValid(document)
    except (etree.XMLSyntaxError, etree.DocumentInvalid) as exc:
        raise ValueError(f"Brainerd TEI does not validate against the bound XSD: {exc}") from exc
    if _local(document) != "TEI" or document.get(_xml_id()) != WORK_ID:
        raise ValueError("Brainerd TEI root identity mismatch")
    for node in document.iter():
        if any(not isinstance(child.tag, str) for child in node):
            raise ValueError("Brainerd TEI contains an unsupported non-element node")
    header = document.find(_q("teiHeader"))
    text = document.find(_q("text"))
    if header is None or text is None:
        raise ValueError("Brainerd TEI header or text is missing")
    title = header.find(f"./{_q('fileDesc')}/{_q('titleStmt')}/{_q('title')}")
    author = header.find(f"./{_q('fileDesc')}/{_q('titleStmt')}/{_q('author')}")
    publication = header.find(f"./{_q('fileDesc')}/{_q('publicationStmt')}/{_q('p')}")
    bibl = header.find(f"./{_q('fileDesc')}/{_q('sourceDesc')}/{_q('bibl')}")
    project = header.find(f"./{_q('encodingDesc')}/{_q('projectDesc')}/{_q('p')}")
    if title is None or title.text != config["title"] or author is None or author.text != config["author"]:
        raise ValueError("Brainerd TEI title or author binding mismatch")
    publication_text = (publication.text or "").casefold() if publication is not None else ""
    if "nonaccepted" not in publication_text or "pending" not in publication_text:
        raise ValueError("Brainerd TEI acceptance boundary is missing")
    if bibl is None:
        raise ValueError("Brainerd TEI source bibliography is missing")
    bibl_title = bibl.find(_q("title"))
    source_file = next((node for node in bibl.findall(_q("idno")) if node.get("type") == "source-file"), None)
    source_url = next((node for node in bibl.findall(_q("idno")) if node.get("type") == "source-url"), None)
    if (
        bibl_title is None
        or bibl_title.text != config["source_edition"]
        or source_file is None
        or source_file.text != "raw/ccel/edwards/brainerd.xml"
        or source_url is None
        or source_url.text != config["source_url"]
    ):
        raise ValueError("Brainerd TEI source bibliography binding mismatch")
    project_text = (project.text or "").casefold() if project is not None else ""
    if "element order" not in project_text or "source accountability" not in project_text:
        raise ValueError("Brainerd TEI structural preservation note is missing")
    body = text.find(_q("body"))
    if body is None:
        raise ValueError("Brainerd TEI body is missing")
    body_children = _children(body)
    if len(body_children) != 1:
        raise ValueError("Brainerd TEI body does not have one selected work root")
    cursor = [0]
    _compare_tree(selected, body_children[0], records, cursor)
    if cursor[0] != len(records):
        raise ValueError("Brainerd TEI carrier walk length mismatch")
    return content


def _check_candidate_manifest(candidate: object, source_manifest: object) -> None:
    record = _require_mapping(getattr(source_manifest, "record", None), "source manifest record")
    manifest = _require_mapping(getattr(candidate, "manifest", None), "candidate manifest")
    if manifest.get("status") != "nonaccepted" or manifest.get("source_id") != WORK_ID:
        raise ValueError("candidate acceptance or work identity boundary is invalid")
    source_path = getattr(source_manifest, "path", None)
    root = getattr(source_manifest, "repository_root", None)
    if not isinstance(source_path, Path) or not isinstance(root, Path):
        raise ValueError("source manifest path binding is unavailable")
    expected_source_manifest = {
        "path": source_path.relative_to(root).as_posix(),
        "sha256": getattr(source_manifest, "sha256"),
    }
    if manifest.get("source_manifest") != expected_source_manifest:
        raise ValueError("candidate source manifest binding mismatch")
    if manifest.get("converter") != dict(_require_mapping(record.get("converter"), "converter binding")):
        raise ValueError("candidate converter binding mismatch")
    if manifest.get("package_schema") != dict(_require_mapping(record.get("package_schema"), "package schema")):
        raise ValueError("candidate package schema binding mismatch")


def validate(source_manifest: object, candidate: object) -> Mapping[str, object]:
    """Independently validate one source-bound Brainerd candidate package."""

    raw, root, body, selected, profile_envelope = _parse_source(source_manifest)
    config_bytes = _authority_bytes(source_manifest, "work-config")
    config = _strict_json(config_bytes, "Brainerd work config")
    _, xsd_authority, _ = _check_manifest_and_config(
        source_manifest, config, config_bytes, raw
    )
    profile_bytes = _authority_bytes(source_manifest, "feature-profile")
    policy_bytes = _authority_bytes(source_manifest, "policy")
    xsd_path = getattr(source_manifest, "authority_path")("tei-schema")
    profile = _strict_json(profile_bytes, "Brainerd feature profile")
    policy = _strict_json(policy_bytes, "Brainerd validation policy")
    unresolved_records = _check_policy(policy)
    records: list[dict[str, object]] = []
    _walk_source(selected, records)
    if len(records) != 8545:
        raise ValueError(f"Brainerd source carrier count changed: {len(records)}")
    expected_profile = _expected_profile(
        raw, config_bytes, config, selected, profile_envelope, records
    )
    if profile != expected_profile:
        raise ValueError("Brainerd feature profile does not match the independently read source")
    _check_candidate_manifest(candidate, source_manifest)
    tei_bytes = _check_tei(candidate, source_manifest, selected, records, config, xsd_path)
    member_bytes = getattr(candidate, "member_bytes")
    actual_accountability = _strict_json(
        member_bytes("source-accountability.json"), "Brainerd source accountability"
    )
    expected_accountability = _expected_accountability(
        raw,
        _authority_record(source_manifest, "source"),
        _require_mapping(getattr(source_manifest, "record").get("scope"), "source scope"),
        _source_envelope(raw, root, body, selected)[0],
        records,
    )
    if actual_accountability != expected_accountability:
        raise ValueError("Brainerd source accountability does not match the independent source walk")
    actual_provenance = _strict_json(member_bytes("provenance.json"), "Brainerd provenance")
    expected_provenance = {
        "contract": "edwards-brainerd-provenance-v1",
        "status": "nonaccepted",
        "work_id": WORK_ID,
        "title": config["title"],
        "author": config["author"],
        "textual_form": {
            "language": config.get("language"),
            "original_language": config.get("original_language"),
            "translator": config.get("translator"),
        },
        "source_member": actual_accountability["source_member"],
        "source_config_sha256": _sha(config_bytes),
        "source_manifest_sha256": getattr(source_manifest, "sha256"),
        "source_scope": _plain(_require_mapping(getattr(source_manifest, "record").get("scope"), "source scope")),
        "source_url": config["source_url"],
        "source_format": config["source_format"],
        "source_edition": config["source_edition"],
        "source_envelope": actual_accountability["envelope"],
        "feature_profile_sha256": _sha(profile_bytes),
        "validation_policy_sha256": _sha(policy_bytes),
        "carrier_count": len(records),
        "carrier_digest": _sha(_canonical([record["source"] for record in records])),
        "mapping": {
            "source_to_tei": dict(SOURCE_TO_TEI),
            "navigation_attributes": ["title", "shorttitle", "progress", "prev", "next"],
            "navigation_title_policy": "retained in accountability; not duplicated as a printed head",
            "wrapper_policy": "ThML and ThML.body are represented in envelope evidence; selected div1 is TEI body root",
            "legacy_projection": "data/structured-text/edwards-life-of-brainerd.json is diagnostic only",
        },
        "human_review": "pending",
        "rights_status": "not independently cleared in this technical lane",
    }
    if actual_provenance != expected_provenance:
        raise ValueError("Brainerd provenance does not match the independent source and authority bindings")
    actual_unresolved = member_bytes("unresolved.jsonl")
    try:
        unresolved_lines = actual_unresolved.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Brainerd unresolved ledger is not UTF-8") from exc
    parsed_unresolved = [_strict_json(line.encode("utf-8"), "Brainerd unresolved record") for line in unresolved_lines if line]
    if parsed_unresolved != unresolved_records:
        raise ValueError("Brainerd unresolved ledger does not match the bound policy")
    expected_readme = _expected_readme(
        config,
        raw,
        _require_mapping(getattr(source_manifest, "record").get("scope"), "source scope"),
        actual_accountability["envelope"],
        records,
    )
    if member_bytes("README.source.md") != expected_readme:
        raise ValueError("Brainerd source README does not match the independent ledger")
    if not tei_bytes:
        raise ValueError("Brainerd TEI member is empty")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).resolve(strict=True).read_bytes()),
        validator_import_closure_sha256=_import_closure_digest(
            getattr(source_manifest, "repository_root")
        ),
        source_sha256=_sha(raw),
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_authority_record(source_manifest, "package-schema")["sha256"],
        xsd_sha256=xsd_authority["sha256"],
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


validate.oracle_id = ORACLE_ID
validate.oracle_version = ORACLE_VERSION
