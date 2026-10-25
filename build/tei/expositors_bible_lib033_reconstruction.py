"""Deterministic retained-CCEL XML to nonaccepted LIB-033 TEI corpus."""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-expositors-bible-lib033-retained-xml-to-tei"
CONVERTER_VERSION = "3"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
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


def _text_correction_id(row: Mapping[str, object]) -> str:
    fields = (
        "member_id", "source_selector", "source_field", "source_value_sha256",
        "start", "end", "sic", "corr", "witness_url",
    )
    return _sha("\\0".join(str(row[field]) for field in fields).encode("utf-8"))


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
        raise ValueError("retained LIB-033 XML is not parseable") from exc


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
        raise ValueError("LIB-033 source element escaped its document")
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
        # and xml:lang on ten Harper spans.
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
        qualified = {
            "xml:id": _XML_ID,
            "xml:space": _XML_SPACE,
            "xml:lang": _XML_LANG,
        }.get(key, key)
        node.set(qualified, value)
    node.text = text
    return node


_FINDLAY_MEMBER_IDS = frozenset(
    {"findlay-expositoreph", "findlay-expositorgal"}
)
_FINDLAY_LANGUAGE_CODES = {
    "EL": "grc",
    "HE": "he",
    "LA": "la",
    "FR": "fr",
    "DE": "de",
}


def _findlay_target_tag(source: etree._Element) -> str:
    """Map a Findlay ThML element to a meaningful TEI carrier."""

    tag = _local_name(source.tag)
    if tag == "ThML.body":
        return "div"
    if tag in {"div1", "div2", "div3", "div4"}:
        return "div"
    if tag == "div":
        return "quote" if source.get("class", "").casefold() in {
            "blockquot",
            "quote",
        } else "div"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "head"
    if tag == "p":
        return "p"
    if tag in {"i", "em", "small"}:
        return "hi"
    if tag == "span":
        if source.get("class", "").casefold() in {"greek", "hebrew"}:
            return "foreign"
        if source.get("class", "").casefold() == "ref":
            return "ref"
        return "hi"
    if tag == "cite":
        return "quote"
    if tag == "a":
        # Image-map anchors in the retained ThML have no link target.  Keep
        # those as anchors; a target-bearing <a> remains a readable ref.
        return "ref" if source.get("href") or source.get("osisRef") else "anchor"
    if tag in {"scripRef", "scripCom"}:
        return "ref"
    if tag == "note":
        return "note"
    if tag == "pb":
        return "pb"
    if tag == "br":
        return "lb"
    if tag == "hr":
        return "milestone"
    if tag == "table":
        return "table"
    if tag == "tr":
        return "row"
    if tag in {"td", "th"}:
        return "cell"
    if tag == "verse":
        return "lg"
    if tag == "l":
        return "l"
    if tag in {"ul", "ol"}:
        return "list"
    if tag == "li":
        return "item"
    if tag == "insertIndex":
        return "index"
    return "seg"


def _findlay_ana_tokens(source: etree._Element) -> list[str]:
    tokens: list[str] = [
        "urn:ocd:source-tag:" + quote(_local_name(source.tag), safe="")
    ]
    if source.get("id"):
        tokens.append("urn:ocd:source-id:" + quote(source.get("id", ""), safe=""))
    if source.get("type"):
        tokens.append(
            "urn:ocd:source-type:" + quote(source.get("type", ""), safe="")
        )
    if source.get("class", "").casefold() == "sc":
        tokens.append("urn:ocd:source-class:sc")
    return tokens


