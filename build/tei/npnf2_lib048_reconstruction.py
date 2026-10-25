"""Faithfully reconstruct the fifteen LIB-048 NPNF2 works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import tei_el


CONVERTER_ID = "ocd-npnf2-lib048-assigned-works-to-tei"
CONVERTER_VERSION = "2"
TEI_NS = "http://www.tei-c.org/ns/1.0"
SOURCES = (
    (
        "npnf206",
        "raw/ccel/npnf2/npnf206.xml",
        4_444_300,
        "6bf37affb240f5a775995ab2353c00569b34990130c98649a358f30f37f41f8d",
    ),
    (
        "npnf209",
        "raw/ccel/npnf2/npnf209.xml",
        3_088_610,
        "b07e2fac0851444a42d2bbd11d39eb7384c518f6fd79e64b7f7bdc404e8a3cc7",
    ),
    (
        "npnf212",
        "raw/ccel/npnf2/npnf212.xml",
        3_461_929,
        "f701b4ce5196bc5890e50adabce4900cd07b803f3221115a7cce526ae0a95570",
    ),
    (
        "npnf213",
        "raw/ccel/npnf2/npnf213.xml",
        2_246_124,
        "323ecfb6470854de378fdf47375b2e15b108e72559bbe3167da9c37500bbf2ae",
    ),
)
ASSIGNED = (
    ("npnf206", "v", "jerome-letters"),
    ("npnf206", "vi.i", "jerome-life-of-paulus"),
    ("npnf206", "vi.ii", "jerome-life-of-hilarion"),
    ("npnf206", "vi.iii", "jerome-life-of-malchus"),
    ("npnf206", "vi.iv", "jerome-dialogue-against-luciferians"),
    ("npnf206", "vi.v", "jerome-perpetual-virginity-of-mary"),
    ("npnf206", "vi.vi", "jerome-against-jovinianus"),
    ("npnf206", "vi.vii", "jerome-against-vigilantius"),
    ("npnf206", "vi.viii", "jerome-to-pammachius-against-john-of-jerusalem"),
    ("npnf206", "vi.ix", "jerome-against-pelagians"),
    ("npnf209", "ii", "hilary-of-poitiers-select-works"),
    ("npnf209", "iii", "john-of-damascus-orthodox-faith"),
    ("npnf212", "ii", "leo-the-great-letters-and-sermons"),
    ("npnf212", "iii", "gregory-the-great-pastoral-rule-and-epistles"),
    ("npnf213", "ii", "gregory-the-great-selected-epistles"),
)
TAG_MAP = {
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "div4": "div",
    "p": "p",
    "note": "note",
    "i": "hi",
    "span": "seg",
    "pb": "pb",
    "scripRef": "ref",
    "sup": "hi",
    "hr": "milestone",
    "img": "figure",
}
EXPECTED_CENSUS = {
    "elements": 53_294,
    "attributes": 115_741,
    "text_nodes": 39_394,
    "tail_nodes": 39_005,
    "characters": 7_718_481,
    "non_ascii_characters": 48_481,
    "notes": 10_138,
    "page_breaks": 1_542,
    "scripture_refs": 7_082,
}
IMAGE_ASSET = {
    "asset_id": "lib048-asset-npnf212-iii.iii-p86.1",
    "authority_name": "gregory-pedigree-image",
    "work_id": "gregory-the-great-pastoral-rule-and-epistles",
    "source_root_id": "iii",
    "source_member": "npnf212",
    "source_xml_id": "iii.iii-p86.1",
    "source_page": "https://ccel.org/ccel/schaff/npnf212/npnf212.iii.iii.html",
    "source_path": "raw/ccel/npnf2/npnf212/files/fig1.png",
    "source_url": "https://ccel.org/ccel/schaff/npnf212/files/fig1.png",
    "media_type": "image/png",
    "alt": "Pedigree of Kings of Gaul",
    "bytes": 44_462,
    "sha256": "a06e1fa626deadbfa78c1390ccd63408b7eea2a720c5b4542eda9e999cc616b5",
    "acquisition_receipt_path": "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-10-structural-audit/14-gregory-asset-acquisition.json",
    "acquisition_receipt_sha256": "4df83db9cf9c3e3f06066a36e62f75e3b110be89c7bef6a47fe6576723941adc",
    "acquired_at": "2026-09-10T11:25:44.179665+00:00",
    "historical_snapshot_bytes": "unknown",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    )


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value) or "source"


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _source_text(tree: etree._ElementTree, source_id: str) -> str:
    nodes = tree.xpath("//*[@id=$source_id]", source_id=source_id)
    if len(nodes) != 1:
        raise ValueError(f"retained credit evidence {source_id!r} drifted")
    return "".join(nodes[0].itertext())


def _source_metadata(tree: etree._ElementTree) -> dict[str, Any]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained source lacks ThML.head")
    return {
        "head_c14n_sha256": _sha(
            etree.tostring(head, method="c14n", with_comments=True)
        ),
        "dc_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/*")
        ],
        "print_source_entries": [
            {
                "tag": node.tag,
                "attributes": dict(node.attrib),
                "text": node.text or "",
                "tail": node.tail or "",
            }
            for node in tree.xpath("/ThML/ThML.head/printSourceInfo/*")
        ],
    }


def _document_accounting(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    before: list[dict[str, str]] = []
    node = root.getprevious()
    while node is not None:
        before.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getprevious()
    before.reverse()
    after: list[dict[str, str]] = []
    node = root.getnext()
    while node is not None:
        after.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getnext()
    return {
        "xml_version": tree.docinfo.xml_version,
        "encoding": tree.docinfo.encoding,
        "standalone": tree.docinfo.standalone,
        "doctype": tree.docinfo.doctype,
        "root_tag": root.tag,
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": {
            "" if key is None else key: value for key, value in root.nsmap.items()
        },
        "pre_root_nodes": before,
        "post_root_nodes": after,
    }


def _selected(
    trees: Mapping[str, etree._ElementTree],
) -> list[tuple[str, etree._Element, str]]:
    result = []
    for key, source_id, work_id in ASSIGNED:
        matches = trees[key].xpath("//*[@id=$source_id]", source_id=source_id)
        if len(matches) != 1:
            raise ValueError(f"exact assigned root drift: {key} {source_id}")
        result.append((key, matches[0], work_id))
    return result


def _census(nodes: list[etree._Element]) -> dict[str, int]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in nodes]
    return {
        "elements": len(elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len(value) for value in strings),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in value) for value in strings
        ),
        "notes": sum(node.tag == "note" for node in elements),
        "page_breaks": sum(node.tag == "pb" for node in elements),
        "scripture_refs": sum(node.tag == "scripRef" for node in elements),
    }


def _target_tag(source: etree._Element) -> str:
    if source.tag == "span" and source.get("lang"):
        return "foreign"
    return TAG_MAP[str(source.tag)]


def _reference_exception_map(policy: Mapping[str, Any]) -> dict[tuple[str, str, str], str]:
    try:
        entries = policy["projection"]["reference_classification"][
            "neutral_non_scripture_exceptions"
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError("reference classification policy is incomplete") from exc
    if not isinstance(entries, list) or len(entries) != 31:
        raise ValueError("reference classification policy must declare 31 exceptions")
    assigned_roots = {(key, root_id) for key, root_id, _work_id in ASSIGNED}
    result: dict[tuple[str, str, str], str] = {}
    required = {"source_member", "source_root_id", "source_xml_id", "passage"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError("reference classification exception shape drift")
        if not all(isinstance(entry[name], str) for name in required):
            raise ValueError("reference classification exception value drift")
        key = (
            entry["source_member"],
            entry["source_root_id"],
            entry["source_xml_id"],
        )
        if (key[0], key[1]) not in assigned_roots or not entry["passage"].startswith(
            "Ep."
        ):
            raise ValueError("reference classification exception binding drift")
        if key in result:
            raise ValueError("duplicate reference classification exception")
        result[key] = entry["passage"]
    return result


def _validate_reference_exceptions(
    exceptions: Mapping[tuple[str, str, str], str],
    selected: list[tuple[str, etree._Element, str]],
) -> None:
    matched: set[tuple[str, str, str]] = set()
    for key, root, _work_id in selected:
        root_id = root.get("id")
        for node in root.iter("scripRef"):
            exception_key = (key, root_id or "", node.get("id") or "")
            if exception_key not in exceptions:
                continue
            if exception_key in matched:
                raise ValueError(
                    "duplicate reference classification exception source at "
                    f"{_selector(node)}"
                )
            if (
                node.get("passage") != exceptions[exception_key]
                or node.get("osisRef") is not None
                or set(node.attrib) != {"id", "passage"}
            ):
                raise ValueError(
                    "reference classification exception source drift at "
                    f"{_selector(node)}"
                )
            matched.add(exception_key)
    if matched != set(exceptions):
        missing = sorted(set(exceptions) - matched)
        raise ValueError(f"reference classification exception not found: {missing}")


def _is_neutral_reference(
    source: etree._Element,
    key: str,
    source_root_id: str,
    exceptions: Mapping[tuple[str, str, str], str],
) -> bool:
    if source.tag != "scripRef":
        return False
    exception_key = (key, source_root_id, source.get("id") or "")
    expected_passage = exceptions.get(exception_key)
    if expected_passage is None:
        return False
    if (
        source.get("passage") != expected_passage
        or source.get("osisRef") is not None
        or set(source.attrib) != {"id", "passage"}
    ):
        raise ValueError(
            "reference classification exception source drift at "
            f"{_selector(source)}"
        )
    return True


def _target_attrs(
    source: etree._Element,
    key: str,
    ordinal: int,
    work_id: str | None,
    source_root_id: str,
    reference_exceptions: Mapping[tuple[str, str, str], str],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    attrs = {
        "xml:id": f"lib048-{key}-{ordinal:06d}-{_safe(source.get('id') or str(source.tag))}"
    }
    dispositions: list[dict[str, str]] = []
    tag = str(source.tag)
    neutral_reference = _is_neutral_reference(
        source, key, source_root_id, reference_exceptions
    )
    for name, value in source.attrib.items():
        destination, method = (
            "source-accountability",
            "preserved-exactly-in-accountability",
        )
        if name == "id":
            destination, method = (
                "@xml:id-and-source-accountability",
                "deterministic-member-and-ordinal-prefix",
            )
        elif name == "n" and tag in {"div1", "div2", "div3", "div4", "note", "pb"}:
            attrs["n"], destination = value, "@n"
        elif name == "type" and tag in {"div1", "div2", "div3", "div4"} and not work_id:
            attrs["type"], destination = value, "@type"
        elif name == "class" and tag in {"p", "span"}:
            attrs["rend"], destination = value, "@rend"
        elif name == "style" and tag in {"p", "hr"}:
            attrs["rend"], destination = value, "@rend"
        elif name == "place" and tag == "note":
            attrs["place"], destination = value, "@place"
        elif name == "href" and tag == "pb":
            attrs["facs"], destination = value, "@facs"
        elif name == "passage" and tag == "scripRef" and not neutral_reference:
            attrs["cRef"], destination = value, "@cRef"
        elif name == "osisRef" and tag == "scripRef" and not neutral_reference:
            attrs["target"], destination = value, "@target"
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = {"EL": "grc", "HE": "he", "LA": "la"}.get(
                value, value.lower()
            )
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name == "dir" and tag == "span":
            attrs["rend"] = (attrs.get("rend", "") + f" direction:{value}").strip()
            destination = "@rend"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        elif name == "src" and tag == "img":
            destination, method = "child::graphic/@url", "retained-source-asset-url"
        elif name == "alt" and tag == "img":
            destination, method = "child::figDesc", "retained-source-image-alt"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    if work_id:
        attrs.update({"type": "work", "subtype": work_id})
    elif tag.startswith("div") and "type" not in attrs:
        attrs["type"] = f"source-{tag}"
    elif tag == "i":
        attrs["rend"] = "italic"
    elif tag == "sup":
        attrs["rend"] = "superscript"
    elif tag == "scripRef" and not neutral_reference:
        attrs["type"] = "scripture"
    elif tag == "span" and "lang" not in source.attrib:
        attrs["type"] = "source-span"
    elif tag == "hr":
        attrs["unit"] = "horizontal-rule"
    elif tag == "img":
        attrs["type"] = "source-img"
    return attrs, dispositions


def _append(
    source: etree._Element,
    parent: etree._Element,
    key: str,
    rows: list[dict[str, Any]],
    parent_feature_id: str | None,
    work_id: str | None = None,
    reference_exceptions: Mapping[tuple[str, str, str], str] | None = None,
    source_root_id: str | None = None,
) -> None:
    if not isinstance(source.tag, str) or source.tag not in TAG_MAP:
        raise ValueError(f"unsupported assigned source node {source.tag!r}")
    ordinal = len(rows) + 1
    feature_id = f"lib048-feature-{ordinal:06d}"
    if reference_exceptions is None or source_root_id is None:
        raise ValueError("reference classification context is required")
    attrs, dispositions = _target_attrs(
        source,
        key,
        ordinal,
        work_id,
        source_root_id,
        reference_exceptions,
    )
    tag = _target_tag(source)
    target = tei_el(tag, attrs)
    target.text, target.tail = source.text or "", source.tail or ""
    if source.tag == "img":
        target.append(tei_el("graphic", {"url": source.get("src", "")}))
        target.append(tei_el("figDesc", text=source.get("alt", "")))
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        target.insert(0, tei_el("head", text=title))
    wrapper_id: str | None = None
    if etree.QName(parent).localname == "div" and tag in {
        "ref",
        "seg",
        "foreign",
        "hi",
    }:
        wrapper_id = f"lib048-inline-wrapper-{ordinal:06d}"
        wrapper = tei_el(
            "ab", {"xml:id": wrapper_id, "type": "source-inline-container"}
        )
        wrapper.append(target)
        parent.append(wrapper)
    else:
        parent.append(target)
    rows.append(
        {
            "feature_id": feature_id,
            "parent_feature_id": parent_feature_id,
            "source_member": key,
            "source_selector": _selector(source),
            "source_tag": source.tag,
            "source_xml_id": source.get("id"),
            "source_attributes": dict(source.attrib),
            "direct_text_length": len(source.text or ""),
            "direct_text_sha256": _sha((source.text or "").encode()),
            "tail_text_length": len(source.tail or ""),
            "tail_text_sha256": _sha((source.tail or "").encode()),
            "source_title_head": title,
            "tei_tag": tag,
            "tei_xml_id": attrs["xml:id"],
            "tei_attributes": attrs,
            "tei_wrapper_id": wrapper_id,
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            **({"work_id": work_id} if work_id else {}),
        }
    )
    for child in source:
        _append(
            child,
            target,
            key,
            rows,
            feature_id,
            reference_exceptions=reference_exceptions,
            source_root_id=source_root_id,
        )


def _header(trees: Mapping[str, etree._ElementTree]) -> etree._Element:
    root = tei_el("TEI", {"xml:id": "npnf2-lib048-candidate"})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    for key in ("npnf206", "npnf209", "npnf212", "npnf213"):
        title = "".join(
            str(v)
            for v in trees[key].xpath(
                "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
            )
        )
        title_stmt.append(
            tei_el("title", {"type": "retained-electronic-title", "n": key}, title)
        )
    title_stmt.append(tei_el("editor", text="Philip Schaff"))
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(
        tei_el(
            "publisher", text="Grand Rapids, MI: Christian Classics Ethereal Library"
        )
    )
    availability = tei_el("availability")
    availability.append(tei_el("p", text="Public Domain"))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    list_bibl = tei_el("listBibl")
    credit_ids = {
        "npnf206": ("ii-p2", "ii-p4", "ii-p7", "ii-p10", "iii-p4", "iii-p7"),
        "npnf209": (
            "ii.i-p3",
            "ii.i-p5",
            "ii.i-p7",
            "ii.i-p12",
            "iii.i-p3",
            "iii.i-p5",
            "iii.ii-p4",
        ),
        "npnf212": ("ii.i-p6", "ii.i-p8", "iii.i-p8", "iii.i-p10"),
        "npnf213": ("ii.i-p6", "ii.i-p8"),
    }
    for key in ("npnf206", "npnf209", "npnf212", "npnf213"):
        tree = trees[key]
        bibl = tei_el("bibl", {"xml:id": f"source-{key}"})
        title = "".join(
            str(v)
            for v in tree.xpath(
                "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
            )
        )
        bibl.append(tei_el("title", text=title))
        bibl.append(tei_el("editor", text="Philip Schaff"))
        published = "".join(
            str(v)
            for v in tree.xpath("/ThML/ThML.head/printSourceInfo/published/text()")
        )
        if published:
            bibl.append(tei_el("publisher", text=published))
        rights = "".join(
            str(v)
            for v in tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/DC.Rights/text()")
        )
        bibl.append(tei_el("note", {"type": "rights"}, rights))
        url = "".join(
            str(v)
            for v in tree.xpath(
                "/ThML/ThML.head/electronicEdInfo/DC/DC.Identifier[@scheme='URL']/text()"
            )
        )
        bibl.append(tei_el("idno", {"type": "CCEL-path"}, url))
        for source_id in credit_ids[key]:
            bibl.append(
                tei_el(
                    "note",
                    {
                        "type": "retained-title-page-or-preface-credit",
                        "source": f"#{source_id}",
                    },
                    _source_text(tree, source_id),
                )
            )
        list_bibl.append(bibl)
    source_desc.append(list_bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    return root


def _division_accounting(
    tree: etree._ElementTree, assigned_ids: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained source has no ThML.body")
    top = []
    for ordinal, node in enumerate(
        [child for child in body if isinstance(child.tag, str)], 1
    ):
        assigned = node.get("id") in assigned_ids
        descendant = any(
            child.get("id") in assigned_ids for child in node.iterdescendants()
        )
        top.append(
            {
                "ordinal": ordinal,
                "tag": node.tag,
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-root-represented"
                if assigned
                else "container-with-assigned-descendants"
                if descendant
                else "source-evidence-outside-work-projection",
                "reason": "complete subtree represented"
                if assigned
                else "container shell retained; assigned descendants represented separately"
                if descendant
                else "title/front/prefatory/sibling/index matter outside exact assigned work roots",
            }
        )
    direct = []
    for ordinal, node in enumerate(tree.xpath("//ThML.body/div1/div2"), 1):
        included = node.get("id") in assigned_ids or any(
            ancestor.get("id") in assigned_ids for ancestor in node.iterancestors()
        )
        direct.append(
            {
                "ordinal": ordinal,
                "parent_div1_id": node.getparent().get("id"),
                "id": node.get("id"),
                "title": node.get("title", ""),
                "disposition": "assigned-work-subtree-represented"
                if included
                else "outside-assigned-work-scope",
                "reason": "complete subtree represented in retained order"
                if included
                else "not an assigned root or descendant",
            }
        )
    return top, direct


def _image_binding(
    source_manifest: SourceManifest,
    selected: list[tuple[str, etree._Element, str]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind the one retained Gregory image to exact current asset evidence."""

    image_nodes = [
        (key, work_id, node)
        for key, root, work_id in selected
        for node in root.iter("img")
    ]
    if len(image_nodes) != 1:
        raise ValueError(f"assigned source image inventory drift: {len(image_nodes)}")
    key, work_id, source = image_nodes[0]
    if (
        key != IMAGE_ASSET["source_member"]
        or work_id != IMAGE_ASSET["work_id"]
        or source.getparent().getparent().getparent().get("id")
        != IMAGE_ASSET["source_root_id"]
        or dict(source.attrib) != {
        "id": IMAGE_ASSET["source_xml_id"],
        "src": IMAGE_ASSET["source_url"].removeprefix("https://ccel.org"),
        "alt": IMAGE_ASSET["alt"],
        }
    ):
        raise ValueError("Gregory source image identity or metadata drift")
    parent = source.getparent()
    if parent is None or parent.get("id") != "iii.iii-p86":
        raise ValueError("Gregory source image parent placement drift")
    source_selector = _selector(source)
    if source_selector != "ThML.body/div1[3]/div2[3]/p[82]/img[1]":
        raise ValueError("Gregory source image selector drift")

    asset_authority = next(item for item in source_manifest.record["authorities"] if item["name"] == "gregory-pedigree-image")
    if asset_authority.get("path") != IMAGE_ASSET["source_path"] or tuple(asset_authority.get("work_ids", ())) != (IMAGE_ASSET["work_id"],):
        raise ValueError("Gregory source authority path or work scope drifted")
    asset_path = source_manifest.authority_path("gregory-pedigree-image")
    asset_bytes = asset_path.read_bytes()
    if len(asset_bytes) != IMAGE_ASSET["bytes"] or _sha(asset_bytes) != IMAGE_ASSET["sha256"]:
        raise ValueError("Gregory retained image asset bytes drifted")
    if not asset_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Gregory retained image is not a PNG")

    receipt = json.loads(
        source_manifest.authority_path("gregory-pedigree-acquisition").read_bytes()
    )
    expected_receipt = {
        "source_page": IMAGE_ASSET["source_page"],
        "url": IMAGE_ASSET["source_url"],
        "final_url": IMAGE_ASSET["source_url"],
        "content_type": IMAGE_ASSET["media_type"],
        "bytes": IMAGE_ASSET["bytes"],
        "sha256": IMAGE_ASSET["sha256"],
        "retrieved_at": IMAGE_ASSET["acquired_at"],
    }
    if any(receipt.get(name) != value for name, value in expected_receipt.items()):
        raise ValueError("Gregory image acquisition receipt drifted")

    row = next(
        (
            item
            for item in rows
            if item["source_member"] == key
            and item["source_xml_id"] == IMAGE_ASSET["source_xml_id"]
        ),
        None,
    )
    if row is None:
        raise ValueError("Gregory source image crosswalk binding is missing")
    rows_by_feature = {item["feature_id"]: item for item in rows}
    parent_row = rows_by_feature.get(row["parent_feature_id"])
    if parent_row is None:
        raise ValueError("Gregory source image candidate parent binding is missing")
    binding = {
        **IMAGE_ASSET,
        "source_selector": source_selector,
        "source_parent_id": parent.get("id"),
        "tei_xml_id": row["tei_xml_id"],
        "candidate_parent_xml_id": parent_row["tei_xml_id"],
    }
    expected = {
        "tei_xml_id": "lib048-npnf212-043142-iii.iii-p86.1",
        "candidate_parent_xml_id": "lib048-npnf212-043141-iii.iii-p86",
    }
    # The deterministic IDs are part of the package placement contract.
    # Keep this explicit so a source reordering cannot silently move the image.
    if any(binding[name] != value for name, value in expected.items()):
        raise ValueError("Gregory candidate image placement drifted")
    return binding


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    policy = json.loads(
        source_manifest.authority_path("validation-policy").read_bytes()
    )
    reference_exceptions = _reference_exception_map(policy)
    trees: dict[str, etree._ElementTree] = {}
    source_bytes: dict[str, bytes] = {}
    for key, _path, expected_bytes, expected_sha in SOURCES:
        path = source_manifest.authority_path(f"retained-{key}")
        content = path.read_bytes()
        if len(content) != expected_bytes or _sha(content) != expected_sha:
            raise ValueError(f"retained {key} authority drift")
        source_bytes[key] = content
        trees[key] = _parse(path)
    selected = _selected(trees)
    _validate_reference_exceptions(reference_exceptions, selected)
    root = _header(trees)
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "npnf2-lib048-assigned-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, Any]] = []
    work_bindings = []
    for key, source_root, work_id in selected:
        before = len(rows)
        _append(
            source_root,
            body,
            key,
            rows,
            None,
            work_id,
            reference_exceptions,
            source_root.get("id"),
        )
        work_bindings.append(
            {
                "work_id": work_id,
                "source_key": key,
                "source_member": dict((k, p) for k, p, _b, _s in SOURCES)[key],
                "source_root_id": source_root.get("id"),
                "source_root_selector": _selector(source_root),
                "feature_count": len(rows) - before,
            }
        )
    asset_binding = _image_binding(source_manifest, selected, rows)
    assigned_nodes = [
        node
        for _key, selected_root, _work_id in selected
        for node in selected_root.iter()
    ]
    assigned_census = _census(assigned_nodes)
    if assigned_census != EXPECTED_CENSUS:
        raise ValueError(f"assigned source census drift: {assigned_census}")
    members = []
    top_accounting = {}
    direct_accounting = {}
    for key, path, expected_bytes, expected_sha in SOURCES:
        full = list(trees[key].getroot().iter())
        member_selected = [
            node
            for selected_key, selected_root, _work_id in selected
            if selected_key == key
            for node in selected_root.iter()
        ]
        complete, assigned = _census(full), _census(member_selected)
        top, direct = _division_accounting(
            trees[key],
            {
                source_id
                for source_key, source_id, _work_id in ASSIGNED
                if source_key == key
            },
        )
        top_accounting[key], direct_accounting[key] = top, direct
        members.append(
            {
                "key": key,
                "path": path,
                "bytes": expected_bytes,
                "sha256": expected_sha,
                "disposition": "included retained authority; assigned roots represented and all remaining member scope explicitly accounted outside work projection",
                "document_accounting": _document_accounting(trees[key]),
                "complete_document_census": complete,
                "assigned_scope_census": assigned,
                "excluded_scope_census": {
                    name: complete[name] - assigned[name] for name in complete
                },
            }
        )
    accountability = {
        "contract": "ocd-npnf2-lib048-source-accountability-v2",
        "schema": "npnf2-lib048.source-accountability.schema.json",
        "profile_id": "npnf2-lib048-fifteen-work-v2",
        "assigned_work_count": 15,
        "source_member_count": 4,
        "asset_count": 1,
        "feature_count": len(rows),
        "attribute_count": assigned_census["attributes"],
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "assigned_census": assigned_census,
        "member_accounting": members,
        "top_level_division_accounting": top_accounting,
        "direct_div2_accounting": direct_accounting,
        "work_bindings": work_bindings,
        "asset_bindings": [asset_binding],
        "crosswalk": rows,
    }
    credits = {
        "npnf206": ["W. H. Fremantle", "G. Lewis", "W. G. Martley"],
        "npnf209": [
            "E. W. Watson",
            "L. Pullan",
            "W. Sanday",
            "S. D. F. Salmond",
            "James L. Salmond",
        ],
        "npnf212": ["Charles Lett Feltoe", "James Barmby"],
        "npnf213": ["James Barmby"],
    }
    credit_evidence_ids = {
        "npnf206": ["ii-p2", "ii-p4", "ii-p7", "ii-p10", "iii-p4", "iii-p7"],
        "npnf209": [
            "ii.i-p3",
            "ii.i-p5",
            "ii.i-p7",
            "ii.i-p12",
            "iii.i-p3",
            "iii.i-p5",
            "iii.ii-p4",
        ],
        "npnf212": ["ii.i-p6", "ii.i-p8", "iii.i-p8", "iii.i-p10"],
        "npnf213": ["ii.i-p6", "ii.i-p8"],
    }
    provenance = {
        "contract": "ocd-npnf2-lib048-provenance-v2",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "publication_state": "not_ready",
        "asset_bindings": [asset_binding],
        "source_edition_relationship": {
            "status": "edition-consistent-current-supplemental",
            "retained_source_member": "npnf212",
            "retained_source_sha256": "f701b4ce5196bc5890e50adabce4900cd07b803f3221115a7cce526ae0a95570",
            "retained_source_parent_id": "iii.iii-p86",
            "retained_source_xml_id": "iii.iii-p86.1",
            "retained_source_url": "https://ccel.org/ccel/schaff/npnf212/files/fig1.png",
            "current_asset_sha256": asset_binding["sha256"],
            "historical_snapshot_bytes": "unknown",
            "evidence": "The retained XML source path, image id, alt label, parent locus, and current CCEL image URL agree; the current retrieval is supplemental evidence and does not prove historical snapshot bytes.",
        },
        "sources": {
            key: {
                "path": path,
                "bytes": size,
                "sha256": digest,
                "metadata": _source_metadata(trees[key]),
                "retained_title_page_and_preface_credit_evidence": {
                    source_id: _source_text(trees[key], source_id)
                    for source_id in credit_evidence_ids[key]
                },
                "display_credit_names": credits[key],
            }
            for key, path, size, digest in SOURCES
        },
        "works": [
            {
                **binding,
                "translation_credit": {
                    "status": "retained-source-level-credit",
                    "credited_to": credits[binding["source_key"]],
                    "work_specific_allocation": None,
                },
                "human_review": "required",
                "accepted_ir": "not_accepted",
                "publication": "not_ready",
            }
            for binding in work_bindings
        ],
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {
            "id": "npnf2-lib048-work-specific-credit-allocation",
            "scope": "all-fifteen-assigned-works",
            "status": "unresolved",
            "evidence": "Retained title pages and prefaces are preserved exactly at source level; no unsupported work-level allocation is inferred.",
        },
        {
            "id": "npnf2-lib048-print-collation",
            "scope": "four-retained-electronic-witnesses",
            "status": "unresolved",
            "evidence": "The candidate is bound to retained CCEL XML; cited print editions were not collated.",
        },
        {
            "id": "npnf2-lib048-rights-human-acceptance-publication",
            "scope": "all-fifteen-assigned-works",
            "status": "unresolved",
            "evidence": "Retained headers state Public Domain; technical verification is not human acceptance or publication authorization.",
        },
    ]
    return {
        "README.source.md": source_manifest.authority_path(
            "source-local-attribution-readme"
        ).read_bytes(),
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
