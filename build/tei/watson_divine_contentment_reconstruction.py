"""Complete-present-carrier ThML reconstruction for ticket 37c-316.

The route binds one retained Watson member and maps every present source
element.  The missing VI/VII carriers remain an explicit source-completeness
question; no replacement text is invented.  The output is a disposable,
nonaccepted candidate package.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.library.identities import load_work
from ocd_kernel.tei.writer import stamp_header, tei_el


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_PATH = "raw/ccel/watson/contentment.xml"

TAGS = {
    "div1": "div",
    "div2": "div",
    "div": "div",
    "p": "p",
    "h1": "head",
    "h2": "head",
    "h3": "head",
    "h4": "head",
    "i": "hi",
    "b": "hi",
    "br": "lb",
    "scripRef": "ref",
    "a": "ref",
    "note": "note",
    "insertIndex": "milestone",
}

EXPECTED_SOURCE_TAGS = frozenset(TAGS)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _selection_digest(selection: dict[str, Any]) -> str:
    return _sha(json.dumps(selection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _load_route_acquisition(manifest, root_path: Path, work: dict[str, Any]) -> dict[str, Any]:
    path = manifest.authority_path("acquisition")
    record = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((root_path / "schemas/v2/acquisition.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(record), key=str)
    if errors:
        raise ValueError(f"Watson acquisition schema failure: {errors[0].message}")
    if record["edition_id"] != "watson-divine-contentment-ccel-thml" or record["source_path"] != SOURCE_PATH:
        raise ValueError("Watson acquisition identity or source path drifted")
    retained = record["retained_files"]
    if len(retained) != 1 or retained[0]["path"] != SOURCE_PATH:
        raise ValueError("Watson route requires exactly one retained source member")
    raw_path = manifest.authority_path("retained-source")
    raw = raw_path.read_bytes()
    if len(raw) != record["source_bytes"] or _sha(raw) != record["source_sha256"] or retained[0]["bytes"] != len(raw) or retained[0]["sha256"] != _sha(raw):
        raise ValueError("Watson acquisition retained-source binding drifted")
    selection = record.get("source_selection")
    if not isinstance(selection, dict) or selection.get("work_id") != work["work_id"] or selection.get("member_path") != SOURCE_PATH:
        raise ValueError("Watson complete-present source selector is invalid")
    evidence = set(work.get("evidence", []))
    selected_ids = [unit.get("native_id") for unit in selection.get("units", [])]
    if len(selected_ids) != len(set(selected_ids)) or any(f"{SOURCE_PATH}#{native_id}" not in evidence for native_id in selected_ids):
        raise ValueError("Watson source selector and work evidence differ")
    return record


def _local(tag: str) -> str:
    return etree.QName(tag).localname if tag.startswith("{") else tag


def _source_selector(tree: etree._ElementTree, node: etree._Element) -> str:
    return tree.getpath(node)


def _text_bytes(node: etree._Element) -> int:
    return len((node.text or "").encode("utf-8"))


def _tail_bytes(node: etree._Element) -> int:
    return len((node.tail or "").encode("utf-8"))


def _document_shell(raw: bytes, tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    head_children: list[dict[str, Any]] = []
    if head is not None:
        for position, child in enumerate(head):
            head_children.append(
                {
                    "position": position,
                    "source_selector": _source_selector(tree, child),
                    "source_tag": child.tag,
                    "attributes": dict(sorted(child.attrib.items())),
                    "text": "".join(child.itertext()),
                    "tail": child.tail or "",
                    "element_count": sum(1 for _ in child.iter()),
                }
            )
    return {
        "xml_declaration": (
            raw.split(b"?>", 1)[0].decode("ascii") + "?>"
            if raw.startswith(b"<?xml") and b"?>" in raw
            else None
        ),
        "doctype": tree.docinfo.doctype or None,
        "root": {
            "source_selector": _source_selector(tree, root),
            "source_tag": root.tag,
            "attributes": dict(sorted(root.attrib.items())),
        },
        "head": {
            "source_selector": _source_selector(tree, head) if head is not None else None,
            "element_count": sum(1 for _ in head.iter()) if head is not None else 0,
            "children": head_children,
        },
        "body": {
            "source_selector": _source_selector(tree, body) if body is not None else None,
            "element_count": sum(1 for _ in body.iter()) if body is not None else 0,
            "carrier_count": sum(1 for child in (body if body is not None else []) if child.tag == "div1"),
        },
    }


def _source_features(
    tree: etree._ElementTree, root: etree._Element
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, int]]:
    body = root.find("ThML.body")
    if body is None:
        raise ValueError("retained source has no ThML.body")
    body_path = tree.getpath(body)
    tei_ids: dict[str, str] = {}
    body_ordinal = 0
    features: list[dict[str, Any]] = []
    tag_counts: dict[str, int] = {}
    attr_counts: dict[str, int] = {}
    for ordinal, node in enumerate(root.iter(), 1):
        selector = _source_selector(tree, node)
        parent = node.getparent()
        position = list(parent).index(node) if parent is not None else None
        in_body = selector.startswith(body_path + "/")
        tei_id = None
        if in_body:
            body_ordinal += 1
            tei_id = f"src-{body_ordinal}"
            tei_ids[selector] = tei_id
        disposition = (
            "represented-in-tei"
            if in_body
            else "accounted-source-document-shell"
        )
        tag_counts[node.tag] = tag_counts.get(node.tag, 0) + 1
        for name in node.attrib:
            attr_counts[name] = attr_counts.get(name, 0) + 1
        features.append(
            {
                "ordinal": ordinal,
                "source_selector": selector,
                "parent_selector": _source_selector(tree, parent) if parent is not None else None,
                "child_position": position,
                "source_tag": node.tag,
                "native_id": node.get("id"),
                "attributes": dict(sorted(node.attrib.items())),
                "text": node.text or "",
                "tail": node.tail or "",
                "disposition": disposition,
                "tei_id": tei_id,
            }
        )
    represented_count = sum(1 for row in features if row["disposition"] == "represented-in-tei")
    return features, tei_ids, {"elements": len(features), "attributes": sum(attr_counts.values()), "text_utf8_bytes": sum(_text_bytes(n) for n in root.iter()), "tail_utf8_bytes": sum(_tail_bytes(n) for n in root.iter()), "body_elements": represented_count, "represented_elements": represented_count, "head_elements": sum(1 for n in root.find("ThML.head").iter()) if root.find("ThML.head") is not None else 0, "tag_counts": dict(sorted(tag_counts.items())), "attribute_counts": dict(sorted(attr_counts.items()))}


def _carrier_inventory(tree: etree._ElementTree, root: etree._Element) -> list[dict[str, Any]]:
    body = root.find("ThML.body")
    if body is None:
        raise ValueError("retained source has no ThML.body")
    rows: list[dict[str, Any]] = []
    for position, node in enumerate(body):
        if node.tag != "div1":
            raise ValueError(f"unexpected non-div1 body carrier: {node.tag}")
        rows.append(
            {
                "position": position,
                "native_id": node.get("id"),
                "source_tag": node.tag,
                "source_title": node.get("title"),
                "progress": node.get("progress"),
                "prev": node.get("prev"),
                "next": node.get("next"),
                "tei_region": "front" if node.get("id") in {"i", "ii"} else ("back" if node.get("id") == "xix" else "body"),
                "disposition": "represented-present-carrier",
            }
        )
    if [row["native_id"] for row in rows] != ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix"]:
        raise ValueError("retained Watson carrier order drifted")
    return rows


def _verify_present_carrier_accounting(
    acquisition: dict[str, Any], carriers: list[dict[str, Any]]
) -> None:
    """Check the complete present carrier union without widening shared code."""

    expected = [row["native_id"] for row in carriers]
    selected = [unit["native_id"] for unit in acquisition["source_selection"]["units"]]
    if selected != expected:
        raise ValueError("Watson acquisition selection omits, duplicates, or reorders present carriers")
    if any(row["disposition"] != "represented-present-carrier" for row in carriers):
        raise ValueError("Watson carrier accounting has a non-present disposition")


def _tei_attributes(source: etree._Element, tag: str, tei_id: str, internal_targets: dict[str, str]) -> dict[str, str]:
    attrs: dict[str, str] = {"xml:id": tei_id, "ana": f"source-tag:{tag}"}
    source_id = source.get("id")
    if source_id:
        attrs["n"] = source.get("n") or source_id
    elif source.get("n"):
        attrs["n"] = source.get("n") or ""
    if source.get("class"):
        attrs["rend"] = source.get("class") or ""
    if source.get("style"):
        attrs["style"] = source.get("style") or ""
    if source.get("lang"):
        attrs["xml:lang"] = source.get("lang") or ""
    if tag == "i":
        attrs["rend"] = (attrs.get("rend", "") + " italic").strip()
    elif tag == "b":
        attrs["rend"] = (attrs.get("rend", "") + " bold").strip()
    if tag in {"h3", "h4"} and source.getparent() is not None and list(source.getparent()).index(source) == 0:
        attrs["type"] = f"thml-{tag}"
    if tag in HEADING_TAGS and source.getparent() is not None and list(source.getparent()).index(source) != 0:
        attrs["rend"] = (attrs.get("rend", "") + " heading").strip()
    if tag == "scripRef":
        if source.get("passage"):
            attrs["cRef"] = source.get("passage") or ""
        if source.get("osisRef"):
            attrs["target"] = source.get("osisRef") or ""
    if tag == "a" and source.get("href"):
        href = source.get("href") or ""
        attrs["target"] = internal_targets.get(href[1:], href) if href.startswith("#") else href
    if tag == "note":
        if source.get("place"):
            attrs["place"] = source.get("place") or ""
        if source.get("anchored") in {"yes", "no"}:
            attrs["anchored"] = "true" if source.get("anchored") == "yes" else "false"
    if tag == "insertIndex":
        attrs["unit"] = "insertIndex"
        attrs["n"] = source.get("type") or source_id or "insertIndex"
    return attrs


def _tei_tag(source: etree._Element) -> str:
    if source.tag in HEADING_TAGS and source.getparent() is not None and list(source.getparent()).index(source) != 0:
        return "p"
    return TAGS[source.tag]


def _metadata_lines(root: etree._Element) -> list[str]:
    head = root.find("ThML.head")
    if head is None:
        return []
    lines: list[str] = []
    for node in head.iter():
        text = " ".join("".join(node.itertext()).split())
        if text and len(node) == 0:
            attrs = " ".join(f"{key}={value}" for key, value in sorted(node.attrib.items()))
            lines.append(f"- `{node.tag}`" + (f" ({attrs})" if attrs else "") + f": {text}")
    return lines


def _convert(manifest):
    manifest.verify()
    root_path = manifest.repository_root
    work = load_work(manifest.authority_path("work"))
    acquisition = _load_route_acquisition(manifest, root_path, work)
    raw = manifest.authority_path("retained-source").read_bytes()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False)
    tree = etree.ElementTree(etree.fromstring(raw, parser))
    source_root = tree.getroot()
    if source_root.tag != "ThML" or source_root.find("ThML.head") is None or source_root.find("ThML.body") is None:
        raise ValueError("Watson retained source is not the expected ThML envelope")
    source_tags = {_local(node.tag) for node in source_root.find("ThML.body").iter()}
    if not source_tags <= EXPECTED_SOURCE_TAGS | {"ThML.body"}:
        raise ValueError(f"unmapped Watson source tags: {sorted(source_tags - EXPECTED_SOURCE_TAGS - {'ThML.body'})}")

    features, tei_ids, feature_census = _source_features(tree, source_root)
    carriers = _carrier_inventory(tree, source_root)
    expected_ids = [row["native_id"] for row in carriers]
    source_by_id = {node.get("id"): node for node in source_root.find("ThML.body") if node.tag == "div1"}
    _verify_present_carrier_accounting(acquisition, carriers)
    if any(
        source_by_id.get(unit["native_id"]) is None
        or source_by_id[unit["native_id"]].get("title") != unit["title"]
        for unit in acquisition["source_selection"]["units"]
    ):
        raise ValueError("Watson source selector title differs from retained carrier")
    verified_selection_sha256 = _selection_digest(acquisition["source_selection"])

    form = next(form for form in work["textual_forms"] if any(edition["edition_id"] == acquisition["edition_id"] for edition in form["editions"]))
    edition = next(edition for edition in form["editions"] if edition["edition_id"] == acquisition["edition_id"])
    root = tei_el("TEI", {"xml:id": work["work_id"]})
    author = "; ".join(item["name"] for item in work.get("creators", []) if item.get("role") == "author")
    header = stamp_header(
        title=work["title"],
        author=author,
        contributors=[],
        source_url=acquisition["url"],
        source_sha256=acquisition["source_sha256"],
        print_source="Retained CCEL ThML electronic source; exact print exemplar and lineage unresolved.",
    )
    root.append(header)
    ns = {"t": TEI_NS}
    binding = header.find(".//t:bibl", ns)
    if binding is None:
        raise ValueError("TEI header source binding is missing")
    binding_values = {
        "work_id": work["work_id"],
        "textual_form_id": form["textual_form_id"],
        "edition_id": edition["edition_id"],
        "acquisition_id": acquisition["acquisition_id"],
        "source_sha256": acquisition["source_sha256"],
        "source_bytes": str(len(raw)),
            "source_selection_sha256": verified_selection_sha256,
        "source_carrier_count": str(len(carriers)),
    }
    for key, value in binding_values.items():
        binding.append(tei_el("idno", {"type": key}, text=value.removeprefix("sha256:")))
    binding.append(tei_el("note", {"type": "source-location"}, text=SOURCE_PATH))
    binding.append(tei_el("note", {"type": "source-scope"}, text=acquisition["source_scope"]))
    binding.append(tei_el("note", {"type": "source-gap"}, text="The source table of contents names Chapters VI and VII, but retained carriers ix and x are absent; no replacement text is supplied."))

    css_rules: list[tuple[str, str]] = []
    for style in source_root.xpath("/ThML/ThML.head/style[@type='text/css']"):
        css = style.text or ""
        for selector, declaration in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            css_rules.append((selector.strip(), declaration.strip()))
    if css_rules:
        encoding = tei_el("encodingDesc")
        project = tei_el("projectDesc")
        project.append(tei_el("p", text="This nonaccepted candidate preserves all present ThML body carriers and records the absent VI/VII source gap."))
        encoding.append(project)
        tags_decl = tei_el("tagsDecl")
        encoding.append(tags_decl)
        for index, (selector, declaration) in enumerate(css_rules, 1):
            tags_decl.append(tei_el("rendition", {"xml:id": f"source-style-{index}", "scheme": "css", "selector": selector}, text=declaration))
        header.append(encoding)

    text = tei_el("text", {"xml:lang": form.get("language") or "en"})
    root.append(text)
    front = tei_el("front")
    body = tei_el("body")
    back = tei_el("back")
    text.extend((front, body, back))
    internal_targets = {node.get("id"): f"#src-{tei_ids[tree.getpath(node)]}" for node in source_root.iter() if node.get("id") and tree.getpath(node) in tei_ids}
    rows_by_selector = {row["source_selector"]: row for row in features}

    def convert(source: etree._Element, parent: etree._Element) -> etree._Element:
        if source.tag not in TAGS:
            raise ValueError(f"unsupported present ThML source tag: {source.tag}")
        selector = tree.getpath(source)
        tei_id = tei_ids.get(selector)
        if tei_id is None:
            raise ValueError(f"source feature has no TEI identity: {selector}")
        target = tei_el(_tei_tag(source), _tei_attributes(source, source.tag, tei_id, internal_targets))
        target.text = source.text
        parent.append(target)
        for child in source:
            convert(child, target)
        target.tail = source.tail
        rows_by_selector[selector]["tei_id"] = tei_id
        rows_by_selector[selector]["tei_tag"] = _tei_tag(source)
        return target

    for carrier in carriers:
        source = source_by_id[carrier["native_id"]]
        region = carrier["tei_region"]
        target = front if region == "front" else (back if region == "back" else body)
        convert(source, target)
    # Empty wrappers are not useful to the reader and are not source features.
    if len(back) == 0:
        text.remove(back)
    if len(front) == 0:
        text.remove(front)

    gap = {
        "contract": "ocd-source-completeness-gap-v1",
        "expected_chapters": ["VI", "VII"],
        "absent_native_ids": ["ix", "x"],
        "evidence_selector": "/ThML/ThML.body/div1[3]",
        "disposition": "unresolved; no replacement text inferred",
    }
    accountability = {
        "contract": "ocd-watson-source-accountability-v1",
        "work_id": work["work_id"],
        "source_member": {"path": SOURCE_PATH, "bytes": len(raw), "sha256": _sha(raw)},
        "source_selection_sha256": verified_selection_sha256,
        "source_envelope": carriers,
        "document_shell": _document_shell(raw, tree),
        "feature_census": feature_census,
        "features": features,
        "source_completeness_gap": gap,
    }
    unresolved = [
        {
            "contract": "ocd-watson-unresolved-v1",
            "id": "watson-missing-chapters-vi-vii",
            "scope": "source-completeness",
            "disposition": "unresolved",
            "evidence": "TOC carrier iii names VI/VII while body carriers ix/x are absent",
        },
        {
            "contract": "ocd-watson-unresolved-v1",
            "id": "watson-source-quality",
            "scope": "source-quality",
            "disposition": "unassessed",
            "evidence": "No proofreading or textual correction is claimed by this mechanical candidate",
        },
        {
            "contract": "ocd-watson-unresolved-v1",
            "id": "watson-rights-clearance",
            "scope": "rights",
            "disposition": "separate-human-gate",
            "evidence": "Provider rights and title-page permission statements are not project clearance",
        },
    ]
    readme_lines = [
        f"# {work['title']}",
        "",
        "Nonaccepted, disposable technical candidate for 37c-316.",
        "",
        f"Retained source: `{SOURCE_PATH}` ({len(raw)} bytes; SHA-256 `{_sha(raw)}`).",
        "",
        "This route maps every present ThML.body carrier in source order: " + ", ".join(expected_ids) + ".",
        "",
        "The source table of contents names Chapters VI and VII, but no body carriers with native IDs `ix` or `x` are present. The candidate records that gap and does not infer content from another witness.",
        "",
        "## Retained source metadata",
        "",
        *_metadata_lines(source_root),
        "",
        "Technical checks, human acceptance, rights clearance, accepted IR, promotion, publication, and deployment remain separate gates.",
    ]
    provenance = {
        "contract": "ocd-candidate-provenance-v1",
        "status": "nonaccepted",
        "work_id": work["work_id"],
        "acquisition_id": acquisition["acquisition_id"],
        "source_path": SOURCE_PATH,
        "source_sha256": _sha(raw),
        "source_selection_sha256": verified_selection_sha256,
        "present_carrier_ids": expected_ids,
        "missing_expected_native_ids": ["ix", "x"],
    }
    return {
        "content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": ("\n".join(readme_lines) + "\n").encode("utf-8"),
    }


_convert.converter_id = "ocd-watson-complete-present-thml-to-tei"
_convert.converter_version = "1"