def _findlay_attributes(
    source: etree._Element,
    feature: Mapping[str, object],
    target_tag: str,
    source_id_to_feature_id: Mapping[str, str],
) -> dict[str, str]:
    source_tag = _local_name(source.tag)
    attributes = {
        "xml:id": str(feature["tei_xml_id"]),
        "corresp": "urn:source-xpath:"
        + quote(str(feature["source_selector"]), safe=""),
    }
    if target_tag in {
        "div",
        "quote",
        "ref",
        "note",
        "table",
        "lg",
        "list",
        "anchor",
        "seg",
    }:
        attributes["type"] = "source-xml-element"
    if target_tag == "lg" and source.get("type"):
        attributes["type"] = source.get("type", "")
    elif source_tag == "scripRef":
        attributes["type"] = "scripture-reference"
    elif source_tag == "scripCom":
        attributes["type"] = "scripture-commentary"
    if source.get("n"):
        attributes["n"] = source.get("n", "")
    source_space = source.get("space") or source.get(_XML_SPACE)
    if source_tag == "ThML.body" and source_space == "preserve":
        attributes["xml:space"] = "preserve"
    if source_tag in {"a", "scripRef", "scripCom"}:
        target = source.get("href") or source.get("osisRef")
        if target:
            parsed = urlsplit(target)
            # Only a bare fragment is proven same-document.  Query-bearing
            # links address a routed viewer request and retain their exact
            # source target even when the fragment text matches a body ID.
            if (
                parsed.fragment
                and not parsed.scheme
                and not parsed.netloc
                and not parsed.path
                and not parsed.query
            ):
                fragment_id = source_id_to_feature_id.get(unquote(parsed.fragment))
                if fragment_id:
                    target = urlunsplit(
                        (
                            parsed.scheme,
                            parsed.netloc,
                            parsed.path,
                            parsed.query,
                            fragment_id,
                        )
                    )
            attributes["target"] = target
        if source.get("passage"):
            attributes["cRef"] = source.get("passage", "")
    if source_tag == "note" and source.get("place"):
        attributes["place"] = source.get("place", "")
    if source_tag in {"td", "th"}:
        if source.get("colspan"):
            attributes["cols"] = source.get("colspan", "")
        if source.get("rowspan"):
            attributes["rows"] = source.get("rowspan", "")
        if source_tag == "th":
            attributes["role"] = "label"
    if source_tag == "hr":
        attributes["unit"] = "horizontal-rule"
    if source_tag in {"i", "em"}:
        attributes["rend"] = "italic"
    elif source_tag == "small":
        attributes["rend"] = "small"
    elif source_tag == "span" and source.get("class", "").casefold() == "sc":
        attributes["rend"] = "smallcaps"
    source_language = source.get("lang") or source.get(_XML_LANG)
    if not source_language:
        source_language = {
            "greek": "grc",
            "hebrew": "he",
        }.get(source.get("class", "").casefold())
    if source_language:
        attributes["xml:lang"] = _FINDLAY_LANGUAGE_CODES.get(
            source_language, source_language.lower()
        )
    ana = _findlay_ana_tokens(source)
    if ana:
        attributes["ana"] = " ".join(ana)
    return attributes


def _findlay_comment_anchor(
    node: etree._Comment | etree._ProcessingInstruction,
    member_id: str,
    ordinal: int,
) -> etree._Element:
    kind = "comment" if isinstance(node, etree._Comment) else "processing-instruction"
    digest = _sha((node.text or "").encode("utf-8"))
    return _element(
        "anchor",
        {
            "xml:id": f"{member_id}-{kind}-{ordinal:05d}",
            "type": f"source-{kind}",
            "ana": f"urn:source-{kind}-sha256:{digest}",
        },
    )


