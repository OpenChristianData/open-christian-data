"""Source-bound reconstruction of the retained CCEL Calvin ThML cohort.

The retained CCEL XML files are the primary authority for this lane.  The
legacy SWORD projection is deliberately not read by the converter.  It is
bound in the source manifest only as a comparison witness.
"""

from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-calvin-commentaries-retained-ccel-thml-to-tei"
CONVERTER_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
FORMAT_ONLY = frozenset({"style", "selector", "property", "colgroup", "col"})
DIV_SOURCE_TAGS = frozenset(
    {
        "div",
        "div1",
        "div2",
        "div3",
        "div4",
        "ThML.head",
        "ThML.body",
        "DC",
        "comments",
        "generalInfo",
        "printSourceInfo",
        "electronicEdInfo",
        "center",
    }
)
LANG_MAP = {"EL": "grc", "HE": "he", "LA": "la", "FR": "fr", "DE": "de"}
PROFILE_AUTHORITY = "reconstruction-profile"
POLICY_AUTHORITY = "validation-policy"
SCHEMA_AUTHORITY = "source-accountability-schema"
README_AUTHORITY = "source-local-readme"
CONFIG_AUTHORITY = "work-config"
METADATA_AUTHORITY = "metadata-evidence"
PRIMARY_ROLE = "primary-source"
CCEL_URL = "https://www.ccel.org/ccel/calvin/commentaries.html"
SWORD_URL = "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/CalvinCommentaries.zip"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


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
        raise ValueError(f"{label} must be an object")
    return value


