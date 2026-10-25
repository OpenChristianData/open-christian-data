"""Deterministic retained-CCEL XML to nonaccepted LIB-035 TEI corpus."""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-expositors-bible-lib035-retained-xml-to-tei"
CONVERTER_VERSION = "2"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SAFE_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
_EXTRA_ENTITIES = {
    "&emdash;": "-",
    "&mdash;": "-",
    "&ndash;": "-",
    "&lsquo;": "'",
    "&rsquo;": "'",
    "&ldquo;": '"',
    "&rdquo;": '"',
    "&nbsp;": " ",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _replace_entity(match: re.Match[str]) -> str:
    entity = match.group(0)
    if entity in _SAFE_ENTITIES:
        return entity
    if entity in _EXTRA_ENTITIES:
        return _EXTRA_ENTITIES[entity]
    replacement = html.unescape(entity)
    return "" if replacement == entity else replacement


def _prepared_xml(content: bytes) -> bytes:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^]]*\])?>", "", text, flags=re.DOTALL)
    return re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text).encode("utf-8")


def _parse(content: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    try:
        return etree.fromstring(_prepared_xml(content), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained LIB-035 XML is not parseable") from exc


def _local_name(value: str) -> str:
    return etree.QName(value).localname


def _selector(element: etree._Element, root: etree._Element) -> str:
    parts: list[str] = []
    current = element
    while True:
        parent = current.getparent()
        tag = _local_name(current.tag)
        if parent is None:
            parts.append(f"{tag}[1]")
            break
        peers = [
            child
            for child in parent
            if isinstance(child.tag, str) and _local_name(child.tag) == tag
        ]
        parts.append(f"{tag}[{peers.index(current) + 1}]")
        current = parent
    if current is not root:
        raise ValueError("LIB-035 source element escaped its document")
    return "/" + "/".join(reversed(parts))


def _feature_inventory(content: bytes, member_id: str) -> tuple[dict[str, object], ...]:
    root = _parse(content)
    elements = [item for item in root.iter() if isinstance(item.tag, str)]
    ordinal_by_identity = {id(item): ordinal for ordinal, item in enumerate(elements, 1)}
    records: list[dict[str, object]] = []
    for ordinal, element in enumerate(elements, 1):
        parent = element.getparent()
        siblings = (
            [item for item in parent if isinstance(item.tag, str)]
            if parent is not None
            else [element]
        )
        # Preserve Clark-qualified attribute names verbatim.  Local-name
        # collapse would conflate distinct retained attributes such as lang
        # and xml:lang on retained Skinner spans.
        attributes = {str(name): value for name, value in sorted(element.attrib.items())}
        direct = element.text or ""
        tail = element.tail or ""
        records.append(
            {
                "feature_id": f"{member_id}-feature-{ordinal:05d}",
                "source_selector": _selector(element, root),
                "source_tag": _local_name(element.tag),
                "source_attributes": attributes,
                "source_direct_text": direct,
                "source_tail_text": tail,
                "source_direct_text_sha256": _sha(direct.encode("utf-8")),
                "source_tail_text_sha256": _sha(tail.encode("utf-8")),
                "source_parent_ordinal": (
                    ordinal_by_identity[id(parent)] if parent is not None else None
                ),
                "source_child_ordinal": siblings.index(element) + 1,
                "tei_xml_id": f"{member_id}-feature-{ordinal:05d}",
            }
        )
    return tuple(records)


def _element(name: str, attributes: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    node = etree.Element(f"{{{_TEI_NS}}}{name}")
    for key, value in (attributes or {}).items():
        node.set(_XML_ID if key == "xml:id" else key, value)
    node.text = text
    return node



def _text_correction_id(row: Mapping[str, object]) -> str:
    fields = (
        "member_id", "source_selector", "source_field", "source_value_sha256",
        "start", "end", "sic", "corr", "witness_url",
    )
    return _sha("\\0".join(str(row[field]) for field in fields).encode("utf-8"))


def _index_text_corrections(rows: object):
    if not isinstance(rows, list):
        raise ValueError("LIB-035 text corrections must be a list")
    result = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("LIB-035 text correction row must be an object")
        key = (str(row["member_id"]), str(row["source_selector"]), str(row["source_field"]))
        result.setdefault(key, []).append((row, _text_correction_id(row)))
    for values in result.values():
        values.sort(key=lambda item: (int(item[0]["start"]), int(item[0]["end"])))
    return result


def _source_text_segment(segment_type, value, member_id, selector, source_field, correction_index, used_corrections):
    segment = _element("seg", {"type": segment_type})
    corrections = correction_index.get((member_id, selector, source_field), [])
    if not corrections:
        segment.text = value or None
        return segment
    value_sha256 = _sha(value.encode("utf-8"))
    cursor = 0
    previous = None
    for row, correction_id in corrections:
        start, end = int(row["start"]), int(row["end"])
        if (
            row["source_value_sha256"] != value_sha256
            or start < cursor or end <= start or value[start:end] != str(row["sic"])
            or row["source_field"] != source_field
            or row["member_id"] != member_id
            or row["source_selector"] != selector
            or not str(row["witness_url"]).startswith("https://www.gutenberg.org/")
        ):
            raise ValueError(f"LIB-035 correction is not bound to exact source span: {selector}")
        if correction_id in used_corrections:
            raise ValueError(f"LIB-035 duplicate text correction: {correction_id}")
        if previous is None:
            segment.text = value[cursor:start] or None
        else:
            previous.tail = value[cursor:start] or None
        choice = _element("choice", {
            "corresp": "urn:ocd:source-text-correction:" + correction_id,
            "resp": str(row["witness_url"]),
        })
        choice.append(_element("sic", text=str(row["sic"])))
        choice.append(_element("corr", text=str(row["corr"])))
        segment.append(choice)
        previous = choice
        cursor = end
        used_corrections.add(correction_id)
    if previous is not None:
        previous.tail = value[cursor:] or None
    return segment


def _work_tei(
    work: Mapping[str, object],
    member_rows: list[tuple[Mapping[str, object], bytes, tuple[dict[str, object], ...]]],
    correction_index,
    used_corrections: set[str],
) -> etree._Element:
    tei = _element("TEI", {"xml:id": str(work["work_id"])})
    header = _element("teiHeader")
    file_desc = _element("fileDesc")
    title_stmt = _element("titleStmt")
    title_stmt.append(_element("title", text="The Expositor's Bible"))
    title_stmt.append(_element("author", text=str(work["author"])))
    editor = _element("respStmt")
    editor.append(_element("resp", text="Series editor"))
    editor.append(_element("name", text="William Robertson Nicoll"))
    title_stmt.append(editor)
    file_desc.append(title_stmt)
    publication = _element("publicationStmt")
    publication.append(_element("publisher", text="Open Christian Data"))
    availability = _element("availability", {"status": "restricted"})
    availability.append(
        _element(
            "p",
            text=(
                "Nonaccepted reconstruction candidate. Underlying texts are stated public "
                "domain; CCEL file and formatting conditions and publication rights require "
                "human review. Attribution is supplied separately."
            ),
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _element("sourceDesc")
    source_desc.append(
        _element(
            "p",
            text=" | ".join(
                f"{member['source_title']} [{_sha(content)}] {member['source_url']} "
                f"(print statement: {member['print_source']})"
                for member, content, _ in member_rows
            ),
        )
    )
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)
    text = _element("text")
    body = _element("body")
    for member, content, features in member_rows:
        division = _element(
            "div",
            {"xml:id": str(member["member_id"]), "type": "retained-source-member"},
        )
        division.append(_element("head", text=str(member["source_title"])))
        encoded = base64.b64encode(content).decode("ascii")
        division.append(
            _element(
                "note",
                {
                    "type": "exact-retained-source-bytes",
                    "subtype": "base64",
                    "n": _sha(content),
                },
                encoded,
            )
        )
        transcription = _element("div", {"type": "parsed-xml-feature-transcription"})
        for feature in features:
            block = _element(
                "ab",
                {
                    "xml:id": str(feature["tei_xml_id"]),
                    "type": "source-xml-element",
                    "subtype": str(feature["source_tag"]),
                    "n": str(feature["source_child_ordinal"]),
                    "corresp": "urn:source-xpath:" + quote(str(feature["source_selector"]), safe=""),
                },
            )
            block.append(_source_text_segment(
                "direct-text", str(feature["source_direct_text"]), str(member["member_id"]),
                str(feature["source_selector"]), "text", correction_index, used_corrections,
            ))
            block.append(_source_text_segment(
                "tail-text", str(feature["source_tail_text"]), str(member["member_id"]),
                str(feature["source_selector"]), "tail", correction_index, used_corrections,
            ))
            transcription.append(block)
        division.append(transcription)
        body.append(division)
    text.append(body)
    tei.append(text)
    return tei


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    """Return the exact five non-manifest LIB-035 candidate members."""

    source_manifest.verify()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    if (
        profile.get("contract") != "ocd-expositors-bible-lib035-profile-v1"
        or profile.get("profile_id") != "expositors-bible-lib035-complete-current-claim-xml-v1"
    ):
        raise ValueError("LIB-035 reconstruction profile identity mismatch")
    configured_members = profile.get("included_members")
    works = profile.get("works")
    if not isinstance(configured_members, list) or len(configured_members) != 9:
        raise ValueError("LIB-035 requires exactly nine retained members")
    if not isinstance(works, list) or len(works) != 5:
        raise ValueError("LIB-035 requires exactly five frozen works")
    if profile.get("text_correction_contract") != "ocd-expositors-bible-edition-witness-token-corrections-v1":
        raise ValueError("LIB-035 edition-witness correction contract is missing")
    correction_rows = profile.get("text_corrections")
    correction_index = _index_text_corrections(correction_rows)
    used_corrections: set[str] = set()
    authority_by_name = {
        str(item["name"]): item for item in source_manifest.record["authorities"]
    }
    grouped: dict[str, list[tuple[Mapping[str, object], bytes, tuple[dict[str, object], ...]]]] = {
        str(work["work_id"]): [] for work in works
    }
    all_crosswalk: list[dict[str, object]] = []
    member_accounting = []
    for member in configured_members:
        authority_name = str(member["authority_name"])
        authority = authority_by_name.get(authority_name)
        if authority is None or authority.get("role") != "primary-source":
            raise ValueError(f"LIB-035 retained authority missing: {authority_name}")
        content = source_manifest.authority_path(authority_name).read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError(f"LIB-035 retained member drifted: {authority_name}")
        features = _feature_inventory(content, str(member["member_id"]))
        if len(features) != member["xml_element_count"]:
            raise ValueError(f"LIB-035 XML element count drifted: {authority_name}")
        work_id = str(member["work_id"])
        if work_id not in grouped:
            raise ValueError("LIB-035 member escaped frozen work scope")
        grouped[work_id].append((member, content, features))
        all_crosswalk.extend(
            {
                **feature,
                "member_id": member["member_id"],
                "work_id": work_id,
                "disposition": "represented",
                "tei_selector": f"#{feature['tei_xml_id']}",
            }
            for feature in features
        )
        member_accounting.append(
            {
                "member_id": member["member_id"],
                "work_id": work_id,
                "path": authority["path"],
                "bytes": len(content),
                "sha256": _sha(content),
                "xml_element_count": len(features),
                "disposition": "included",
                "reason": member["reason"],
            }
        )
    corpus = _element("teiCorpus", {"xml:id": "expositors-bible-lib035-corpus"})
    corpus_header = _element("teiHeader")
    corpus_file_desc = _element("fileDesc")
    corpus_title_stmt = _element("titleStmt")
    corpus_title_stmt.append(_element("title", text="The Expositor's Bible: LIB-035 retained-source corpus"))
    corpus_file_desc.append(corpus_title_stmt)
    corpus_publication = _element("publicationStmt")
    corpus_publication.append(_element("publisher", text="Open Christian Data"))
    corpus_availability = _element("availability", {"status": "restricted"})
    corpus_availability.append(_element("p", text="Nonaccepted candidate; not publication-ready."))
    corpus_publication.append(corpus_availability)
    corpus_file_desc.append(corpus_publication)
    corpus_source = _element("sourceDesc")
    corpus_source.append(_element("p", text="Nine exact retained CCEL XML members across five frozen works."))
    corpus_file_desc.append(corpus_source)
    corpus_header.append(corpus_file_desc)
    corpus.append(corpus_header)
    for work in works:
        rows = grouped[str(work["work_id"])]
        if len(rows) != work["member_count"]:
            raise ValueError("LIB-035 work/member lineage drifted")
        corpus.append(_work_tei(work, rows, correction_index, used_corrections))
    expected_corrections = {
        _text_correction_id(row) for row in correction_rows if isinstance(row, Mapping)
    }
    if used_corrections != expected_corrections:
        raise ValueError("LIB-035 did not apply every profile-bound text correction exactly once")
    tei_bytes = etree.tostring(
        corpus, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    excluded = profile.get("excluded_members")
    if not isinstance(excluded, list) or len(excluded) != 38:
        raise ValueError("LIB-035 retained-family exclusion census is incomplete")
    census = {
        "contract": "ocd-expositors-bible-lib035-member-census-v1",
        "included": member_accounting,
        "excluded": excluded,
        "counts": {"included": 9, "excluded": 38, "retained_family_total": 47},
        "inventory_contradiction": profile["inventory_contradiction"],
    }
    namespace_collision = profile.get("namespace_attribute_collision")
    if not isinstance(namespace_collision, dict):
        raise ValueError("LIB-035 namespace-attribute collision authority is missing")
    collision_rows = [
        item
        for item in all_crosswalk
        if item["member_id"] == namespace_collision.get("member_id")
        and item["source_tag"] == namespace_collision.get("source_tag")
        and all(key in item["source_attributes"] for key in namespace_collision.get("distinct_keys", []))
    ]
    if len(collision_rows) != namespace_collision.get("count"):
        raise ValueError("LIB-035 namespace-qualified attribute census drifted")
    accountability = {
        "contract": "ocd-expositors-bible-lib035-source-accountability-v1",
        "schema": "lib035.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_member_count": 9,
        "work_count": 5,
        "source_bytes": sum(int(item["bytes"]) for item in member_accounting),
        "feature_count": len(all_crosswalk),
        "omitted_feature_count": 0,
        "unresolved_feature_count": 0,
        "member_census": census,
        "crosswalk": all_crosswalk,
    }
    authority_bindings = {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-expositors-bible-lib035-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket": "LIB-035",
        "work_ids": [work["work_id"] for work in works],
        "authorities": authority_bindings,
        "member_census_sha256": _sha(_canonical(census)),
        "legacy_current_claims": profile["legacy_current_claims"],
        "rights": {
            "publication_authorized": False,
            "status": "human-review-required",
            "ccel_permission_authority": "ccel-permission",
            "attribution_deliverable": "data/commentaries/expositors-bible/README.md",
        },
        "identity": {
            "status": "retained-witness-metadata-only",
            "print_collation": "not performed",
            "canonical_identity_decided": False,
        },
    }
    unresolved = [
        {
            "id": "lib035-print-edition-collation-not-performed",
            "status": "unresolved",
            "scope": "all nine retained members",
            "reason": "Retained CCEL witness statements were preserved but not collated against print copies.",
        },
        {
            "id": "lib035-rights-and-publication-review",
            "status": "unresolved",
            "scope": "candidate corpus",
            "reason": "Technical validation does not decide rights acceptance or publication readiness.",
        },
        {
            "id": "lib035-retained-inventory-47-vs-legacy-48",
            "status": "unresolved",
            "scope": "Expositor's Bible family inventory",
            "reason": str(profile["inventory_contradiction"]),
        },
        {
            "id": "lib035-author-label-variants",
            "status": "unresolved",
            "scope": "horton-expositorprov, kellogg-expositor3, edwards-tc-expositorheb",
            "reason": "Retained abbreviated and titled creator strings differ from frozen work labels; no canonical identity normalization is asserted.",
        },
    ]
    readme = (
        "# LIB-035 source note\n\n"
        "This is a nonaccepted, nonpublication reconstruction candidate for five frozen "
        "Expositor's Bible work identities. It embeds the exact bytes of nine retained "
        "CCEL ThML/XML members and inventories every parsed XML element.\n\n"
        "Source files were sourced via CCEL.org. CCEL permits parsing these ThML/XML files; "
        "do not sell CCEL files or derivatives of their formatting. See the digest-bound "
        "source-local permission record.\n\n"
        "No print collation, human textual acceptance, canonical identity decision, rights "
        "acceptance, or publication authorization is claimed.\n"
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