def _findlay_source_node(
    source: etree._Element,
    root: etree._Element,
    member_id: str,
    feature_by_selector: Mapping[str, Mapping[str, object]],
    comment_ordinal: list[int],
    source_id_to_feature_id: Mapping[str, str],
) -> etree._Element:
    if isinstance(source, etree._Comment) or isinstance(
        source, etree._ProcessingInstruction
    ):
        comment_ordinal[0] += 1
        target = _findlay_comment_anchor(source, member_id, comment_ordinal[0])
        target.tail = source.tail
        return target
    if not isinstance(source.tag, str):
        raise ValueError("LIB-033 Findlay source body contains an unsupported node")
    selector = _selector(source, root)
    feature = feature_by_selector.get(selector)
    if feature is None:
        raise ValueError(f"LIB-033 Findlay source feature is not inventoried: {selector}")
    target_tag = _findlay_target_tag(source)
    target = _element(
        target_tag,
        _findlay_attributes(source, feature, target_tag, source_id_to_feature_id),
        source.text,
    )
    source_tag = _local_name(source.tag)
    if source_tag in {"div", "div1", "div2", "div3", "div4"} and source.get(
        "title"
    ) and not any(
        isinstance(child.tag, str)
        and _local_name(child.tag) in {"h1", "h2", "h3", "h4", "h5", "h6"}
        for child in source
    ):
        synthetic = _element(
            "head",
            {
                "ana": "urn:ocd:source-attribute:title",
            },
            source.get("title"),
        )
        target.append(synthetic)
    # TEI divisions may contain sibling divisions, but a block-level child
    # after a division is not legal in the P5 content model.  Findlay's ThML
    # mixes those forms (for example, a heading section followed by a table),
    # so retain source order inside an attributed synthetic content division.
    nested_div_seen = False
    content_group: etree._Element | None = None
    for child_ordinal, child in enumerate(source, 1):
        mapped = _findlay_source_node(
            child,
            root,
            member_id,
            feature_by_selector,
            comment_ordinal,
            source_id_to_feature_id,
        )
        source_child_name = (
            _local_name(child.tag) if isinstance(child.tag, str) else ""
        )
        if source_child_name in {"h1", "h2", "h3", "h4", "h5", "h6"} and any(
            isinstance(previous.tag, str)
            for previous in list(source)[: child_ordinal - 1]
        ):
            parent_feature = feature_by_selector[selector]
            section = _element(
                "div",
                {
                    "type": "source-heading-section",
                    "ana": "urn:ocd:source-parent-feature:"
                    + str(parent_feature["tei_xml_id"]),
                },
            )
            section.append(mapped)
            mapped_container = section
        else:
            mapped_container = mapped
        mapped_name = _local_name(mapped_container.tag)
        if target_tag == "div" and mapped_name == "ref":
            # A direct ThML span/a reference is inline source content.  TEI
            # does not admit ref directly under div, so retain the exact
            # source feature and order in a source-parent-attributed p.
            parent_feature = feature_by_selector[selector]
            inline_wrapper = _element(
                "p",
                {
                    "ana": "urn:ocd:source-parent-feature:"
                    + str(parent_feature["tei_xml_id"]),
                },
            )
            inline_wrapper.append(mapped_container)
            mapped_container = inline_wrapper
        if target_tag == "div" and nested_div_seen and mapped_name != "div":
            if content_group is None:
                parent_feature = feature_by_selector[selector]
                content_group = _element(
                    "div",
                    {
                        "type": "source-content-group",
                        "ana": "urn:ocd:source-parent-feature:"
                        + str(parent_feature["tei_xml_id"]),
                    },
                )
                target.append(content_group)
            content_group.append(mapped_container)
        else:
            target.append(mapped_container)
            if target_tag == "div" and mapped_name == "div":
                nested_div_seen = True
                content_group = None
        mapped.tail = child.tail
    return target


def _findlay_member_tei(
    member: Mapping[str, object],
    content: bytes,
    features: tuple[dict[str, object], ...],
) -> etree._Element:
    root = _parse(content)
    bodies = [
        element
        for element in root.iter()
        if isinstance(element.tag, str) and _local_name(element.tag) == "ThML.body"
    ]
    if len(bodies) != 1:
        raise ValueError("LIB-033 Findlay source must contain one ThML.body")
    feature_by_selector = {str(row["source_selector"]): row for row in features}
    source_id_to_feature_id = {
        str(row["source_attributes"]["id"]): str(row["tei_xml_id"])
        for row in features
        if isinstance(row.get("source_attributes"), Mapping)
        and "id" in row["source_attributes"]
    }
    division = _element(
        "div",
        {"xml:id": str(member["member_id"]), "type": "retained-source-member"},
    )
    division.append(_element("head", text=str(member["source_title"])))
    mapped_body = _findlay_source_node(
        bodies[0],
        root,
        str(member["member_id"]),
        feature_by_selector,
        [0],
        source_id_to_feature_id,
    )
    mapped_body.tail = bodies[0].tail
    division.append(mapped_body)
    return division