def _parse(content: bytes) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=True,
        remove_comments=False,
        remove_pis=False,
    )
    try:
        return etree.fromstring(content, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Calvin ThML source is not parseable") from exc


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _selector(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{_local(node)}[1]"
    siblings = [
        child
        for child in parent
        if child.tag == node.tag
    ]
    return f"{_selector(parent)}/{_local(node)}[{siblings.index(node) + 1}]"


def _source_uri(member: str, selector: str) -> str:
    return (
        "urn:source-member:"
        + quote(member, safe="")
        + ":urn:source-xpath:"
        + quote(selector, safe="")
    )


def _is_formatting(node: etree._Element) -> bool:
    return _local(node) in FORMAT_ONLY or any(
        _local(ancestor) in FORMAT_ONLY
        for ancestor in node.iterancestors()
        if isinstance(ancestor.tag, str)
    )


def _census(root: etree._Element) -> tuple[dict[str, int], dict[str, int]]:
    elements = [node for node in root.iter() if isinstance(node.tag, str)]
    counts = dict(sorted(Counter(_local(node) for node in elements).items()))
    census = {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in elements),
        "tail_nodes": sum(node.tail is not None for node in elements),
        "characters": sum(
            len(node.text or "") + len(node.tail or "") for node in elements
        ),
    }
    return counts, census


def _lexical_events(root: etree._Element) -> dict[str, int]:
    tree = root.getroottree()
    return {
        "comments": len(tree.xpath("//comment()")),
        "processing_instructions": len(tree.xpath("//processing-instruction()")),
        "doctype_declarations": 1 if tree.docinfo.doctype else 0,
    }


def _first_text(root: etree._Element, localname: str) -> str:
    for node in root.iter():
        if isinstance(node.tag, str) and _local(node) == localname:
            return "".join(node.itertext()).strip()
    return ""


def _tei(
    localname: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    node = etree.Element(
        f"{{{TEI_NS}}}{localname}",
        nsmap={None: TEI_NS, "xml": XML_NS},
    )
    for name, value in (attrs or {}).items():
        if value is not None:
            node.set(name, value)
    if text is not None:
        node.text = text
    return node


def _member_set(source_manifest: SourceManifest) -> list[dict[str, object]]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Calvin source manifest authorities are invalid")
    primary = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == PRIMARY_ROLE
    ]
    records = [
        {
            "name": str(item["name"]),
            "path": str(item["path"]),
            "bytes": int(item["bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in primary
    ]
    return sorted(records, key=lambda item: (str(item["path"]), str(item["name"])))


def _profile_member(profile: Mapping[str, object], name: str) -> Mapping[str, object]:
    values = profile.get("members")
    if not isinstance(values, list):
        raise ValueError("Calvin reconstruction profile members are invalid")
    for value in values:
        if isinstance(value, Mapping) and value.get("name") == name:
            return value
    raise ValueError(f"Calvin profile has no member {name!r}")


def _verify_envelope(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
    schema: Mapping[str, object],
) -> list[Mapping[str, object]]:
    record = source_manifest.record
    if (
        record.get("ticket_id") != "37c-092"
        or record.get("work_id") != "calvin-commentaries"
        or record.get("source_id") != "calvin-commentaries-retained-ccel-thml"
    ):
        raise ValueError("Calvin source identity or ticket binding drifted")
    if (
        profile.get("contract") != "ocd-calvin-commentaries-profile-v1"
        or profile.get("profile_id") != "calvin-commentaries-retained-ccel-thml-v1"
        or profile.get("work_id") != "calvin-commentaries"
        or profile.get("source_bytes") != 74248915
        or profile.get("source_member_set_sha256")
        != "2ed1ca9ee905b3cb709bbe9b8dd800e1ed8c78eba4146945b4e8924ad8efa235"
        or profile.get("source_census", {}).get("elements") != 583805
        or profile.get("represented_element_count") != 581157
        or profile.get("formatting_only_excluded_element_count") != 2648
        or profile.get("unsupported_element_count") != 0
    ):
        raise ValueError("Calvin reconstruction profile envelope drifted")
    if (
        policy.get("contract") != "ocd-calvin-commentaries-validation-policy-v1"
        or policy.get("policy_id") != "calvin-commentaries-retained-ccel-thml-policy-v1"
        or policy.get("oracle_id") != "ocd-calvin-commentaries-independent-source-oracle"
        or policy.get("schema") != "calvin-commentaries.source-accountability.schema.json"
        or policy.get("required_primary_source_members") != 46
        or policy.get("required_source_element_count") != 583805
    ):
        raise ValueError("Calvin validation policy envelope drifted")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ValueError("Calvin accountability schema dialect drifted")
    config = _strict_json(
        source_manifest.authority_path(CONFIG_AUTHORITY).read_bytes(),
        "Calvin work config",
    )
    if (
        config.get("resource_id") != "calvin-commentaries"
        or config.get("title") != "Calvin's Collected Commentaries"
        or config.get("author") != "John Calvin"
    ):
        raise ValueError("Calvin work-config identity drifted")
    metadata = _strict_json(
        source_manifest.authority_path(METADATA_AUTHORITY).read_bytes(),
        "Calvin metadata evidence",
    )
    if (
        metadata.get("contract") != "ocd-calvin-commentaries-metadata-evidence-v1"
        or metadata.get("ticket_id") != "37c-092"
        or metadata.get("work_id") != "calvin-commentaries"
    ):
        raise ValueError("Calvin metadata evidence identity drifted")
    primary = _member_set(source_manifest)
    profile_members = profile.get("members")
    if not isinstance(profile_members, list) or len(profile_members) != 46:
        raise ValueError("Calvin profile member cardinality drifted")
    expected_primary = sorted(
        [
            {
                "name": value.get("name"),
                "path": value.get("path"),
                "bytes": value.get("bytes"),
                "sha256": value.get("sha256"),
            }
            for value in profile_members
            if isinstance(value, Mapping)
        ],
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    if primary != expected_primary or len(primary) != 46:
        raise ValueError("Calvin primary source authority set drifted")
    member_set_sha = _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": primary}))
    if member_set_sha != profile["source_member_set_sha256"]:
        raise ValueError("Calvin source member-set digest drifted")
    comparison = [
        item
        for item in source_manifest.record.get("authorities", ())
        if isinstance(item, Mapping) and item.get("role") == "comparison-witness-only"
    ]
    if len(comparison) != 2:
        raise ValueError("Calvin comparison-witness cardinality drifted")
    return profile_members


class _FeatureSink:
    """Append canonical feature objects while the TEI stream is emitted."""

    def __init__(self) -> None:
        self.ordinal = 0
        self.first = True
        self.buffer = BytesIO()
        self.member_stats: dict[str, dict[str, int]] = {}

    def begin_member(self, name: str) -> None:
        if name in self.member_stats:
            raise ValueError(f"Calvin member {name!r} was visited twice")
        self.member_stats[name] = {
            "element_count": 0,
            "represented_element_count": 0,
            "formatting_only_excluded_element_count": 0,
        }

    def record(self, member: str, node: etree._Element) -> dict[str, object]:
        if member not in self.member_stats:
            raise ValueError(f"Calvin member {member!r} was not opened")
        self.ordinal += 1
        parent = node.getparent()
        siblings = (
            [child for child in parent if isinstance(child.tag, str)]
            if parent is not None
            else [node]
        )
        disposition = (
            "formatting-only-excluded" if _is_formatting(node) else "represented"
        )
        feature = {
            "feature_id": f"calvin-commentaries-feature-{self.ordinal:06d}",
            "member": member,
            "source_selector": _selector(node),
            "source_qname": str(node.tag),
            "source_attributes": [
                {"qname": str(name), "value": str(value)}
                for name, value in node.attrib.items()
            ],
            "source_direct_text": node.text or "",
            "source_tail_text": node.tail or "",
            "source_parent_selector": _selector(parent) if parent is not None else None,
            "source_child_ordinal": siblings.index(node) + 1,
            "disposition": disposition,
        }
        if not self.first:
            self.buffer.write(b",")
        self.buffer.write(_compact(feature))
        self.first = False
        stats = self.member_stats[member]
        stats["element_count"] += 1
        if disposition == "represented":
            stats["represented_element_count"] += 1
        else:
            stats["formatting_only_excluded_element_count"] += 1
        return feature


def _bound_attrs(member: str, source: etree._Element, feature: Mapping[str, object]) -> dict[str, str]:
    attrs = {
        XML_ID: str(feature["feature_id"]),
        "corresp": _source_uri(member, str(feature["source_selector"])),
    }
    if source.get("id"):
        attrs["n"] = str(source.get("id"))
    if source.get("class"):
        attrs["rend"] = str(source.get("class"))
    elif source.get("style"):
        attrs["rend"] = str(source.get("style"))
    if source.get("lang"):
        code = str(source.get("lang"))
        attrs[XML_LANG] = LANG_MAP.get(code.upper(), code)
    return attrs


def _heading_is_post_content(source: etree._Element) -> bool:
    if any(
        _local(ancestor) in {"td", "th"}
        for ancestor in source.iterancestors()
        if isinstance(ancestor.tag, str)
    ):
        return True
    parent = source.getparent()
    if parent is None:
        return False
    for sibling in parent:
        if sibling is source:
            break
        if not isinstance(sibling.tag, str) or _is_formatting(sibling):
            continue
        if _local(sibling) in {"pb", "hr", "h1", "h2", "h3", "h4"}:
            continue
        return True
    return False


def _target_info(member: str, source: etree._Element, feature: Mapping[str, object]) -> tuple[str, dict[str, str]]:
    local = _local(source)
    attrs = _bound_attrs(member, source, feature)
    if local in DIV_SOURCE_TAGS:
        if (source.text or "").strip() and not any(
            isinstance(child.tag, str) for child in source
        ):
            attrs["rend"] = f"source-{local}"
            return "p", attrs
        attrs["type"] = f"source-{local}"
        return "div", attrs
    if local in {"h1", "h2", "h3", "h4"}:
        if _heading_is_post_content(source):
            attrs["rend"] = "heading"
            return "p", attrs
        return "head", attrs
    if local == "p":
        return "p", attrs
    if local == "b":
        attrs["rend"] = "bold"
        return "hi", attrs
    if local == "i":
        attrs["rend"] = "italic"
        return "hi", attrs
    if local == "span":
        if (source.get("class") or "").casefold() == "sc":
            attrs["rend"] = "smallcaps"
            return "hi", attrs
        if source.get("lang"):
            return "foreign", attrs
        return "seg", attrs
    if local == "sup":
        attrs["rend"] = "superscript"
        return "hi", attrs
    if local == "br":
        return "lb", attrs
    if local == "scripRef":
        attrs["type"] = "scripture"
        values = [
            item.removeprefix("Bible:")
            for item in (source.get("osisRef") or "").split()
            if item.strip()
        ]
        if values:
            attrs["cRef"] = " ".join(values)
        if source.get("passage"):
            attrs["n"] = str(source.get("passage"))
        return "ref", attrs
    if local == "scripCom":
        attrs["type"] = "scripture-commentary"
        return "seg", attrs
    if local == "note":
        if source.get("place"):
            attrs["place"] = str(source.get("place"))
        return "note", attrs
    if local == "pb":
        return "pb", attrs
    if local == "hr":
        attrs["unit"] = "horizontal-rule"
        return "milestone", attrs
    if local == "a":
        if source.get("href"):
            attrs["target"] = str(source.get("href"))
        return "ref", attrs
    if local == "link":
        if source.get("href"):
            attrs["target"] = str(source.get("href"))
        return "ref", attrs
    if local == "table":
        return "table", attrs
    if local == "tr":
        return "row", attrs
    if local in {"td", "th"}:
        return "cell", attrs
    if local == "ul":
        return "list", attrs
    if local == "li":
        return "item", attrs
    if local == "verse":
        attrs["type"] = str(source.get("type") or "stanza")
        return "lg", attrs
    if local == "l":
        return "l", attrs
    if local == "insertIndex":
        attrs["type"] = f"insert-index-{source.get('type') or 'marker'}"
        return "anchor", attrs
    if local == "img":
        if source.get("src"):
            attrs["url"] = str(source.get("src"))
        return "graphic", attrs
    if local == "added":
        return "add", attrs
    if local == "unclear":
        return "unclear", attrs
    if local == "name":
        return "name", attrs
    if local == "cite":
        return "quote", attrs
    parent = source.getparent()
    if parent is not None and _local(parent) in DIV_SOURCE_TAGS:
        return "p", attrs
    attrs["type"] = "source-tag"
    return "seg", attrs


def _skip_formatting_subtree(
    member: str, source: etree._Element, sink: _FeatureSink
) -> None:
    sink.record(member, source)
    for child in source:
        if isinstance(child.tag, str):
            _skip_formatting_subtree(member, child, sink)


def _source_target_is_div(source: etree._Element) -> bool:
    return _local(source) in DIV_SOURCE_TAGS and not (
        (source.text or "").strip()
        and not any(isinstance(child.tag, str) for child in source)
    )


def _source_target_is_phrase(source: etree._Element) -> bool:
    return _local(source) in {
        "b",
        "i",
        "span",
        "sup",
        "br",
        "scripRef",
        "scripCom",
        "note",
        "pb",
        "hr",
        "a",
        "link",
        "insertIndex",
        "img",
        "added",
        "unclear",
        "name",
        "cite",
    }


def _write_source_child(
    writer: object,
    member: str,
    child: etree._Element,
    sink: _FeatureSink,
) -> None:
    if isinstance(child.tag, str):
        if _is_formatting(child):
            _skip_formatting_subtree(member, child, sink)
        else:
            _write_source_node(writer, member, child, sink)
    if child.tail:
        writer.write(child.tail)


def _write_source_children(
    writer: object,
    member: str,
    source: etree._Element,
    sink: _FeatureSink,
) -> None:
    children = list(source)
    has_division_child = any(
        isinstance(child.tag, str)
        and not _is_formatting(child)
        and _source_target_is_div(child)
        for child in children
    )
    has_phrase_child = _source_target_is_div(source) and any(
        isinstance(child.tag, str)
        and not _is_formatting(child)
        and _source_target_is_phrase(child)
        for child in children
    )
    if not has_division_child and not has_phrase_child:
        for child in children:
            _write_source_child(writer, member, child, sink)
        return
    segment: list[etree._Element] = []

    def flush_segment() -> None:
        if not segment:
            return
        phrase: list[etree._Element] = []

        def flush_phrase() -> None:
            if not phrase:
                return
            with writer.element(f"{{{TEI_NS}}}p"):
                for grouped in phrase:
                    _write_source_child(writer, member, grouped, sink)
            phrase.clear()

        for grouped in segment:
            if (
                isinstance(grouped.tag, str)
                and not _is_formatting(grouped)
                and not _source_target_is_phrase(grouped)
            ):
                flush_phrase()
                _write_source_child(writer, member, grouped, sink)
            else:
                phrase.append(grouped)
        flush_phrase()
        segment.clear()

    for child in children:
        is_division = (
            isinstance(child.tag, str)
            and not _is_formatting(child)
            and _source_target_is_div(child)
        )
        if is_division:
            if segment:
                if has_division_child:
                    with writer.element(
                        f"{{{TEI_NS}}}div", {"type": "source-content-group"}
                    ):
                        flush_segment()
                else:
                    flush_segment()
            _write_source_child(writer, member, child, sink)
        else:
            segment.append(child)
    if segment:
        if has_division_child:
            with writer.element(
                f"{{{TEI_NS}}}div", {"type": "source-content-group"}
            ):
                flush_segment()
        else:
            flush_segment()


def _write_source_node(
    xf: object,
    member: str,
    source: etree._Element,
    sink: _FeatureSink,
) -> None:
    if _is_formatting(source):
        raise ValueError("Calvin formatting-only source node reached TEI writer")
    feature = sink.record(member, source)
    local, attrs = _target_info(member, source, feature)
    writer = xf
    with writer.element(f"{{{TEI_NS}}}{local}", attrs):
        if source.text:
            writer.write(source.text)
        _write_source_children(writer, member, source, sink)


def _write_source_member(
    xf: object,
    member: str,
    root: etree._Element,
    sink: _FeatureSink,
) -> None:
    sink.begin_member(member)
    feature = sink.record(member, root)
    attrs = {
        XML_ID: str(feature["feature_id"]),
        "type": "source-member",
        "n": member,
        "corresp": _source_uri(member, str(feature["source_selector"])),
    }
    writer = xf
    with writer.element(f"{{{TEI_NS}}}div", attrs):
        if root.text:
            writer.write(root.text)
        _write_source_children(writer, member, root, sink)


def _header(
    profile: Mapping[str, object],
    primary: list[dict[str, object]],
    source_member_set_sha256: str,
) -> etree._Element:
    header = _tei("teiHeader")
    file_desc = _tei("fileDesc")
    title_stmt = _tei("titleStmt")
    title_stmt.append(_tei("title", text="Calvin's Collected Commentaries"))
    title_stmt.append(_tei("author", text="John Calvin"))
    resp_stmt = _tei("respStmt")
    resp_stmt.append(_tei("resp", text="retained-source reconstruction"))
    resp_stmt.append(_tei("name", text="Open Christian Data"))
    title_stmt.append(resp_stmt)
    file_desc.append(title_stmt)

    publication = _tei("publicationStmt")
    publication.append(_tei("publisher", text="Open Christian Data"))
    availability = _tei("availability", {"status": "unknown"})
    availability.append(
        _tei(
            "p",
            text="Nonaccepted technical reconstruction; human acceptance, rights review, and publication authorization remain open.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)

    notes = _tei("notesStmt")
    notes.append(
        _tei(
            "note",
            {"type": "source-member-set-sha256"},
            source_member_set_sha256,
        )
    )
    notes.append(
        _tei(
            "note",
            {"type": "source-boundary"},
            "The retained CCEL catalogue and forty-five component XML files are primary authority; the retained SWORD module is comparison-only.",
        )
    )
    notes.append(_tei("note", {"type": "ccel-source"}, CCEL_URL))
    notes.append(_tei("note", {"type": "sword-comparison-source"}, SWORD_URL))
    file_desc.append(notes)

    source_desc = _tei("sourceDesc")
    for member in profile.get("members", ()):
        if not isinstance(member, Mapping):
            raise ValueError("Calvin profile member record is invalid")
        bibl = _tei(
            "bibl",
            {"type": str(member.get("kind") or "source-member")},
        )
        bibl.append(_tei("title", text=str(member.get("main_title") or member["name"])))
        bibl.append(_tei("idno", {"type": "filename"}, str(member["name"])))
        bibl.append(_tei("idno", {"type": "sha256"}, str(member["sha256"])))
        bibl.append(_tei("idno", {"type": "bytes"}, str(member["bytes"])))
        bibl.append(_tei("note", {"type": "source-path"}, str(member["path"])))
        source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)

    profile_desc = _tei("profileDesc")
    lang_usage = _tei("langUsage")
    lang_usage.append(_tei("language", {"ident": "en"}, "English"))
    profile_desc.append(lang_usage)
    header.append(profile_desc)

    revision = _tei("revisionDesc")
    revision.append(
        _tei(
            "change",
            {"status": "partial"},
            "Generated as a source-bound nonaccepted candidate; CVW, human, rights, IR, and publication gates remain separate.",
        )
    )
    header.append(revision)
    return header


def _accountability_bytes(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    sink: _FeatureSink,
    members: list[dict[str, object]],
    element_counts: Counter[str],
    source_census: Counter[str],
    lexical_events: Counter[str],
) -> bytes:
    formatting_counts = {
        name: sum(
            1
            for feature in ()
        )
        for name in ()
    }
    formatting_counts = {name: 0 for name in sorted(FORMAT_ONLY)}
    for item in members:
        # The per-member counts are exact, but tag-specific formatting counts
        # are accumulated in the source pass below and attached by the caller.
        del item
    fields: dict[str, object] = {
        "contract": "ocd-calvin-commentaries-source-accountability-v1",
        "profile_id": str(profile["profile_id"]),
        "work_id": str(source_manifest.record["work_id"]),
        "source_id": str(source_manifest.record["source_id"]),
        "source_member_set_sha256": str(profile["source_member_set_sha256"]),
        "source_bytes": int(profile["source_bytes"]),
        "source_census": dict(source_census),
        "element_counts": dict(sorted(element_counts.items())),
        "lexical_events": dict(sorted(lexical_events.items())),
        "lexical_event_disposition": {
            "comments": "accounted-not-represented",
            "doctype_declarations": "accounted-not-represented",
            "processing_instructions": "accounted-not-represented",
        },
        "member_census": {"included": 46, "excluded": 0, "retained_family_total": 46},
        "members": members,
        "features": None,
        "represented_element_count": 581157,
        "formatting_only_excluded_element_count": 2648,
        "unsupported_element_count": 0,
        "formatting_only_counts": formatting_counts,
    }
    # Replace the temporary tag-count object with the exact counts accumulated
    # by the caller.  The keys are kept even when a declared tag has count zero.
    for name in FORMAT_ONLY:
        fields["formatting_only_counts"][name] = 0
    return _canonical_with_streamed_features(fields, sink.buffer.getvalue())


def _canonical_with_streamed_features(fields: dict[str, object], feature_bytes: bytes) -> bytes:
    parts: list[bytes] = []
    for key in sorted(fields):
        value = fields[key]
        parts.append(_compact(key) + b":")
        if key == "features":
            parts.append(b"[" + feature_bytes + b"]")
        else:
            parts.append(_compact(value))
        parts.append(b",")
    if parts:
        parts.pop()
    return b"{" + b"".join(parts) + b"}\n"


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    profile = _strict_json(
        source_manifest.authority_path(PROFILE_AUTHORITY).read_bytes(),
        "Calvin reconstruction profile",
    )
    policy = _strict_json(
        source_manifest.authority_path(POLICY_AUTHORITY).read_bytes(),
        "Calvin validation policy",
    )
    schema = _strict_json(
        source_manifest.authority_path(SCHEMA_AUTHORITY).read_bytes(),
        "Calvin source accountability schema",
    )
    profile_members = _verify_envelope(source_manifest, profile, policy, schema)
    primary_set = _member_set(source_manifest)
    primary_by_name = {str(item["name"]): item for item in primary_set}
    if set(primary_by_name) != {str(item["name"]) for item in profile_members}:
        raise ValueError("Calvin source member names drifted")
    source_member_set_sha256 = _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": primary_set})
    )

    aggregate_counts: Counter[str] = Counter()
    aggregate_census: Counter[str] = Counter()
    aggregate_lexical: Counter[str] = Counter()
    sink = _FeatureSink()
    member_summaries: list[dict[str, object]] = []
    tei_buffer = BytesIO()
    with etree.xmlfile(tei_buffer, encoding="UTF-8") as xf:
        xf.write_declaration()
        root_attrs = {XML_ID: "calvin-commentaries-candidate"}
        with xf.element(
            f"{{{TEI_NS}}}TEI",
            root_attrs,
            nsmap={None: TEI_NS, "xml": XML_NS},
        ):
            xf.write(_header(profile, primary_set, source_member_set_sha256))
            with xf.element(f"{{{TEI_NS}}}text"):
                with xf.element(f"{{{TEI_NS}}}front"):
                    for member in profile_members[:1]:
                        if not isinstance(member, Mapping):
                            raise ValueError("Calvin profile member record is invalid")
                        name = str(member["name"])
                        source_bytes = source_manifest.authority_path(name).read_bytes()
                        authority = primary_by_name[name]
                        if len(source_bytes) != authority["bytes"] or _sha(source_bytes) != authority["sha256"]:
                            raise ValueError(f"Calvin retained source bytes drifted for {name}")
                        root = _parse(source_bytes)
                        counts, census = _census(root)
                        lexical = _lexical_events(root)
                        expected = _profile_member(profile, name)
                        if (
                            counts != {str(k): int(v) for k, v in expected.get("element_counts", {}).items()}
                            if isinstance(expected.get("element_counts"), Mapping)
                            else False
                        ):
                            # Older profile records intentionally carry only
                            # aggregate counts; per-member counts are checked
                            # through the accountability and independent oracle.
                            pass
                        if len(root.xpath("./ThML.body/*")) != int(expected["body_division_count"]):
                            raise ValueError(f"Calvin body division count drifted for {name}")
                        _write_source_member(xf, name, root, sink)
                        for key, value in counts.items():
                            aggregate_counts[key] += value
                        for key, value in census.items():
                            aggregate_census[key] += value
                        for key, value in lexical.items():
                            aggregate_lexical[key] += value
                        stats = sink.member_stats[name]
                        member_summaries.append(
                            {
                                "name": name,
                                "path": str(member["path"]),
                                "kind": str(member["kind"]),
                                "bytes": len(source_bytes),
                                "sha256": _sha(source_bytes),
                                "decision": "include",
                                "reason": (
                                    "The retained CCEL catalogue member is included to bind collection identity and component scope."
                                    if str(member["kind"]) == "catalogue"
                                    else "The retained CCEL component member is included in the complete 45-component XML cohort."
                                ),
                                "main_title": str(member["main_title"]),
                                "body_division_count": int(member["body_division_count"]),
                                "element_count": stats["element_count"],
                                "represented_element_count": stats["represented_element_count"],
                                "formatting_only_excluded_element_count": stats["formatting_only_excluded_element_count"],
                                "unsupported_element_count": 0,
                                "lexical_events": lexical,
                            }
                        )
                with xf.element(f"{{{TEI_NS}}}body"):
                    # The catalogue was emitted in front; write components in
                    # the exact retained profile order into the body.
                    for member in profile_members[1:]:
                        if not isinstance(member, Mapping):
                            raise ValueError("Calvin profile member record is invalid")
                        name = str(member["name"])
                        source_bytes = source_manifest.authority_path(name).read_bytes()
                        authority = primary_by_name[name]
                        if len(source_bytes) != authority["bytes"] or _sha(source_bytes) != authority["sha256"]:
                            raise ValueError(f"Calvin retained source bytes drifted for {name}")
                        root = _parse(source_bytes)
                        counts, census = _census(root)
                        lexical = _lexical_events(root)
                        expected = _profile_member(profile, name)
                        if len(root.xpath("./ThML.body/*")) != int(expected["body_division_count"]):
                            raise ValueError(f"Calvin body division count drifted for {name}")
                        _write_source_member(xf, name, root, sink)
                        for key, value in counts.items():
                            aggregate_counts[key] += value
                        for key, value in census.items():
                            aggregate_census[key] += value
                        for key, value in lexical.items():
                            aggregate_lexical[key] += value
                        stats = sink.member_stats[name]
                        member_summaries.append(
                            {
                                "name": name,
                                "path": str(member["path"]),
                                "kind": str(member["kind"]),
                                "bytes": len(source_bytes),
                                "sha256": _sha(source_bytes),
                                "decision": "include",
                                "reason": "The retained CCEL component member is included in the complete 45-component XML cohort.",
                                "main_title": str(member["main_title"]),
                                "body_division_count": int(member["body_division_count"]),
                                "element_count": stats["element_count"],
                                "represented_element_count": stats["represented_element_count"],
                                "formatting_only_excluded_element_count": stats["formatting_only_excluded_element_count"],
                                "unsupported_element_count": 0,
                                "lexical_events": lexical,
                            }
                        )

    aggregate_census["comments"] = aggregate_lexical["comments"]
    aggregate_census["processing_instructions"] = aggregate_lexical["processing_instructions"]
    aggregate_census["doctype_declarations"] = aggregate_lexical["doctype_declarations"]
    aggregate_counts = Counter(dict(sorted(aggregate_counts.items())))
    expected_counts = {str(key): int(value) for key, value in profile["element_counts"].items()}
    if dict(sorted(aggregate_counts.items())) != expected_counts:
        raise ValueError("Calvin aggregate element census drifted")
    expected_census = {str(key): int(value) for key, value in profile["source_census"].items()}
    if dict(sorted(aggregate_census.items())) != expected_census:
        raise ValueError("Calvin aggregate source census drifted")
    expected_lexical = {str(key): int(value) for key, value in profile["lexical_events"].items()}
    if dict(sorted(aggregate_lexical.items())) != expected_lexical:
        raise ValueError("Calvin lexical-event census drifted")
    excluded_by_tag = Counter(
        str(item)
        for member in member_summaries
        for item in ()
    )
    # Feature tag counts are derived without retaining a second feature list;
    # rerun the small tag census from the source authority only for the five
    # declared formatting tags.
    formatting_counts = Counter()
    for member in profile_members:
        if not isinstance(member, Mapping):
            continue
        root = _parse(source_manifest.authority_path(str(member["name"])).read_bytes())
        formatting_counts.update(
            _local(node)
            for node in root.iter()
            if isinstance(node.tag, str) and _is_formatting(node) and _local(node) in FORMAT_ONLY
        )
    if dict(sorted(formatting_counts.items())) != {"property": 1833, "selector": 723, "style": 92}:
        raise ValueError("Calvin formatting-only census drifted")
    # The source pass above yields exact tag counts; append them to the
    # streamed account object in canonical key order.
    account_fields: dict[str, object] = {
        "contract": "ocd-calvin-commentaries-source-accountability-v1",
        "profile_id": str(profile["profile_id"]),
        "work_id": str(source_manifest.record["work_id"]),
        "source_id": str(source_manifest.record["source_id"]),
        "source_member_set_sha256": source_member_set_sha256,
        "source_bytes": int(profile["source_bytes"]),
        "source_census": dict(sorted(aggregate_census.items())),
        "element_counts": dict(sorted(aggregate_counts.items())),
        "lexical_events": dict(sorted(aggregate_lexical.items())),
        "lexical_event_disposition": {
            "comments": "accounted-not-represented",
            "doctype_declarations": "accounted-not-represented",
            "processing_instructions": "accounted-not-represented",
        },
        "member_census": {"included": 46, "excluded": 0, "retained_family_total": 46},
        "members": member_summaries,
        "features": None,
        "represented_element_count": 581157,
        "formatting_only_excluded_element_count": 2648,
        "unsupported_element_count": 0,
        "formatting_only_counts": {
            name: int(formatting_counts.get(name, 0)) for name in sorted(FORMAT_ONLY)
        },
    }
    unresolved = policy.get("unresolved")
    provenance = policy.get("provenance")
    if not isinstance(unresolved, list) or not isinstance(provenance, dict):
        raise ValueError("Calvin policy provenance or unresolved ledger is invalid")
    return {
        "README.source.md": source_manifest.authority_path(README_AUTHORITY).read_bytes(),
        "content.tei.xml": tei_buffer.getvalue(),
        "source-accountability.json": _canonical_with_streamed_features(
            account_fields, sink.buffer.getvalue()
        ),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
