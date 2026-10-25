"""Source-bound ThML-to-TEI reconstruction for LIB-055 / 37c-256."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-murray-absolute-surrender-retained-thml-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "murray-absolute-surrender"
SOURCE_ID = "murray-absolute-surrender-retained-thml"
SOURCE_PATH = "raw/ccel/murray/surrender.xml"
SOURCE_SHA256 = "3b8a474258f452b6d43ce14735c2594da52cd583a0271e8a650969aad97aff7d"
PROFILE_CONTRACT = "ocd-murray-absolute-surrender-profile-v1"
ACCOUNTABILITY_CONTRACT = "ocd-murray-absolute-surrender-source-accountability-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
DOCTYPE_RE = re.compile(r"<!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>", re.IGNORECASE | re.DOTALL)
ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
BODY_TAGS = {
    "div1",
    "div2",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "p",
    "scripRef",
    "a",
    "i",
    "br",
    "l",
    "verse",
    "insertIndex",
}
NON_ELEMENT_EVENT_RE = re.compile(
    r"(?P<doctype><!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>)"
    r"|(?P<comment><!--[\s\S]*?-->)"
    r"|(?P<pi><\?(?!xml(?:\s|\?>))[\s\S]*?\?>)",
    re.IGNORECASE,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority_bytes(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _parse_source(content: bytes) -> etree._Element:
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("retained Murray ThML must be UTF-8") from error
    prepared = DOCTYPE_RE.sub("", decoded)
    unknown = sorted(set(ENTITY_RE.findall(prepared)) - XML_ENTITIES)
    if unknown:
        raise ValueError(f"unsupported named entity in retained Murray ThML: {unknown[0]}")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=True,
        remove_comments=False,
        strip_cdata=False,
    )
    try:
        root = etree.fromstring(prepared.encode("utf-8"), parser)
    except etree.XMLSyntaxError as error:
        raise ValueError("retained Murray ThML is not well-formed after safe DOCTYPE removal") from error
    if etree.QName(root).localname != "ThML":
        raise ValueError("retained Murray source root must be ThML")
    if root.nsmap.get(None):
        raise ValueError("retained Murray ThML unexpectedly uses a default namespace")
    return root


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        tag = _local(current)
        parent = current.getparent()
        if parent is None:
            position = 1
        else:
            peers = [
                child
                for child in parent
                if isinstance(child.tag, str) and child.tag == current.tag
            ]
            position = peers.index(current) + 1
        parts.append(f"{tag}[{position}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _header_target(node: etree._Element) -> str | None:
    tag = _local(node)
    if tag == "ThML.head":
        return "murray-absolute-surrender-source-header"
    if tag == "DC.Title":
        return "murray-absolute-surrender-header-title"
    if tag == "DC.Creator" and node.get("scheme") == "short-form":
        return "murray-absolute-surrender-header-author"
    if tag == "DC.Contributor" and node.get("sub") == "Transcriber":
        return "murray-absolute-surrender-header-transcriber"
    if tag == "published":
        return "murray-absolute-surrender-header-print-claim"
    if tag == "editorialComments":
        return "murray-absolute-surrender-header-editorial-note"
    if tag == "DC.Subject" and node.get("scheme") == "ccel":
        return "murray-absolute-surrender-header-subjects"
    if tag == "DC.Publisher":
        return "murray-absolute-surrender-header-provider"
    if tag == "DC.Rights":
        return "murray-absolute-surrender-header-rights-claim"
    if tag == "DC.Language":
        return "murray-absolute-surrender-header-language"
    return None


def _target_xml_id(
    node: etree._Element,
    ordinal: int,
    *,
    root: etree._Element,
    body: etree._Element,
    body_nodes: set[etree._Element],
) -> str | None:
    if node is root:
        return WORK_ID
    if node is body:
        return f"{WORK_ID}-text"
    if node in body_nodes:
        source_id = node.get("id")
        if source_id:
            return source_id
        return f"{WORK_ID}-node-{ordinal:05d}"
    return _header_target(node)


def _feature_disposition(
    node: etree._Element,
    *,
    root: etree._Element,
    body: etree._Element,
    body_nodes: set[etree._Element],
    target_xml_id: str | None,
) -> str:
    if node is root:
        return "represented-by-tei-root"
    if node is body:
        return "represented-by-tei-text"
    if node in body_nodes:
        return "represented-in-tei-body"
    if target_xml_id is not None:
        return "represented-in-tei-header"
    if _local(node) in {"style", "selector"}:
        return "presentation-metadata-accountability-only"
    return "source-header-accountability-only"


def _features(root: etree._Element, body: etree._Element) -> list[dict[str, object]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    ordinal_by_element = {node: ordinal for ordinal, node in enumerate(elements, 1)}
    body_nodes = {node for node in body.iter() if isinstance(node.tag, str)}
    features: list[dict[str, object]] = []
    for ordinal, node in enumerate(elements, 1):
        parent = node.getparent()
        peers = (
            [child for child in parent if isinstance(child.tag, str)]
            if parent is not None
            else [node]
        )
        target = _target_xml_id(
            node, ordinal, root=root, body=body, body_nodes=body_nodes
        )
        features.append(
            {
                "feature_id": f"{WORK_ID}-feature-{ordinal:05d}",
                "source_ordinal": ordinal,
                "source_selector": _selector(node),
                "source_qname": str(node.tag),
                "source_attributes": [
                    {"qname": key, "value": value}
                    for key, value in sorted(node.attrib.items())
                ],
                "source_direct_text": node.text or "",
                "source_tail_text": node.tail or "",
                "source_parent_ordinal": ordinal_by_element[parent]
                if parent is not None
                else None,
                "source_child_ordinal": peers.index(node) + 1,
                "disposition": _feature_disposition(
                    node,
                    root=root,
                    body=body,
                    body_nodes=body_nodes,
                    target_xml_id=target,
                ),
                "target_xml_id": target,
            }
        )
    return features


def _non_element_events(content: bytes) -> list[dict[str, object]]:
    decoded = content.decode("utf-8")
    rows: list[dict[str, object]] = []
    for ordinal, match in enumerate(NON_ELEMENT_EVENT_RE.finditer(decoded), 1):
        lexical = match.group(0)
        rows.append(
            {
                "source_event_ordinal": ordinal,
                "kind": str(match.lastgroup),
                "lexical": lexical,
                "sha256": _sha(lexical.encode("utf-8")),
                "disposition": "non-element-event-byte-bound-only",
            }
        )
    return rows


def _source_metadata(root: etree._Element) -> dict[str, str]:
    title = root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Title)")
    author = root.xpath(
        "string(./ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form'])"
    )
    transcriber = root.xpath(
        "string(./ThML.head/electronicEdInfo/DC/DC.Contributor[@sub='Transcriber'])"
    )
    language = root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Language)")
    language_scheme = root.xpath(
        "string(./ThML.head/electronicEdInfo/DC/DC.Language/@scheme)"
    )
    print_claim = root.xpath("string(./ThML.head/printSourceInfo/published)")
    editorial_comment = root.xpath(
        "string(./ThML.head/electronicEdInfo/editorialComments)"
    )
    subjects = root.xpath(
        "string(./ThML.head/electronicEdInfo/DC/DC.Subject[@scheme='ccel'])"
    )
    provider = root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Publisher)")
    rights_claim = root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Rights)")
    values = {
        "title": title,
        "author": author,
        "transcriber": transcriber,
        "language": language,
        "language_scheme": language_scheme,
        "print_claim": print_claim,
        "editorial_comment": editorial_comment,
        "subjects": subjects,
        "provider": provider,
        "rights_claim": rights_claim,
    }
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        missing = sorted(name for name, value in values.items() if not str(value).strip())
        raise ValueError(f"required retained header metadata is missing: {', '.join(missing)}")
    return {name: " ".join(value.split()) for name, value in values.items()}


def _element(name: str, attrs: dict[str, str] | None = None, text: str | None = None) -> etree._Element:
    node = etree.Element(
        f"{{{TEI_NS}}}{name}",
        nsmap={None: TEI_NS} if name == "TEI" else None,
    )
    for key, value in (attrs or {}).items():
        node.set(f"{{{XML_NS}}}id" if key == "xml:id" else key, value)
    node.text = text
    return node


def _source_corresp(selector: str) -> str:
    return "urn:ocd:source-xpath:" + quote(selector, safe="")


def _id_and_corresp(
    source: etree._Element, ordinal_by_element: dict[etree._Element, int]
) -> dict[str, str]:
    return {
        "xml:id": str(_body_xml_id(source, ordinal_by_element)),
        "corresp": _source_corresp(_selector(source)),
    }


def _body_xml_id(
    node: etree._Element, ordinal_by_element: dict[etree._Element, int]
) -> str:
    source_id = node.get("id")
    if source_id:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9._-]*", source_id):
            raise ValueError(f"source id is not a safe TEI xml:id: {source_id!r}")
        return source_id
    return f"{WORK_ID}-node-{ordinal_by_element[node]:05d}"


def _append_text(parent: etree._Element, text: str | None) -> None:
    if not text:
        return
    if len(parent):
        last = parent[-1]
        last.tail = (last.tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _convert_body_element(
    source: etree._Element,
    ordinal_by_element: dict[etree._Element, int],
) -> etree._Element:
    tag = _local(source)
    attrs = _id_and_corresp(source, ordinal_by_element)
    if tag in {"div1", "div2", "div"}:
        if tag == "div1":
            if source.get("id") == "i":
                tei_type = "title-page"
            elif source.get("id") == "xi":
                tei_type = "indexes"
            else:
                tei_type = "address"
        elif tag == "div2":
            tei_type = "index"
        else:
            tei_type = (source.get("class") or "section").casefold()
        attrs["type"] = tei_type
        if source.get("n"):
            attrs["n"] = source.get("n", "")
        out = _element("div", attrs)
    elif tag in {"h1", "h2", "h3"}:
        attrs["type"] = f"ThML-{tag}"
        out = _element("head", attrs)
    elif tag == "h4":
        attrs["type"] = "source-heading"
        attrs["subtype"] = "ThML-h4"
        out = _element("ab", attrs)
    elif tag == "p":
        if source.get("class"):
            attrs["rend"] = source.get("class", "")
        out = _element("p", attrs)
    elif tag == "a":
        target = source.get("href")
        if not target:
            raise ValueError(f"source link has no href at {_selector(source)}")
        attrs["target"] = target
        if source.get("class"):
            attrs["type"] = source.get("class", "")
        out = _element("ref", attrs)
    elif tag == "scripRef":
        attrs["type"] = "scripture"
        if source.get("passage"):
            attrs["n"] = source.get("passage", "")
        refs = [
            re.sub(r"^Bible(?:\.[A-Za-z0-9_-]+)?:", "", value)
            for value in (source.get("osisRef") or "").split()
        ]
        refs = [value for value in refs if value]
        if not refs:
            raise ValueError(f"scripture reference has no usable osisRef at {_selector(source)}")
        attrs["cRef"] = " ".join(refs)
        out = _element("ref", attrs)
    elif tag == "i":
        attrs["rend"] = "italic"
        out = _element("hi", attrs)
    elif tag == "verse":
        attrs["type"] = "verse"
        out = _element("lg", attrs)
    elif tag == "l":
        out = _element("l", attrs)
    elif tag == "br":
        out = _element("lb", attrs)
    elif tag == "insertIndex":
        attrs["type"] = "source-index-marker"
        out = _element("anchor", attrs)
    else:
        raise ValueError(f"unsupported retained body element <{tag}> at {_selector(source)}")

    if tag != "br":
        _append_text(out, source.text)
        for child in source:
            if not isinstance(child.tag, str):
                raise ValueError(f"non-element child is unsupported at {_selector(source)}")
            if _local(child) not in BODY_TAGS:
                raise ValueError(f"unsupported retained body child <{_local(child)}> at {_selector(child)}")
            converted = _convert_body_element(child, ordinal_by_element)
            converted.tail = child.tail
            out.append(converted)
    return out


def _header(metadata: dict[str, str], source_sha256: str) -> etree._Element:
    header = _element("teiHeader", {"xml:id": f"{WORK_ID}-source-header"})
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(
        _element(
            "title",
            {"xml:id": "murray-absolute-surrender-header-title"},
            metadata["title"],
        )
    )
    title_stmt.append(
        _element(
            "author",
            {"xml:id": "murray-absolute-surrender-header-author"},
            metadata["author"],
        )
    )
    resp_stmt = _element("respStmt")
    resp_stmt.append(_element("resp", text="Transcriber of the retained CCEL ThML"))
    resp_stmt.append(
        _element(
            "name",
            {"xml:id": "murray-absolute-surrender-header-transcriber"},
            metadata["transcriber"],
        )
    )
    title_stmt.append(resp_stmt)
    file_desc.append(title_stmt)

    publication_stmt = _element("publicationStmt")
    publication_stmt.append(_element("publisher", text="Open Christian Data"))
    availability = _element("availability", {"status": "restricted"})
    availability.append(
        _element(
            "p",
            text="Nonaccepted technical reconstruction. Human textual acceptance, rights clearance, and publication authorization are not claimed.",
        )
    )
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)

    source_desc = _element("sourceDesc")
    bibl = _element("bibl", {"type": "retained-ccel-thml-witness"})
    bibl.append(_element("title", text=metadata["title"]))
    bibl.append(_element("author", text=metadata["author"]))
    bibl.append(
        _element(
            "ref",
            {"target": "https://www.ccel.org/ccel/murray/surrender.xml"},
            SOURCE_PATH,
        )
    )
    bibl.append(_element("idno", {"type": "source-sha256"}, source_sha256))
    bibl.append(
        _element(
            "note",
            {
                "type": "source-print-claim",
                "xml:id": "murray-absolute-surrender-header-print-claim",
            },
            metadata["print_claim"],
        )
    )
    bibl.append(
        _element(
            "note",
            {
                "type": "source-editorial-comment",
                "xml:id": "murray-absolute-surrender-header-editorial-note",
            },
            metadata["editorial_comment"],
        )
    )
    bibl.append(
        _element(
            "note",
            {
                "type": "source-proofing-subjects",
                "xml:id": "murray-absolute-surrender-header-subjects",
            },
            metadata["subjects"],
        )
    )
    bibl.append(
        _element(
            "note",
            {
                "type": "source-provider-claim",
                "xml:id": "murray-absolute-surrender-header-provider",
            },
            metadata["provider"],
        )
    )
    bibl.append(
        _element(
            "note",
            {
                "type": "source-rights-claim",
                "xml:id": "murray-absolute-surrender-header-rights-claim",
            },
            metadata["rights_claim"],
        )
    )
    bibl.append(
        _element(
            "note",
            {
                "type": "source-language-claim",
                "xml:id": "murray-absolute-surrender-header-language",
            },
            f"{metadata['language']} ({metadata['language_scheme']})",
        )
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)

    encoding_desc = _element("encodingDesc")
    encoding_desc.append(
        _element(
            "p",
            text="The complete retained ThML header and body carriers, source attributes, direct text, tails, and non-element events are enumerated in the candidate source-accountability file. Header-only CSS and selector directives are recorded there and are not presented as book text.",
        )
    )
    header.append(encoding_desc)
    return header


def _metadata_authority_record(root: etree._Element) -> dict[str, str]:
    metadata = _source_metadata(root)
    return metadata


def _validate_inputs(
    source_manifest: SourceManifest,
    content: bytes,
    config_bytes: bytes,
    profile_bytes: bytes,
    metadata_bytes: bytes,
    attribution_bytes: bytes,
) -> tuple[dict[str, Any], dict[str, Any], etree._Element, etree._Element]:
    if _sha(content) != SOURCE_SHA256:
        raise ValueError("retained Murray ThML source hash does not match the current claim")
    if len(content) != 217645:
        raise ValueError("retained Murray ThML byte count does not match the current claim")
    profile = _strict_json(profile_bytes, "Murray reconstruction profile")
    config = _strict_json(config_bytes, "Murray source config")
    metadata_sidecar = _strict_json(metadata_bytes, "Murray source metadata sidecar")
    if profile.get("contract") != PROFILE_CONTRACT or profile.get("work_id") != WORK_ID:
        raise ValueError("Murray reconstruction profile identity mismatch")
    if profile.get("source_id") != SOURCE_ID:
        raise ValueError("Murray reconstruction profile source identity mismatch")
    if config.get("resource_id") != WORK_ID or config.get("title") != "Absolute Surrender":
        raise ValueError("Murray source config identity mismatch")
    if config.get("source_hash") != f"sha256:{SOURCE_SHA256}":
        raise ValueError("Murray source config retained hash mismatch")
    if config.get("source_file", "").replace("\\", "/") != SOURCE_PATH:
        raise ValueError("Murray source config path mismatch")
    if metadata_sidecar.get("schema_version") != "source-metadata-sidecar-v1":
        raise ValueError("Murray source metadata sidecar contract mismatch")
    if metadata_sidecar.get("subject") != {"id": WORK_ID, "kind": "catalog"}:
        raise ValueError("Murray source metadata sidecar identity mismatch")
    if b"Christian Classics Ethereal Library (CCEL)" not in attribution_bytes:
        raise ValueError("the data-side CCEL attribution notice is absent")
    if b"Do not sell CCEL files" not in attribution_bytes:
        raise ValueError("the data-side CCEL formatting restriction notice is absent")
    if source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("Murray source manifest source_id mismatch")
    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Murray source manifest work_id mismatch")

    root = _parse_source(content)
    bodies = [node for node in root if isinstance(node.tag, str) and _local(node) == "ThML.body"]
    if len(bodies) != 1:
        raise ValueError("retained Murray ThML must contain exactly one direct ThML.body")
    body = bodies[0]
    return config, profile, root, body


def _validate_profile(
    content: bytes,
    profile: dict[str, Any],
    root: etree._Element,
    body: etree._Element,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    body_elements = [node for node in body.iter() if isinstance(node.tag, str)]
    element_counts = Counter(_local(node) for node in elements)
    body_counts = Counter(_local(node) for node in body_elements)
    attributes = [value for node in elements for value in node.attrib.values()]
    id_values = [node.get("id") for node in elements if node.get("id")]
    ordered_divisions = [
        {"id": node.get("id"), "title": node.get("title")}
        for node in body
        if isinstance(node.tag, str) and _local(node) == "div1"
    ]
    expected = profile["source_carriers"]
    if (
        len(elements) != expected.get("element_count")
        or len(attributes) != expected.get("attribute_count")
        or len(id_values) != expected.get("unique_id_attribute_count")
        or len(set(id_values)) != expected.get("unique_id_attribute_count")
        or len(body_elements) != expected.get("body_element_count")
        or {key: element_counts[key] for key in sorted(element_counts)}
        != expected.get("element_counts")
        or {key: body_counts[key] for key in sorted(body_counts)}
        != expected.get("body_element_counts")
        or ordered_divisions
        != [{"id": row["id"], "title": row["title"]} for row in profile["ordered_divisions"]]
    ):
        raise ValueError("Murray source feature profile no longer matches the retained ThML")
    if len(re.findall(r"&(?:amp|lt|gt|quot|apos);", content.decode("utf-8"))) != expected.get("entity_reference_count"):
        raise ValueError("Murray XML entity reference count drifted")
    if content.decode("utf-8").count("\ufffd") != expected.get("replacement_character_count"):
        raise ValueError("Murray source replacement-character count drifted")
    events = _non_element_events(content)
    event_counts = Counter(str(row["kind"]) for row in events)
    expected_events = profile["non_element_events"]
    if (
        event_counts["comment"] != expected_events.get("comment_count")
        or event_counts["pi"] != expected_events.get("processing_instruction_count")
        or event_counts["doctype"] != expected_events.get("doctype_declaration_count")
    ):
        raise ValueError("Murray non-element event profile no longer matches the retained bytes")
    if any(_local(node) not in BODY_TAGS | {"ThML.body"} for node in body_elements):
        raise ValueError("Murray ThML body contains an unsupported element")
    return _features(root, body), events


def _source_accountability(
    features: list[dict[str, object]],
    events: list[dict[str, object]],
    profile: dict[str, Any],
) -> dict[str, object]:
    counts = profile["source_carriers"]
    dispositions = Counter(str(row["disposition"]) for row in features)
    return {
        "contract": ACCOUNTABILITY_CONTRACT,
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "profile_id": profile["profile_id"],
        "member_census": [
            {
                "path": SOURCE_PATH,
                "bytes": 217645,
                "sha256": SOURCE_SHA256,
                "scope": "whole ThML document including complete header and body",
                "disposition": "included",
            }
        ],
        "counts": {
            "source_elements": len(features),
            "body_elements": counts["body_element_count"],
            "source_attributes": counts["attribute_count"],
            "unique_id_attributes": counts["unique_id_attribute_count"],
            "comment_events": sum(row["kind"] == "comment" for row in events),
            "processing_instruction_events": sum(row["kind"] == "pi" for row in events),
            "doctype_events": sum(row["kind"] == "doctype" for row in events),
            "unmapped_features": 0,
            "duplicate_features": 0,
            "dispositions": dict(sorted(dispositions.items())),
        },
        "crosswalk": features,
        "non_element_events": events,
        "unmapped_features": [],
        "duplicate_features": [],
    }


def _candidate_readme() -> bytes:
    return (
        "# Murray — Absolute Surrender source note\n\n"
        "This is a nonaccepted, source-bound technical reconstruction for the whole retained ThML document `raw/ccel/murray/surrender.xml` (SHA-256 `"
        + SOURCE_SHA256
        + "`). It represents the title page, nine address divisions, and indexes. The retained header names Claude King as transcriber and labels the CCEL subject `Proofed`; the title page says the text was scanned and corrected by Claude King in September 1999.\n\n"
        "The exact source carrier inventory and explicit dispositions are in `source-accountability.json`. The source describes light editorial changes to language and scripture references. No original-print collation or textual acceptance is claimed.\n\n"
        "The source claims Public Domain, and its CCEL attribution and formatting terms are recorded in `data/structured-text/README.md`. This candidate does not make a rights determination, establish edition identity, or authorize publication. Human acceptance, rights clearance, canonical IR acceptance, and publication remain separate.\n"
    ).encode("utf-8")


def _provenance(
    source_manifest: SourceManifest,
    source_content: bytes,
    config_bytes: bytes,
    metadata_bytes: bytes,
    attribution_bytes: bytes,
    profile: dict[str, Any],
    metadata: dict[str, str],
) -> dict[str, object]:
    authorities = {
        str(row["name"]): dict(row) for row in source_manifest.record["authorities"]
    }
    config = _strict_json(config_bytes, "Murray source config")
    return {
        "contract": "ocd-murray-absolute-surrender-provenance-v1",
        "status": "nonaccepted",
        "publication_status": "not-authorized",
        "ticket": "37c-256",
        "owner_route": "LIB-055",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source": {
            "path": SOURCE_PATH,
            "bytes": len(source_content),
            "sha256": _sha(source_content),
            "scope": "complete ThML document, including the full source header and ThML.body",
            "member_count": 1,
            "profile_id": profile["profile_id"],
        },
        "work_binding": {
            "path": authorities["work-identity-config"]["path"],
            "sha256": _sha(config_bytes),
            "legacy_parser_output": "data/structured-text/murray-absolute-surrender.json",
            "legacy_output_used_as_reconstruction_authority": False,
        },
        "metadata_evidence": {
            "path": authorities["source-metadata-sidecar"]["path"],
            "sha256": _sha(metadata_bytes),
            "contract": "source-metadata-sidecar-v1",
            "subject": {"kind": "catalog", "id": WORK_ID},
            "adoption_scope": "existing inspected META-002/003 source-evidence projection; no config, generated-data, or index mutation",
        },
        "data_attribution": {
            "path": authorities["data-attribution-readme"]["path"],
            "sha256": _sha(attribution_bytes),
            "delivered_notice": True,
        },
        "source_quality": {
            "classification": "human-correction-explicitly-attested-for-exact-retained-source",
            "transcriber": metadata["transcriber"],
            "proofed_subject": "Proofed",
            "title_page_attestation": "Scanned and corrected by Claude King, September 1999.",
            "editorial_comment": metadata["editorial_comment"],
            "limits": list(profile["human_correction_attestation"]["limits"]),
        },
        "identity": {
            "status": "retained-witness-bound; canonical work and edition questions remain unresolved",
            "title": metadata["title"],
            "author": metadata["author"],
            "source_print_claim": metadata["print_claim"],
            "legacy_config_edition_claim": config.get("source_edition"),
            "print_collation": "not performed",
        },
        "rights": {
            "status": "unreviewed",
            "source_claim": metadata["rights_claim"],
            "ccel_terms_notice": authorities["data-attribution-readme"]["path"],
            "publication_authorized": False,
        },
        "human_acceptance": {"status": "not-recorded"},
        "producer": {
            "id": CONVERTER_ID,
            "version": CONVERTER_VERSION,
            "callable": "_convert",
            "path": "build/tei/murray_absolute_surrender_reconstruction.py",
        },
        "independent_verifier": {
            "id": "ocd-murray-absolute-surrender-independent-thml-oracle",
            "version": "1",
            "path": "build/tei/murray_absolute_surrender_oracle.py",
            "source_reader_independent_of_producer": True,
        },
    }


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    source_content = _authority_bytes(source_manifest, "retained-source")
    config_bytes = _authority_bytes(source_manifest, "work-identity-config")
    profile_bytes = _authority_bytes(source_manifest, "reconstruction-profile")
    metadata_bytes = _authority_bytes(source_manifest, "source-metadata-sidecar")
    attribution_bytes = _authority_bytes(source_manifest, "data-attribution-readme")
    config, profile, root, body = _validate_inputs(
        source_manifest,
        source_content,
        config_bytes,
        profile_bytes,
        metadata_bytes,
        attribution_bytes,
    )
    features, events = _validate_profile(source_content, profile, root, body)
    metadata = _metadata_authority_record(root)
    ordinal_by_element = {
        node: ordinal
        for ordinal, node in enumerate(
            (item for item in root.iter() if isinstance(item.tag, str)), 1
        )
    }
    feature_target_ids = [row["target_xml_id"] for row in features if row["target_xml_id"]]
    if len(feature_target_ids) != len(set(feature_target_ids)):
        raise ValueError("Murray source-to-TEI crosswalk contains duplicate target IDs")

    tei = _element("TEI", {"xml:id": WORK_ID})
    tei.append(_header(metadata, _sha(source_content)))
    text = _element("text", {"xml:id": f"{WORK_ID}-text"})
    front = _element("front")
    tei_body = _element("body")
    back = _element("back")
    for child in body:
        if not isinstance(child.tag, str):
            raise ValueError("Murray ThML.body contains a non-element top-level carrier")
        if _local(child) != "div1":
            raise ValueError(f"unexpected ThML.body child <{_local(child)}> at {_selector(child)}")
        converted = _convert_body_element(child, ordinal_by_element)
        converted.tail = child.tail
        if child.get("id") == "i":
            front.append(converted)
        elif child.get("id") == "xi":
            back.append(converted)
        else:
            tei_body.append(converted)
    if not len(front) or len(tei_body) != 9 or len(back) != 1:
        raise ValueError("Murray top-level source divisions do not match title/address/index scope")
    _append_text(text, body.text)
    text.append(front)
    text.append(tei_body)
    text.append(back)
    text.tail = body.tail
    tei.append(text)

    # Keep every generated TEI xml:id unique, including the mapped source ids.
    tei_ids = [node.get(f"{{{XML_NS}}}id") for node in tei.iter() if node.get(f"{{{XML_NS}}}id")]
    if len(tei_ids) != len(set(tei_ids)):
        raise ValueError("Murray TEI output contains duplicate xml:id values")

    accountability = _source_accountability(features, events, profile)
    unresolved_lines = b"".join(
        _canonical(item) for item in profile.get("unresolved", [])
    )
    return {
        "content.tei.xml": etree.tostring(
            tei, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(
            _provenance(
                source_manifest,
                source_content,
                config_bytes,
                metadata_bytes,
                attribution_bytes,
                profile,
                metadata,
            )
        ),
        "unresolved.jsonl": unresolved_lines,
        "README.source.md": _candidate_readme(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