def _apply_findlay_text_corrections(
    member_id: str,
    mapped_body: etree._Element,
    features: tuple[dict[str, object], ...],
    corrections: list[Mapping[str, object]],
    used_corrections: set[str],
) -> None:
    feature_by_selector = {str(row["source_selector"]): row for row in features}
    mapped_by_id = {
        node.get(_XML_ID): node
        for node in mapped_body.iter()
        if node.get(_XML_ID)
    }
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for row in corrections:
        if row.get("member_id") != member_id:
            raise ValueError("LIB-033 correction escaped its retained member")
        key = (str(row["source_selector"]), str(row["source_field"]))
        grouped.setdefault(key, []).append(row)

    for (selector, source_field), rows in grouped.items():
        feature = feature_by_selector.get(selector)
        if feature is None:
            raise ValueError(f"LIB-033 correction selector is not inventoried: {selector}")
        if source_field not in {"text", "tail"}:
            raise ValueError(f"LIB-033 correction field is invalid: {source_field}")
        field_key = "source_direct_text" if source_field == "text" else "source_tail_text"
        value = str(feature[field_key])
        target = mapped_by_id.get(str(feature["tei_xml_id"]))
        if target is None:
            raise ValueError(f"LIB-033 correction TEI carrier is missing: {selector}")
        if (target.text if source_field == "text" else target.tail or "") != (value or None):
            raise ValueError(f"LIB-033 correction carrier drifted from source: {selector}")
        rows.sort(key=lambda row: (int(row["start"]), int(row["end"])))
        cursor = 0
        choices: list[etree._Element] = []
        prefix: str | None = None
        for row in rows:
            start, end = int(row["start"]), int(row["end"])
            correction_id = _text_correction_id(row)
            if (
                row["source_value_sha256"] != _sha(value.encode("utf-8"))
                or start < cursor or end <= start or end > len(value)
                or value[start:end] != str(row["sic"])
                or row["source_selector"] != selector
                or row["source_field"] != source_field
                or not str(row["witness_url"]).startswith("https://www.gutenberg.org/")
            ):
                raise ValueError(f"LIB-033 correction is not bound to exact source span: {selector}")
            if correction_id in used_corrections:
                raise ValueError(f"LIB-033 duplicate text correction: {correction_id}")
            choice = _element(
                "choice",
                {
                    "corresp": "urn:ocd:source-text-correction:" + correction_id,
                    "resp": str(row["witness_url"]),
                },
            )
            choice.append(_element("sic", text=str(row["sic"])))
            choice.append(_element("corr", text=str(row["corr"])))
            if choices:
                choices[-1].tail = value[cursor:start] or None
            else:
                prefix = value[:start] or None
            choices.append(choice)
            cursor = end
            used_corrections.add(correction_id)
        choices[-1].tail = value[cursor:] or None
        if source_field == "text":
            target.text = prefix
            for index, choice in enumerate(choices):
                target.insert(index, choice)
        else:
            parent = target.getparent()
            if parent is None:
                raise ValueError(f"LIB-033 correction tail has no parent: {selector}")
            target.tail = prefix
            index = parent.index(target) + 1
            for choice in choices:
                parent.insert(index, choice)
                index += 1


