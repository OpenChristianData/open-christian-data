"""Check actual Findlay TEI against raw ThML without building expected TEI.

The source parser is stdlib ElementTree. Source element identity, direct text,
tails, and child relationships are checked against actual candidate nodes.
Only explicitly attributed, text-free TEI compatibility wrappers are transparent.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import hashlib
from urllib.parse import quote, unquote, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML = "{http://www.w3.org/XML/1998/namespace}"
SOURCE_HASHES = {
    "findlay-expositoreph": "697b5713691c402b9d127296cf7d68c2e5aacae66fc6e8a052d6ac9206b3f771",
    "findlay-expositorgal": "9fcb5bc51a36d49f68a94d1852a57ffcefd8896d7e7f8ae7036aae1da4a8fc6d",
}
TAG_CONTRACT = {
    "ThML.body": "div", "div1": "div", "div2": "div", "div3": "div",
    "div4": "div", "h1": "head", "h2": "head", "h3": "head",
    "h4": "head", "h5": "head", "h6": "head", "p": "p",
    "i": "hi", "em": "hi", "small": "hi", "cite": "quote",
    "scripRef": "ref", "scripCom": "ref", "note": "note", "pb": "pb",
    "br": "lb", "hr": "milestone", "table": "table", "tr": "row",
    "td": "cell", "th": "cell", "verse": "lg", "l": "l",
    "ul": "list", "ol": "list", "li": "item", "insertIndex": "index",
}


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("Findlay native TEI: " + message)


def _text_correction_id(row: Mapping[str, object]) -> str:
    fields = (
        "member_id", "source_selector", "source_field", "source_value_sha256",
        "start", "end", "sic", "corr", "witness_url",
    )
    return hashlib.sha256("\\0".join(str(row[field]) for field in fields).encode("utf-8")).hexdigest()


def _check_correction_choice(
    choice: etree._Element, row: Mapping[str, object], correction_id: str
) -> None:
    _assert(
        choice.tag == TEI + "choice"
        and dict(choice.attrib) == {
            "corresp": "urn:ocd:source-text-correction:" + correction_id,
            "resp": str(row["witness_url"]),
        }
        and len(choice) == 2
        and choice[0].tag == TEI + "sic"
        and choice[1].tag == TEI + "corr"
        and not choice[0].attrib
        and not choice[1].attrib
        and choice[0].text == str(row["sic"])
        and choice[1].text == str(row["corr"])
        and not choice[0].tail
        and not choice[1].tail,
        f"correction witness markup drifted: {correction_id}",
    )


def _validate_corrected_field(
    actual: etree._Element,
    value: str,
    member_id: str,
    selector: str,
    source_field: str,
    rows: list[Mapping[str, object]],
    choices_by_corresp: Mapping[str, etree._Element],
    used_corrections: set[str],
) -> None:
    rows = sorted(rows, key=lambda row: (int(row["start"]), int(row["end"])))
    actual_text = value or ""
    field_value = (
        (actual.text or "") if source_field == "text" else (actual.tail or "")
    )
    if not rows:
        _assert(field_value == actual_text, f"{source_field} text at {selector}")
        return

    value_digest = hashlib.sha256(actual_text.encode("utf-8")).hexdigest()
    expected_choices: list[etree._Element] = []
    cursor = 0
    correction_ids: list[str] = []
    for row in rows:
        correction_id = _text_correction_id(row)
        start, end = int(row["start"]), int(row["end"])
        _assert(
            row["member_id"] == member_id
            and row["source_selector"] == selector
            and row["source_field"] == source_field
            and row["source_value_sha256"] == value_digest
            and 0 <= start < end <= len(actual_text)
            and start >= cursor
            and actual_text[start:end] == str(row["sic"])
            and str(row["witness_url"]).startswith("https://www.gutenberg.org/"),
            f"source-bound correction span at {selector}",
        )
        uri = "urn:ocd:source-text-correction:" + correction_id
        choice = choices_by_corresp.get(uri)
        _assert(choice is not None, f"missing correction choice at {selector}")
        _check_correction_choice(choice, row, correction_id)
        _assert(correction_id not in used_corrections, f"duplicate correction use {correction_id}")
        used_corrections.add(correction_id)
        correction_ids.append(correction_id)
        expected_choices.append(choice)
        cursor = end

    if source_field == "text":
        _assert(
            list(actual)[:len(expected_choices)] == expected_choices,
            f"direct-text choices are not before source children at {selector}",
        )
        _assert(
            field_value == actual_text[:int(rows[0]["start"])],
            f"direct-text prefix at {selector}",
        )
    else:
        parent = actual.getparent()
        _assert(parent is not None, f"tail correction has no parent at {selector}")
        sibling_index = parent.index(actual)
        _assert(
            list(parent)[sibling_index + 1:sibling_index + 1 + len(expected_choices)]
            == expected_choices,
            f"tail choices are not adjacent to their source node at {selector}",
        )
        _assert(
            field_value == actual_text[:int(rows[0]["start"])],
            f"tail-text prefix at {selector}",
        )

    for index, (row, choice) in enumerate(zip(rows, expected_choices, strict=True)):
        next_start = int(rows[index + 1]["start"]) if index + 1 < len(rows) else len(actual_text)
        expected_gap = actual_text[int(row["end"]):next_start]
        _assert(
            (choice.tail or "") == expected_gap,
            f"source text between correction spans at {selector}",
        )


def _semantic_tag(source: ET.Element) -> str:
    if source.tag == "div":
        return "quote" if source.get("class", "").lower() in {"quote", "blockquot"} else "div"
    if source.tag == "span":
        style = source.get("class", "").lower()
        return "foreign" if style in {"greek", "hebrew"} else "ref" if style == "ref" else "hi"
    if source.tag == "a":
        return "ref" if source.get("href") or source.get("osisRef") else "anchor"
    _assert(source.tag in TAG_CONTRACT, f"unreviewed source tag {source.tag}")
    return TAG_CONTRACT[source.tag]


def _check_attributes(
    source: ET.Element, actual: etree._Element, identifier: str,
    source_path: str, source_ids: dict[str, str],
) -> None:
    tag = _semantic_tag(source)
    _assert(actual.tag == TEI + tag, f"wrong semantic tag at {source_path}")
    wanted = {XML + "id": identifier, "corresp": "urn:source-xpath:" + quote(source_path, safe="")}
    tokens = ["urn:ocd:source-tag:" + quote(str(source.tag), safe="")]
    for field in ("id", "type"):
        if source.get(field):
            tokens.append(f"urn:ocd:source-{field}:" + quote(source.get(field), safe=""))
    if source.get("class", "").lower() == "sc":
        tokens.append("urn:ocd:source-class:sc")
    wanted["ana"] = " ".join(tokens)
    if tag in {"div", "quote", "ref", "note", "table", "lg", "list", "anchor", "seg"}:
        wanted["type"] = "source-xml-element"
    if source.tag == "verse" and source.get("type"):
        wanted["type"] = source.get("type")
    if source.tag in {"scripRef", "scripCom"}:
        wanted["type"] = "scripture-reference" if source.tag == "scripRef" else "scripture-commentary"
    if source.get("n"):
        wanted["n"] = source.get("n")
    if source.tag == "ThML.body" and source.get(XML + "space", source.get("space")) == "preserve":
        wanted[XML + "space"] = "preserve"
    if source.tag in {"a", "scripRef", "scripCom"}:
        target = source.get("href") or source.get("osisRef")
        if target:
            parts = urlsplit(target)
            # Only a same-document reference is eligible for native-ID remapping.
            if not parts.scheme and not parts.netloc and not parts.path and not parts.query and parts.fragment:
                fragment = unquote(parts.fragment)
                _assert(fragment in source_ids, f"unresolved source fragment at {source_path}")
                target = urlunsplit(("", "", "", parts.query, source_ids[fragment]))
            wanted["target"] = target
        if source.get("passage"):
            wanted["cRef"] = source.get("passage")
    if source.tag == "note" and source.get("place"):
        wanted["place"] = source.get("place")
    if source.tag in {"td", "th"}:
        if source.tag == "th":
            wanted["role"] = "label"
        for original, mapped in (("colspan", "cols"), ("rowspan", "rows")):
            if source.get(original):
                wanted[mapped] = source.get(original)
    if source.tag == "hr":
        wanted["unit"] = "horizontal-rule"
    if source.tag in {"i", "em", "small"}:
        wanted["rend"] = "small" if source.tag == "small" else "italic"
    elif source.tag == "span" and source.get("class", "").lower() == "sc":
        wanted["rend"] = "smallcaps"
    language = source.get(XML + "lang", source.get("lang"))
    if not language:
        language = {"greek": "grc", "hebrew": "he"}.get(source.get("class", "").lower())
    if language:
        wanted[XML + "lang"] = {"EL": "grc", "HE": "he", "LA": "la", "FR": "fr", "DE": "de"}.get(language, language.lower())
    _assert(dict(actual.attrib) == wanted, f"attribute/target/formatting drift at {source_path}")


def validate_findlay_member(
    actual_member: etree._Element, source_bytes: bytes, member_id: str,
    source_title: str, text_corrections: list[Mapping[str, object]] | tuple[Mapping[str, object], ...] = (),
) -> dict[str, int]:
    """Validate one actual member; return measured source/candidate coverage."""
    _assert(hashlib.sha256(source_bytes).hexdigest() == SOURCE_HASHES.get(member_id), "source identity drift")
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    source_root = ET.fromstring(source_bytes, parser=parser)
    source_nodes = [node for node in source_root.iter() if isinstance(node.tag, str)]
    identifiers = {node: f"{member_id}-feature-{number:05d}" for number, node in enumerate(source_nodes, 1)}
    paths: dict[ET.Element, str] = {}

    def source_paths(node: ET.Element, path: str) -> None:
        paths[node] = path
        counts: Counter[str] = Counter()
        for child in node:
            if isinstance(child.tag, str):
                counts[child.tag] += 1
                source_paths(child, f"{path}/{child.tag}[{counts[child.tag]}]")

    source_paths(source_root, "/ThML[1]")
    bodies = [node for node in source_nodes if node.tag == "ThML.body"]
    _assert(len(bodies) == 1, "source body cardinality")
    body = bodies[0]
    _assert(not (body.tail or "").strip(), "substantive text outside the source body")
    body_elements = [node for node in body.iter() if isinstance(node.tag, str)]
    source_ids = {node.get("id"): identifiers[node] for node in body_elements if node.get("id")}
    _assert(len(source_ids) == sum(bool(n.get("id")) for n in body_elements), "duplicate source IDs")
    comment_count = 0
    comment_nodes: dict[ET.Element, tuple[str, str]] = {}
    for node in body.iter():
        if not isinstance(node.tag, str):
            comment_count += 1
            kind = "comment" if node.tag is ET.Comment else "processing-instruction"
            payload = node.text or ""
            if kind == "processing-instruction":
                payload = payload.partition(" ")[2]
            identifiers[node] = f"{member_id}-{kind}-{comment_count:05d}"
            comment_nodes[node] = (kind, hashlib.sha256(payload.encode("utf-8")).hexdigest())
    _assert(actual_member.tag == TEI + "div" and dict(actual_member.attrib) == {XML + "id":member_id,"type":"retained-source-member"}, "member shell")
    _assert(len(actual_member) == 2, "member must contain title and native source body")
    title, actual_body = actual_member
    _assert(title.tag == TEI + "head" and not title.attrib and len(title) == 0 and title.text == source_title and not title.tail, "member title")
    _assert(not actual_member.text and not actual_member.tail, "unbound member text")
    actual_nodes = list(actual_body.iter())
    actual_by_id = {node.get(XML + "id"):node for node in actual_nodes if node.get(XML + "id")}
    required_ids = {identifiers[node] for node in body.iter()}
    _assert(set(actual_by_id) == required_ids and len(actual_by_id) == sum(bool(n.get(XML + "id")) for n in actual_nodes), "source carrier ID set/cardinality")
    _assert(actual_body is actual_by_id[identifiers[body]], "native body attachment")
    corrections_by_field: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    correction_ids: set[str] = set()
    for row in text_corrections:
        _assert(row.get("member_id") == member_id, "correction member scope")
        selector = str(row["source_selector"])
        source_field = str(row["source_field"])
        _assert(source_field in {"text", "tail"}, "correction source field")
        correction_id = _text_correction_id(row)
        _assert(correction_id not in correction_ids, "duplicate correction authority")
        correction_ids.add(correction_id)
        corrections_by_field.setdefault((selector, source_field), []).append(row)
    allowed_choice_uris = {
        "urn:ocd:source-text-correction:" + correction_id
        for correction_id in correction_ids
    }
    actual_choices = list(actual_body.iter(TEI + "choice"))
    choices_by_corresp: dict[str, etree._Element] = {}
    for choice in actual_choices:
        corresp = choice.get("corresp")
        _assert(corresp in allowed_choice_uris, "unbound correction choice")
        _assert(corresp not in choices_by_corresp, "duplicate correction choice")
        choices_by_corresp[str(corresp)] = choice
    _assert(
        set(choices_by_corresp) == allowed_choice_uris
        and len(actual_choices) == len(correction_ids),
        "correction choice count/identity",
    )
    used_corrections: set[str] = set()
    virtual_count = 0
    synthetic_title_count = 0
    for source in body.iter():
        actual = actual_by_id[identifiers[source]]
        if source in comment_nodes:
            _assert((actual.tail or "") == (source.tail or ""), f"tail order/text at {identifiers[source]}")
            kind, digest = comment_nodes[source]
            _assert(actual.tag == TEI + "anchor" and dict(actual.attrib) == {XML+"id":identifiers[source],"type":"source-"+kind,"ana":f"urn:source-{kind}-sha256:{digest}"} and not actual.text and len(actual) == 0, "comment/PI anchor")
            continue
        _check_attributes(source, actual, identifiers[source], paths[source], source_ids)
        selector = paths[source]
        _validate_corrected_field(
            actual, source.text or "", member_id, selector, "text",
            corrections_by_field.get((selector, "text"), []),
            choices_by_corresp, used_corrections,
        )
        _validate_corrected_field(
            actual, source.tail or "", member_id, selector, "tail",
            corrections_by_field.get((selector, "tail"), []),
            choices_by_corresp, used_corrections,
        )
        observed_children: list[str] = []
        title_heads = []

        def inspect_children(container: etree._Element, virtual: bool = False) -> None:
            nonlocal virtual_count
            for child in container:
                identifier = child.get(XML + "id")
                if identifier:
                    _assert(identifier in required_ids, "unbound source child")
                    observed_children.append(identifier)
                elif child.tag == TEI + "div" and child.get("type") in {"source-content-group", "source-heading-section"}:
                    _assert(dict(child.attrib) == {"type":child.get("type"),"ana":"urn:ocd:source-parent-feature:"+identifiers[source]} and not child.text and not child.tail and len(child)>0, "compatibility wrapper provenance/text")
                    virtual_count += 1
                    inspect_children(child, True)
                elif child.tag == TEI + "p" and _semantic_tag(source) == "div":
                    _assert(dict(child.attrib) == {"ana":"urn:ocd:source-parent-feature:"+identifiers[source]} and not child.text and not child.tail and len(child)==1 and child[0].tag==TEI+"ref" and child[0].get(XML+"id") in required_ids, "inline reference compatibility paragraph")
                    virtual_count += 1
                    inspect_children(child, True)
                elif child.tag == TEI + "choice" and child.get("corresp") in allowed_choice_uris:
                    continue
                elif not virtual and child.tag == TEI + "head" and child.get("ana") == "urn:ocd:source-attribute:title":
                    _assert(dict(child.attrib) == {"ana":"urn:ocd:source-attribute:title"} and child.text == source.get("title") and not child.tail and len(child)==0 and child is actual[0], "attributed title head")
                    title_heads.append(child)
                else:
                    raise ValueError(f"Findlay native TEI: unbound child at {paths[source]}: {child.tag} {dict(child.attrib)}")

        inspect_children(actual)
        needs_title = source.tag in {"div", "div1", "div2", "div3", "div4"} and bool(source.get("title")) and not any(isinstance(c.tag,str) and c.tag in {"h1","h2","h3","h4","h5","h6"} for c in source)
        _assert(len(title_heads) == int(needs_title), f"title-head cardinality at {paths[source]}")
        synthetic_title_count += len(title_heads)
        _assert(observed_children == [identifiers[child] for child in source], f"source child order/attachment at {paths[source]}")
    _assert(used_corrections == correction_ids, "not every correction has one source projection")
    return {"source_elements":len(body_elements),"source_comments_and_pis":comment_count,"native_ids":len(actual_by_id),"compatibility_wrappers":virtual_count,"attributed_title_heads":synthetic_title_count,"source_body_ids":len(source_ids),"text_corrections":len(used_corrections)}
