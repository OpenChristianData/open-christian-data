"""Independent source walk and TEI/accounting oracle for Watson Beatitudes."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import (
    _canonical,
    _validation_authority_bindings,
)
from ocd_kernel.reconstruction.verifier import (
    MechanicalFacts,
    verify_mechanical_facts,
)
from ocd_kernel.tei.validate import compiled_schema


WORK_ID = "watson-beatitudes"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MEMBERS = frozenset(
    {
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
)
SOURCE_TO_TEI = {
    "a": "ref",
    "cite": "title",
    "div": "div",
    "div1": "div",
    "div2": "div",
    "div3": "div",
    "em": "hi",
    "h1": "head",
    "h2": "head",
    "h3": "head",
    "i": "hi",
    "insertIndex": "milestone",
    "li": "item",
    "name": "name",
    "note": "note",
    "ol": "list",
    "p": "p",
    "pb": "pb",
    "scripCom": "milestone",
    "scripContext": "milestone",
    "scripRef": "ref",
    "span": "seg",
    "ul": "list",
}
IMPORT_CLOSURE = (
    "sources/structured-text/watson-beatitudes/watson_beatitudes_reconstruction.py",
    "build/tei/selected_thml.py",
    "ocd_kernel/library/acquisitions.py",
    "ocd_kernel/library/identities.py",
    "ocd_kernel/library/_common.py",
    "ocd_kernel/library/source_selection.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/tei/writer.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
    "ocd_kernel/tei/validate.py",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
    "schemas/v2/work.schema.json",
    "schemas/v2/acquisition.schema.json",
    "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    "library/works/watson-beatitudes/work.json",
    "library/works/watson-beatitudes/forms/watson-beatitudes-route-source-form/editions/watson-beatitudes-retained-thml-route/acquisitions/watson-beatitudes-retained-source.json",
    "sources/structured-text/watson-beatitudes/watson-beatitudes.reconstruction-profile.json",
    "sources/structured-text/watson-beatitudes/watson-beatitudes.validation-policy.json",
    "sources/structured-text/watson-beatitudes/watson-beatitudes.source-accountability.json",
    "sources/structured-text/watson-beatitudes/watson-beatitudes.source-accountability.schema.json",
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read_json(content: bytes, label: str) -> dict:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _node_kind(node) -> str:
    if isinstance(node, etree._Comment):
        return "comment"
    if isinstance(node, etree._ProcessingInstruction):
        return "processing-instruction"
    raise ValueError(f"unsupported document-shell node: {type(node).__name__}")


def _shell_node(node, tree, disposition: str) -> dict:
    record = {
        "kind": _node_kind(node),
        "path": tree.getroottree().getpath(node) if node.getparent() is not None else None,
        "text": node.text or "",
        "tail": node.tail or "",
        "disposition": disposition,
    }
    if isinstance(node, etree._ProcessingInstruction):
        record["target"] = node.target
    return record


def _region(source, unit: Mapping[str, object]) -> str:
    if source.tag == "div1" and source.get("title") == "Title Page":
        if unit["role"] != "body":
            raise ValueError("source title page must retain the body selection role")
        return "front"
    return str(unit["role"])


def _ordered_shell_nodes(root, *, previous: bool):
    nodes = []
    node = root.getprevious() if previous else root.getnext()
    while node is not None:
        nodes.append(node)
        node = node.getprevious() if previous else node.getnext()
    if previous:
        nodes.reverse()
    return nodes


def _document_shell(raw: bytes, tree, selected_roots: set) -> dict:
    root = tree.getroottree().getroot()
    before = _ordered_shell_nodes(root, previous=True)
    after = _ordered_shell_nodes(root, previous=False)

    def is_selected_comment(node) -> bool:
        parent = node.getparent()
        while parent is not None:
            if parent in selected_roots:
                return True
            parent = parent.getparent()
        return False

    declaration = None
    if raw.startswith(b"<?xml") and b"?>" in raw:
        declaration = raw.split(b"?>", 1)[0].decode("ascii") + "?>"
    comments = []
    for node in tree.iter():
        if isinstance(node, (etree._Comment, etree._ProcessingInstruction)):
            comments.append(
                _shell_node(
                    node,
                    tree,
                    "preserved-in-tei" if is_selected_comment(node) else "accounted-outside-selected-content",
                )
            )

    head = tree.find("ThML.head")
    head_children = []
    if head is not None:
        for position, child in enumerate(head):
            if not isinstance(child.tag, str):
                raise ValueError("unsupported non-element node in ThML head")
            if child.tag == "style" and child.get("type") == "text/css":
                disposition = "represented-in-tei-encodingDesc"
            elif child.tag == "style" and not "".join(child.itertext()).strip():
                disposition = "accounted-empty-source-stylesheet"
            else:
                disposition = "reproduced-in-source-readme"
            head_children.append(
                {
                    "position": position,
                    "tag": child.tag,
                    "attributes": dict(child.attrib),
                    "text": "".join(child.itertext()).strip(),
                    "disposition": disposition,
                }
            )
    docinfo = tree.getroottree().docinfo
    return {
        "xml_declaration": declaration,
        "doctype": docinfo.doctype or None,
        "root_name": etree.QName(root).localname,
        "prolog": [
            _shell_node(node, tree, "accounted-source-document-shell")
            for node in before
        ],
        "epilog": [
            _shell_node(node, tree, "accounted-source-document-shell")
            for node in after
        ],
        "comments_and_processing_instructions": comments,
        "head_children": head_children,
    }


def _manual_source_binding(manifest, acquisition: dict, work: dict):
    source_member = manifest.authority_path("retained-source")
    raw = source_member.read_bytes()
    member = acquisition["retained_files"][0]
    selection = acquisition.get("source_selection")
    if not isinstance(selection, dict):
        raise ValueError("Watson Beatitudes acquisition lacks its selector")
    if (
        manifest.record.get("work_id") != WORK_ID
        or work.get("work_id") != WORK_ID
        or member.get("path") != "raw/ccel/watson/beatitudes.xml"
        or selection.get("work_id") != WORK_ID
        or selection.get("member_path") != member.get("path")
        or acquisition.get("source_path") != member.get("path")
        or acquisition.get("source_bytes") != len(raw)
        or acquisition.get("source_sha256") != _sha(raw)
        or member.get("bytes") != len(raw)
        or member.get("sha256") != _sha(raw)
    ):
        raise ValueError("Watson Beatitudes source binding differs from retained bytes")
    tree = etree.fromstring(
        raw,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            recover=False,
            remove_comments=False,
            remove_pis=False,
        ),
    )
    if tree.tag != "ThML" or any(isinstance(node, etree._Entity) for node in tree.iter()):
        raise ValueError("Watson Beatitudes source is not entity-free ThML")
    body = tree.find("ThML.body")
    if body is None:
        raise ValueError("Watson Beatitudes source body is missing")
    direct_carriers = [node for node in body if isinstance(node.tag, str)]
    units = selection.get("units")
    if not isinstance(units, list) or len(units) != len(direct_carriers):
        raise ValueError("Watson Beatitudes selector does not cover every direct body carrier")
    ids = [node.get("id") for node in direct_carriers]
    unit_ids = [unit.get("native_id") for unit in units]
    if ids != unit_ids or len(ids) != len(set(ids)):
        raise ValueError("Watson Beatitudes selector order or native IDs differ")
    if any(node.tag != "div1" for node in direct_carriers):
        raise ValueError("Watson Beatitudes direct body envelope contains a non-div1 element")
    for node, unit in zip(direct_carriers, units):
        if node.get("title") != unit.get("title"):
            raise ValueError(f"Watson Beatitudes source title differs for {unit.get('native_id')}")
    if not units or units[0].get("role") != "body" or units[-1].get("role") != "back":
        raise ValueError("Watson Beatitudes route roles must bind title matter and final index")
    if any(unit.get("role") not in {"body", "back"} for unit in units):
        raise ValueError("Watson Beatitudes selector uses an unsupported role")
    if any(unit.get("role") == "body" for unit in units[units.index(next((u for u in units if u.get("role") == "back"), {})) + 1 :]):
        raise ValueError("Watson Beatitudes body unit follows a back unit")
    if selection.get("dependencies") != []:
        raise ValueError("Watson Beatitudes route does not declare source-credit dependencies")

    member_path = member["path"]
    expected_evidence = {member_path, *(f"{member_path}#{native_id}" for native_id in ids)}
    if set(work.get("evidence", [])) != expected_evidence:
        raise ValueError("Watson Beatitudes work evidence differs from the selector envelope")
    title_values = tree.xpath("/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()")
    if title_values != [work.get("title")]:
        raise ValueError("Watson Beatitudes work title differs from retained source metadata")
    author_values = tree.xpath(
        "/ThML/ThML.head/electronicEdInfo/DC/DC.Creator[@sub='Author']/text()"
    )
    title_page_text = " ".join("".join(direct_carriers[0].itertext()).split())
    authors = [creator for creator in work.get("creators", []) if creator.get("role") == "author"]
    if not authors or any(author.get("name") not in author_values and author.get("name") not in title_page_text for author in authors):
        raise ValueError("Watson Beatitudes creator lacks retained source evidence")
    return raw, tree, selection, direct_carriers


def _expected_source_features(tree, selection, direct_carriers):
    units = selection["units"]
    by_id = {node.get("id"): node for node in direct_carriers}
    selected_roots = [by_id[unit["native_id"]] for unit in units]
    selected_nodes = [
        node
        for source_root in selected_roots
        for node in source_root.iter()
        if isinstance(node.tag, str)
    ]
    features = [
        {
            "source_path": tree.getroottree().getpath(node),
            "native_id": node.get("id"),
            "source_tag": node.tag,
            "attributes": dict(node.attrib),
            "tei_id": f"src-{position}",
        }
        for position, node in enumerate(selected_nodes, 1)
    ]
    return selected_roots, selected_nodes, features


def _expected_envelope(tree, selection, direct_carriers, selected_roots):
    body = tree.find("ThML.body")
    unit_by_id = {unit["native_id"]: unit for unit in selection["units"]}
    selected_ids = set(unit_by_id)
    envelope = []
    sequence = []
    for position, node in enumerate(body):
        if isinstance(node.tag, str):
            native_id = node.get("id")
            unit = unit_by_id.get(native_id)
            row = {
                "position": position,
                "native_id": native_id,
                "source_tag": node.tag,
                "source_title": node.get("title"),
                "disposition": "selected-work" if native_id in selected_ids else "outside-selected-work",
            }
            if unit is not None:
                row["selection_role"] = unit["role"]
                row["tei_region"] = _region(node, unit)
            envelope.append(row)
            sequence.append({**row, "node_kind": "carrier"})
        elif isinstance(node, (etree._Comment, etree._ProcessingInstruction)):
            shell_row = _shell_node(node, tree, "accounted-source-body-wrapper")
            shell_row["position"] = position
            sequence.append(shell_row)
        else:
            raise ValueError("unsupported non-element node in Watson Beatitudes body")
    return envelope, sequence


def _source_shell_observation(raw: bytes, tree, selected_roots: set) -> dict:
    all_nodes = list(tree.iter())
    prolog = _ordered_shell_nodes(tree, previous=True)
    epilog = _ordered_shell_nodes(tree, previous=False)
    comments = sum(isinstance(node, etree._Comment) for node in all_nodes + prolog + epilog)
    processing_instructions = sum(
        isinstance(node, etree._ProcessingInstruction) for node in all_nodes + prolog + epilog
    )
    selected_comments = 0
    for node in all_nodes:
        if not isinstance(node, etree._Comment):
            continue
        parent = node.getparent()
        while parent is not None and parent not in selected_roots:
            parent = parent.getparent()
        if parent in selected_roots:
            selected_comments += 1
    body = tree.find("ThML.body")
    wrapper_comments = sum(isinstance(node, etree._Comment) for node in body)
    return {
        "root_name": etree.QName(tree).localname,
        "doctype": tree.getroottree().docinfo.doctype or None,
        "element_count": sum(isinstance(node.tag, str) for node in all_nodes),
        "attribute_count": sum(len(node.attrib) for node in all_nodes if isinstance(node.tag, str)),
        "comment_count": comments,
        "processing_instruction_count": processing_instructions,
        "selected_comment_count": selected_comments,
        "body_wrapper_comment_count": wrapper_comments,
    }


_CSS_SELECTOR = re.compile(r"(?:[A-Za-z][A-Za-z0-9]*)?\.[A-Za-z][A-Za-z0-9_-]*$")


def _css_rules(tree) -> list[tuple[str, str]]:
    rules = []
    for style in tree.xpath("/ThML/ThML.head/style[@type='text/css']"):
        css = style.text or ""
        parsed = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        if re.sub(r"[^{}]+\{[^{}]*\}", "", css).strip():
            raise ValueError("unsupported retained stylesheet structure")
        for selector, declarations in parsed:
            selector = selector.strip()
            if not _CSS_SELECTOR.fullmatch(selector):
                raise ValueError(f"unsupported retained CSS selector: {selector}")
            rules.append((selector, declarations))
    return rules


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def _synthetic_division_head(source):
    title = source.get("title", "")
    has_matching_heading = any(
        child.tag in ("h1", "h2", "h3")
        and _normalized("".join(child.itertext())) == _normalized(title)
        for child in source
        if isinstance(child.tag, str)
    )
    return source.tag.startswith("div") and bool(source.get("title")) and not has_matching_heading


def _expected_attributes(source, feature, acquisition, native_targets, css_rules, responsibilities):
    attrs = {f"{{{XML_NS}}}id": feature["tei_id"]}
    for source_key, tei_key in (("n", "n"), ("class", "rend"), ("style", "style"), ("lang", f"{{{XML_NS}}}lang")):
        if source.get(source_key):
            attrs[tei_key] = source.get(source_key)
    if source.tag in {"i", "em"}:
        attrs["rend"] = "italic"
    renditions = [
        f"#source-style-{index}"
        for index, (selector, _declarations) in enumerate(css_rules, 1)
        if selector.split(".")[-1] in source.get("class", "").split()
        and (selector.startswith(".") or selector.split(".")[0] == source.tag)
    ]
    if renditions:
        attrs["rendition"] = " ".join(renditions)
    if source.tag == "note" and source.get("place"):
        attrs["place"] = source.get("place")
    if source.tag == "note" and source.get("resp"):
        attrs["resp"] = f"#source-responsibility-{responsibilities.index(source.get('resp')) + 1}"
    if source.tag == "note" and source.get("anchored"):
        if source.get("anchored") not in {"yes", "no"}:
            raise ValueError("unsupported source anchored value")
        attrs["anchored"] = "true" if source.get("anchored") == "yes" else "false"
    if source.tag == "pb" and source.get("href"):
        attrs["facs"] = source.get("href")
    if source.tag == "scripRef" and source.get("passage"):
        attrs["cRef"] = source.get("passage")
    if source.tag == "scripRef" and source.get("osisRef"):
        attrs["target"] = source.get("osisRef")
    if source.tag in {"name", "cite"} and source.get("title"):
        attrs["key"] = source.get("title")
    if source.tag == "a" and source.get("href"):
        href = source.get("href")
        attrs["target"] = (
            native_targets.get(href[1:], acquisition["url"] + href)
            if href.startswith("#")
            else href
        )
    if source.tag in {"scripContext", "insertIndex"}:
        attrs["unit"] = source.tag
        attrs["n"] = source.get("version") or source.get("type") or source.tag
    if source.tag == "h3":
        attrs["type"] = "thml-h3"
    if source.tag == "ol":
        attrs["type"] = "ordered"
    if source.tag == "scripCom":
        attrs["unit"] = "scripCom"
        attrs["type"] = source.get("type")
        attrs["n"] = source.get("passage")
        attrs["corresp"] = source.get("osisRef")
    return attrs


def _verify_source_node(source, target, feature, *, acquisition, features_by_path, native_targets, css_rules, responsibilities):
    expected_tag = SOURCE_TO_TEI.get(source.tag)
    if expected_tag is None or target.tag != f"{{{TEI_NS}}}{expected_tag}":
        raise ValueError(f"source element mapping differs at {feature['source_path']}")
    if target.attrib != _expected_attributes(
        source, feature, acquisition, native_targets, css_rules, responsibilities
    ):
        raise ValueError(f"TEI attributes differ from source mapping at {feature['source_path']}")
    if target.text != source.text or target.tail != source.tail:
        raise ValueError(f"source text or tail differs at {feature['source_path']}")

    expected_children = list(source)
    insert_head = _synthetic_division_head(source)
    actual_children = list(target)
    if len(actual_children) != len(expected_children) + int(insert_head):
        raise ValueError(f"source child count differs at {feature['source_path']}")
    offset = 0
    if insert_head:
        head = actual_children[0]
        if (
            head.tag != f"{{{TEI_NS}}}head"
            or head.attrib
            or head.text != source.get("title")
            or head.tail is not None
        ):
            raise ValueError(f"source division title is not preserved at {feature['source_path']}")
        offset = 1

    for source_child, target_child in zip(expected_children, actual_children[offset:]):
        if isinstance(source_child.tag, str):
            child_path = source.getroottree().getpath(source_child)
            child_feature = features_by_path.get(child_path)
            if child_feature is None:
                raise ValueError(f"selected source child lacks an accounting row: {child_path}")
            if not target_child.tag.startswith(f"{{{TEI_NS}}}"):
                raise ValueError(f"selected source element became a non-element: {child_path}")
            _verify_source_node(
                source_child,
                target_child,
                child_feature,
                acquisition=acquisition,
                features_by_path=features_by_path,
                native_targets=native_targets,
                css_rules=css_rules,
                responsibilities=responsibilities,
            )
        elif isinstance(source_child, etree._Comment):
            if (
                not isinstance(target_child, etree._Comment)
                or target_child.text != source_child.text
                or target_child.tail != source_child.tail
            ):
                raise ValueError("selected source comment or its position differs")
        else:
            raise ValueError("unsupported non-element node inside selected source content")


def _expected_readme(tree, work, acquisition) -> bytes:
    context = tree.find("ThML.head")
    context_text = "\n\n".join(
        f"### ThML.head/{node.tag}\n\n{''.join(node.itertext()).strip()}"
        for node in context
        if node.tag != "style" and "".join(node.itertext()).strip()
    )
    return (
        f"# {work['title']}\n\nNonaccepted per-work reconstruction.\n\n"
        f"Retained electronic source locator: {acquisition['url']}\n\n"
        f"{context_text}\n\n"
        "Shared source credits (verbatim; roles are source-level unless explicitly allocated):\n\n"
        + "\n\n".join(
            dependency["text"] for dependency in acquisition["source_selection"]["dependencies"]
        )
        + "\n"
    ).encode("utf-8")


def _check_static_accountability(manifest, raw, tree, selection, direct_carriers, selected_roots, features):
    authority = _read_json(
        manifest.authority_path("source-accountability").read_bytes(),
        "Watson Beatitudes source-accountability authority",
    )
    schema = _read_json(
        manifest.authority_path("source-accountability-schema").read_bytes(),
        "Watson Beatitudes source-accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(authority), key=str)
    if errors:
        raise ValueError(f"Watson Beatitudes source-accountability schema failure: {errors[0].message}")
    counts = dict(sorted(Counter(row["source_tag"] for row in features).items()))
    carrier_rows = [
        {
            "native_id": unit["native_id"],
            "title": unit["title"],
            "selection_role": unit["role"],
            "tei_region": _region(node, unit),
        }
        for unit, node in zip(selection["units"], direct_carriers)
    ]
    custom_counts = {tag: counts.get(tag, 0) for tag in ("ol", "scripCom")}
    observed = {
        "contract": "watson-beatitudes-source-accountability-v1",
        "source_member": {
            "path": selection["member_path"],
            "bytes": len(raw),
            "sha256": _sha(raw),
        },
        "selection_id": selection["selection_id"],
        "body_carriers": carrier_rows,
        "selected_feature_count": len(features),
        "selected_feature_counts": counts,
        "custom_element_counts": custom_counts,
        "document_shell_observation": _source_shell_observation(
            raw, tree, set(selected_roots)
        ),
    }
    if authority != observed:
        raise ValueError("Watson Beatitudes static source-accountability authority differs from retained source")
    return counts


def _audit_members(source_manifest, members: Mapping[str, bytes]) -> dict:
    """Audit an in-memory producer result without sealing or writing a candidate."""

    source_manifest.verify()
    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("Watson Beatitudes oracle received another work")
    if set(members) != MEMBERS or any(not isinstance(value, bytes) for value in members.values()):
        raise ValueError("Watson Beatitudes route members do not match the five-member contract")

    acquisition = validate_acquisition(
        source_manifest.authority_path("acquisition"),
        root=source_manifest.repository_root,
    )
    work = load_work(source_manifest.authority_path("work"))
    raw, source_tree, selection, direct_carriers = _manual_source_binding(
        source_manifest, acquisition, work
    )
    selected_roots, selected_nodes, expected_features = _expected_source_features(
        source_tree, selection, direct_carriers
    )
    expected_envelope, expected_body_sequence = _expected_envelope(
        source_tree, selection, direct_carriers, selected_roots
    )
    expected_document_shell = _document_shell(raw, source_tree, set(selected_roots))
    expected_accountability = {
        "selection_sha256": hashlib.sha256(_canonical(selection)).hexdigest(),
        "units": selection["units"],
        "features": expected_features,
        "source_envelope": expected_envelope,
        "body_node_sequence": expected_body_sequence,
        "document_shell": expected_document_shell,
    }
    accountability = _read_json(members["source-accountability.json"], "candidate accountability")
    if accountability != expected_accountability:
        raise ValueError("candidate source-accountability differs from the independent source walk")

    counts = _check_static_accountability(
        source_manifest,
        raw,
        source_tree,
        selection,
        direct_carriers,
        selected_roots,
        expected_features,
    )
    if len(expected_features) != 4953:
        raise ValueError("Watson Beatitudes selected feature count differs from profile")

    tei_root = etree.fromstring(
        members["content.tei.xml"],
        etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
    )
    schema = compiled_schema()
    if not schema.validate(tei_root):
        raise ValueError(f"Watson Beatitudes TEI P5 schema failed: {schema.error_log}")
    if (
        tei_root.tag != f"{{{TEI_NS}}}TEI"
        or tei_root.get(f"{{{XML_NS}}}id") != WORK_ID
    ):
        raise ValueError("Watson Beatitudes TEI root identity differs")

    profile = _read_json(
        source_manifest.authority_path("profile").read_bytes(),
        "Watson Beatitudes reconstruction profile",
    )
    if profile.get("source_element_map") != SOURCE_TO_TEI:
        raise ValueError("Watson Beatitudes source-to-TEI map differs from the independent oracle")
    if profile.get("scope", {}).get("expected_carrier_count") != len(direct_carriers):
        raise ValueError("Watson Beatitudes carrier count differs from the bound profile")
    rules = profile.get("custom_element_rules", {})
    if set(rules) != {"ol", "scripCom"}:
        raise ValueError("Watson Beatitudes custom element policy is incomplete")
    if counts.get("scripCom") != rules["scripCom"].get("expected_occurrences"):
        raise ValueError("Watson Beatitudes scripCom route count differs")
    if counts.get("ol") != rules["ol"].get("expected_occurrences"):
        raise ValueError("Watson Beatitudes ol route count differs")

    by_path = {row["source_path"]: row for row in expected_features}
    native_targets = {
        node.get("id"): f"#src-{index}"
        for index, node in enumerate(selected_nodes, 1)
        if node.get("id")
    }
    css_rules = _css_rules(source_tree)
    responsibilities = sorted(
        {
            node.get("resp")
            for node in selected_nodes
            if node.tag == "note" and node.get("resp")
        }
    )

    tei_ns = {"t": TEI_NS}
    title_values = tei_root.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title/text()", namespaces=tei_ns)
    if title_values != [work["title"]]:
        raise ValueError("Watson Beatitudes TEI title differs from source-bound work title")
    text_nodes = tei_root.xpath("/t:TEI/t:text", namespaces=tei_ns)
    if len(text_nodes) != 1 or text_nodes[0].get(f"{{{XML_NS}}}lang") != "en":
        raise ValueError("Watson Beatitudes TEI text or route language binding differs")
    expected_groups: dict[str, list[tuple[object, Mapping[str, object]]]] = {}
    for unit, source in zip(selection["units"], direct_carriers):
        expected_groups.setdefault(_region(source, unit), []).append((source, unit))
    region_order = [region for region in ("front", "body", "back") if region in expected_groups]
    region_nodes = list(text_nodes[0])
    if [etree.QName(node).localname for node in region_nodes] != region_order:
        raise ValueError("Watson Beatitudes TEI front/body/back regions differ from selector")
    for region, region_node in zip(region_order, region_nodes):
        source_units = expected_groups[region]
        tei_carriers = list(region_node)
        if len(tei_carriers) != len(source_units):
            raise ValueError(f"Watson Beatitudes {region} carrier count differs")
        for (source, _unit), target in zip(source_units, tei_carriers):
            feature = by_path[source_tree.getroottree().getpath(source)]
            _verify_source_node(
                source,
                target,
                feature,
                acquisition=acquisition,
                features_by_path=by_path,
                native_targets=native_targets,
                css_rules=css_rules,
                responsibilities=responsibilities,
            )

    # Header binding checks are intentionally source-scoped; no print date,
    # rights clearance, or edition/witness assertion is accepted here.
    bibliography = tei_root.xpath("/t:TEI/t:teiHeader//t:bibl", namespaces=tei_ns)
    if len(bibliography) != 1:
        raise ValueError("Watson Beatitudes TEI source bibliography is missing or ambiguous")
    idnos = {
        node.get("type"): "".join(node.itertext())
        for node in bibliography[0].xpath("./t:idno", namespaces=tei_ns)
    }
    form = work["textual_forms"][0]
    edition = form["editions"][0]
    expected_idnos = {
        "work_id": WORK_ID,
        "textual_form_id": form["textual_form_id"],
        "edition_id": edition["edition_id"],
        "acquisition_id": acquisition["acquisition_id"],
        "sha256": _sha(raw),
        "source_sha256": _sha(raw),
        "source_bytes": str(len(raw)),
        "source_selection_sha256": expected_accountability["selection_sha256"],
    }
    if idnos != expected_idnos:
        raise ValueError("Watson Beatitudes TEI source-binding idnos differ")
    if (
        bibliography[0].xpath("string(./t:note[@type='source-location'])", namespaces=tei_ns)
        != selection["member_path"]
        or bibliography[0].xpath("string(./t:note[@type='source-scope'])", namespaces=tei_ns)
        != acquisition["source_scope"]
        or tei_root.xpath("/t:TEI/t:teiHeader//t:note[@type='print-source']", namespaces=tei_ns)
    ):
        raise ValueError("Watson Beatitudes TEI source scope or unresolved print boundary differs")

    provenance = _read_json(members["provenance.json"], "candidate provenance")
    if provenance != {
        "work_id": WORK_ID,
        "acquisition_id": acquisition["acquisition_id"],
        "source_selection_sha256": expected_accountability["selection_sha256"],
    }:
        raise ValueError("Watson Beatitudes provenance binding differs")
    expected_questions = profile.get("candidate_questions", [])
    unresolved = b"".join(_json(question) for question in expected_questions)
    if members["unresolved.jsonl"] != unresolved:
        raise ValueError("Watson Beatitudes unresolved question set differs from profile")
    if members["README.source.md"] != _expected_readme(source_tree, work, acquisition):
        raise ValueError("Watson Beatitudes human-readable source metadata deliverable differs")
    return {
        "source_sha256": _sha(raw),
        "selected_feature_count": len(expected_features),
        "selected_feature_counts": counts,
        "source_carrier_count": len(direct_carriers),
        "unresolved_question_count": len(expected_questions),
    }


def _closure_digest(root: Path) -> str:
    rows = [
        {"path": path, "sha256": _sha((root / path).read_bytes())}
        for path in IMPORT_CLOSURE
    ]
    return _sha(_canonical(rows))


def _oracle(source_manifest, candidate):
    """Bind the independent in-memory source audit to a sealed candidate."""

    source_manifest.verify()
    candidate.verify_integrity()
    members = {name: candidate.member_bytes(name) for name in MEMBERS}
    audit = _audit_members(source_manifest, members)
    bindings = _validation_authority_bindings(source_manifest)
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_closure_digest(source_manifest.repository_root),
        source_sha256=audit["source_sha256"],
        profile_sha256=bindings["profile_sha256"],
        package_schema_sha256=bindings["package_schema_sha256"],
        xsd_sha256=bindings["xsd_sha256"],
        policy_sha256=bindings["policy_sha256"],
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-watson-beatitudes-independent-source-walk"
_oracle.oracle_version = "1"