def _work_tei(
    work: Mapping[str, object],
    member_rows: list[tuple[Mapping[str, object], bytes, tuple[dict[str, object], ...]]],
    correction_rows: list[Mapping[str, object]],
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
        member_id = str(member["member_id"])
        division = _element(
            "div",
            {"xml:id": member_id, "type": "retained-source-member"},
        )
        if member_id in _FINDLAY_MEMBER_IDS:
            member_corrections = [
                row for row in correction_rows if row.get("member_id") == member_id
            ]
            division = _findlay_member_tei(member, content, features)
            mapped_body = next(
                child for child in division
                if child.get(_XML_ID) and child.get(_XML_ID).startswith(member_id + "-feature-")
            )
            _apply_findlay_text_corrections(
                member_id, mapped_body, features, member_corrections, used_corrections
            )
        else:
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
            transcription = _element(
                "div", {"type": "parsed-xml-feature-transcription"}
            )
            for feature in features:
                block = _element(
                    "ab",
                    {
                        "xml:id": str(feature["tei_xml_id"]),
                        "type": "source-xml-element",
                        "subtype": str(feature["source_tag"]),
                        "n": str(feature["source_child_ordinal"]),
                        "corresp": "urn:source-xpath:"
                        + quote(str(feature["source_selector"]), safe=""),
                    },
                )
                block.append(
                    _element(
                        "seg", {"type": "direct-text"}, str(feature["source_direct_text"])
                    )
                )
                block.append(
                    _element(
                        "seg", {"type": "tail-text"}, str(feature["source_tail_text"])
                    )
                )
                transcription.append(block)
            division.append(transcription)
        body.append(division)
    text.append(body)
    tei.append(text)
    return tei


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    """Return the exact five non-manifest LIB-033 candidate members."""

    source_manifest.verify()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    profile = json.loads(profile_bytes)
    if (
        profile.get("contract") != "ocd-expositors-bible-lib033-profile-v2"
        or profile.get("profile_id") != "expositors-bible-lib033-complete-retained-xml-v2"
    ):
        raise ValueError("LIB-033 reconstruction profile identity mismatch")
    configured_members = profile.get("included_members")
    works = profile.get("works")
    if not isinstance(configured_members, list) or len(configured_members) != 12:
        raise ValueError("LIB-033 requires exactly twelve retained members")
    if not isinstance(works, list) or len(works) != 5:
        raise ValueError("LIB-033 requires exactly five frozen works")
    if profile.get("text_correction_contract") != "ocd-expositors-bible-edition-witness-token-corrections-v1":
        raise ValueError("LIB-033 edition-witness correction contract is missing")
    correction_rows = profile.get("text_corrections")
    if not isinstance(correction_rows, list) or any(not isinstance(row, Mapping) for row in correction_rows):
        raise ValueError("LIB-033 text correction profile is invalid")
    used_corrections: set[str] = set()
    authority_by_name = {
        str(item["name"]): item for item in source_manifest.record["authorities"]
    }
    grouped: dict[str, list[tuple[Mapping[str, object], bytes, tuple[dict[str, object], ...]]]] = {
        str(work["work_id"]): [] for work in works
    }
    all_crosswalk: list[dict[str, object]] = []
    member_accounting = []
    retained_source_bytes: dict[str, dict[str, object]] = {}
    for member in configured_members:
        authority_name = str(member["authority_name"])
        authority = authority_by_name.get(authority_name)
        if authority is None or authority.get("role") != "primary-source":
            raise ValueError(f"LIB-033 retained authority missing: {authority_name}")
        content = source_manifest.authority_path(authority_name).read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError(f"LIB-033 retained member drifted: {authority_name}")
        features = _feature_inventory(content, str(member["member_id"]))
        if len(features) != member["xml_element_count"]:
            raise ValueError(f"LIB-033 XML element count drifted: {authority_name}")
        work_id = str(member["work_id"])
        if work_id not in grouped:
            raise ValueError("LIB-033 member escaped frozen work scope")
        grouped[work_id].append((member, content, features))
        retained_source_bytes[str(member["member_id"])] = {
            "bytes": len(content),
            "sha256": _sha(content),
            "base64": base64.b64encode(content).decode("ascii"),
        }
        member_id = str(member["member_id"])
        for feature in features:
            # Findlay's retained XML includes a root/header envelope whose
            # source features remain available in exact retained bytes and
            # the feature ledger, but are outside the readable body TEI
            # projection.  Do not manufacture TEI selectors for those
            # evidence-only features.
            body_projected = (
                member_id not in _FINDLAY_MEMBER_IDS
                or str(feature["source_selector"]).startswith(
                    "/ThML[1]/ThML.body[1]"
                )
            )
            all_crosswalk.append(
                {
                    **feature,
                    "member_id": member_id,
                    "work_id": work_id,
                    "disposition": "represented" if body_projected else "evidence-only",
                    "tei_selector": (
                        f"#{feature['tei_xml_id']}" if body_projected else None
                    ),
                }
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
    corpus = _element("teiCorpus", {"xml:id": "expositors-bible-lib033-corpus"})
    corpus_header = _element("teiHeader")
    corpus_file_desc = _element("fileDesc")
    corpus_title_stmt = _element("titleStmt")
    corpus_title_stmt.append(_element("title", text="The Expositor's Bible: LIB-033 retained-source corpus"))
    corpus_file_desc.append(corpus_title_stmt)
    corpus_publication = _element("publicationStmt")
    corpus_publication.append(_element("publisher", text="Open Christian Data"))
    corpus_availability = _element("availability", {"status": "restricted"})
    corpus_availability.append(_element("p", text="Nonaccepted candidate; not publication-ready."))
    corpus_publication.append(corpus_availability)
    corpus_file_desc.append(corpus_publication)
    corpus_source = _element("sourceDesc")
    corpus_source.append(_element("p", text="Twelve exact retained CCEL XML members across five frozen works."))
    corpus_file_desc.append(corpus_source)
    corpus_header.append(corpus_file_desc)
    corpus.append(corpus_header)
    for work in works:
        rows = grouped[str(work["work_id"])]
        if len(rows) != work["member_count"]:
            raise ValueError("LIB-033 work/member lineage drifted")
        corpus.append(_work_tei(work, rows, correction_rows, used_corrections))
    expected_corrections = {_text_correction_id(row) for row in correction_rows}
    if used_corrections != expected_corrections:
        raise ValueError("LIB-033 text correction coverage is incomplete")
    tei_bytes = etree.tostring(
        corpus, encoding="UTF-8", xml_declaration=True, pretty_print=False
    )
    excluded = profile.get("excluded_members")
    if not isinstance(excluded, list) or len(excluded) != 35:
        raise ValueError("LIB-033 retained-family exclusion census is incomplete")
    census = {
        "contract": "ocd-expositors-bible-lib033-member-census-v1",
        "included": member_accounting,
        "excluded": excluded,
        "counts": {"included": 12, "excluded": 35, "retained_family_total": 47},
        "inventory_contradiction": profile["inventory_contradiction"],
    }
    namespace_collision = profile.get("namespace_attribute_collision")
    if not isinstance(namespace_collision, dict):
        raise ValueError("LIB-033 namespace-attribute collision authority is missing")
    collision_rows = [
        item
        for item in all_crosswalk
        if item["member_id"] == namespace_collision.get("member_id")
        and item["source_tag"] == namespace_collision.get("source_tag")
        and all(key in item["source_attributes"] for key in namespace_collision.get("distinct_keys", []))
    ]
    if len(collision_rows) != namespace_collision.get("count"):
        raise ValueError("LIB-033 namespace-qualified attribute census drifted")
    accountability = {
        "contract": "ocd-expositors-bible-lib033-source-accountability-v2",
        "schema": "lib033.source-accountability.schema.json",
        "profile_id": profile["profile_id"],
        "source_member_count": 12,
        "work_count": 5,
        "source_bytes": sum(int(item["bytes"]) for item in member_accounting),
        "feature_count": len(all_crosswalk),
        "omitted_feature_count": 0,
        "unresolved_feature_count": 0,
        "member_census": census,
        "crosswalk": all_crosswalk,
        "retained_source_bytes": retained_source_bytes,
    }
    authority_bindings = {
        str(item["name"]): {
            key: item[key] for key in ("path", "bytes", "sha256", "role")
        }
        for item in source_manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-expositors-bible-lib033-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket": "LIB-033",
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
            "id": "lib033-print-edition-collation-not-performed",
            "status": "unresolved",
            "scope": "all twelve retained members",
            "reason": "Retained CCEL witness statements were preserved but not collated against print copies.",
        },
        {
            "id": "lib033-rights-and-publication-review",
            "status": "unresolved",
            "scope": "candidate corpus",
            "reason": "Technical validation does not decide rights acceptance or publication readiness.",
        },
        {
            "id": "lib033-retained-inventory-47-vs-legacy-48",
            "status": "unresolved",
            "scope": "Expositor's Bible family inventory",
            "reason": str(profile["inventory_contradiction"]),
        },
        {
            "id": "lib033-maclaren-colphm-source-author-spelling",
            "status": "unresolved",
            "scope": "maclaren-expositorcolphm",
            "reason": "Retained DC.Creator spells the author Alexaner MacLaren; no editorial correction is asserted.",
        },
    ]
    readme = (
        "# LIB-033 source note\n\n"
        "This is a nonaccepted, nonpublication reconstruction candidate for five frozen "
        "Expositor's Bible work identities. It retains exact bytes for twelve retained "
        "CCEL ThML/XML members in source-accountability.json and inventories every parsed "
        "XML element. The two G. G. Findlay readable bodies preserve nested source "
        "structure; envelope and metadata features outside those bodies remain "
        "evidence-only ledger rows without fabricated TEI selectors, and the other ten "
        "members retain their diagnostic feature projection. Source title attributes "
        "without a projected head remain in source accountability without a separate "
        "readable attribute projection.\n\n"
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
