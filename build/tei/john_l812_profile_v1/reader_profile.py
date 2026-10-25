"""Source-specific L812 apparatus mapping and independently derived observer.

This file is not imported by the application. It models proposed producer and
observer behavior against one frozen retained source and bound master.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.lib.path_io import io_path

PROFILE_DIR = Path(__file__).resolve().parent
HEADER_MODULE = PROFILE_DIR / "header_profile.py"
PROFILE_ID = "ocd-prose-pta-l812-john-ephesus-part-iii-apparatus-v1"
IDENTITY = {
    "work_id": "john-of-ephesus-ecclesiastical-history",
    "textual_form_id": "syriac",
    "edition_id": "pta-ef861ab3-john-ecclesiastical-history-part-iii",
}
LANGUAGE = "syc"
CATEGORY = "prose"
SOURCE_PATH = (
    "raw/pta/ef861ab391ea35c5d85b41dd8d7ba2bf65530b21/"
    "pta-l812-john-of-ephesus-ecclesiastical-history-syriac-part-iii-ef861ab3/"
    "pta0200.pta001.pta-syc1.xml"
)
MASTER_PATH = ("library/works/john-of-ephesus-ecclesiastical-history/forms/syriac/editions/"
               "pta-ef861ab3-john-ecclesiastical-history-part-iii/master.tei.xml")
SOURCE_SHA256 = "35e8d68a884aaa10d1e9f4ae0aee4eb447a4cca7ff0c1393bee6674a6b7e437e"
SOURCE_BYTES = 1_292_998
MASTER_SHA256 = "c0aab5dd6685ee6b29db074426e5395871171664a5b3029714d250f599e3a153"
EDITION_N = "urn:cts:pta:pta0200.pta001.pta-syc1"
NS = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
Q = "{" + NS + "}"
X = "{" + XML + "}"
RELATION_ATTRIBUTES = ("wit", "resp", "source", "hand")
APPARATUS_ATTRIBUTE_NAMES = {
    "add": {"hand", "place"}, "app": {"type"},
    "del": {"hand", "rend"}, "gap": {"quantity", "reason", "unit"},
    "hi": {"rend"}, "lacunaEnd": set(), "lacunaStart": set(),
    "lem": {"hand", "rend", "resp", "source", "type", "varSeq", "wit"},
    "note": {"hand", "place"}, "pb": {"edRef", "n"},
    "rdg": {"hand", "resp", "source", "type", "varSeq", "wit"},
    "subst": {"hand"}, "supplied": set(), "title": set(), "witStart": set(),
}
APPARATUS_CHILD_NAMES = {
    "add": set(), "app": {"lem", "note", "rdg"}, "del": set(), "gap": set(),
    "hi": set(), "lacunaEnd": set(), "lacunaStart": set(),
    "lem": {"pb", "subst", "supplied", "title"}, "note": set(), "pb": set(),
    "rdg": {"add", "del", "gap", "lacunaEnd", "lacunaStart", "note", "subst", "supplied", "witStart"},
    "subst": {"add", "del"}, "supplied": {"title"}, "title": {"hi"}, "witStart": set(),
}


class ProfileMismatch(ValueError):
    """A scoped profile, source, or projected apparatus binding failed."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_header_module():
    spec = importlib.util.spec_from_file_location("ocd_john_l812_header_profile", HEADER_MODULE)
    if spec is None or spec.loader is None:
        raise ProfileMismatch("header-profile module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def admitted(*, identity: dict, raw: bytes, language: str, category: str,
             collection: bool, projection_profile: str | None,
             allow_acceptance_metadata: bool) -> bool:
    """Fail closed for every identity or context except exact accepted L812."""
    same_work = identity.get("work_id") == IDENTITY["work_id"]
    if not same_work:
        return False
    if (identity != IDENTITY or _sha(raw) != MASTER_SHA256
            or language != LANGUAGE or category != CATEGORY or collection is not False
            or projection_profile != PROFILE_ID or allow_acceptance_metadata is not True):
        raise ProfileMismatch("L812 profile requires its exact accepted identity/master/context")
    return True


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _path_et(node: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    parts = []
    current = node
    while True:
        parent = parents.get(current)
        siblings = list(parent) if parent is not None else [current]
        same = [child for child in siblings if child.tag == current.tag]
        position = same.index(current) + 1
        parts.append(f"{_local(current.tag)}[{position}]")
        if parent is None:
            break
        current = parent
    return "/" + "/".join(reversed(parts))


def _path_lxml(node) -> str:
    parts = []
    current = node
    while current is not None and isinstance(current.tag, str):
        parent = current.getparent()
        same = ([child for child in parent if child.tag == current.tag]
                if parent is not None else [current])
        position = same.index(current) + 1
        parts.append(f"{_local(current.tag)}[{position}]")
        current = parent
    return "/" + "/".join(reversed(parts))


def _attrs_et(node: ET.Element) -> list[dict[str, str]]:
    return [{"name": key, "value": value} for key, value in sorted(node.attrib.items())]


def _attrs_lxml(node) -> list[dict[str, str]]:
    return [{"name": key, "value": value} for key, value in sorted(node.attrib.items())]


def _validate_l812_subtree_et(node: ET.Element, parent: str | None = None) -> None:
    """Check the closed source-derived tag, attribute and child-name sets."""
    tag = _local(node.tag)
    if tag not in APPARATUS_ATTRIBUTE_NAMES:
        raise ProfileMismatch(f"unsupported L812 apparatus element: {tag}")
    attrs = {_local(key) for key in node.attrib}
    if attrs - APPARATUS_ATTRIBUTE_NAMES[tag]:
        raise ProfileMismatch(f"unsupported source attribute on {tag}")
    if any(_local(child.tag) not in APPARATUS_CHILD_NAMES[tag] for child in node):
        raise ProfileMismatch(f"unsupported child in L812 apparatus {tag}")
    if tag == "app" and node.get("type") not in {"variants", "witnesses"}:
        raise ProfileMismatch("unsupported source apparatus type")
    for child in node:
        _validate_l812_subtree_et(child, tag)


def _mixed_content_et(node: ET.Element) -> dict:
    """Producer-side typed mixed-content tree; never flattens alternatives."""
    tag = _local(node.tag)
    record = {
        "tag": tag,
        "attributes": _attrs_et(node),
        "text": node.text or "",
        "children": [],
    }
    for child in node:
        record["children"].append({
            "node": _mixed_content_et(child),
            "tail": child.tail or "",
        })
    return record


def _relation_record(node: ET.Element, path: str, targets: dict[str, ET.Element]) -> list[dict]:
    result = []
    for attribute in RELATION_ATTRIBUTES:
        raw = node.get(attribute)
        if raw is None:
            continue
        tokens = []
        for token in raw.split():
            target_id = token[1:] if token.startswith("#") else None
            target = targets.get(target_id) if target_id is not None else None
            tokens.append({
                "token": token,
                "classification": "resolved-fragment" if target is not None else "unresolved-fragment" if target_id is not None else "literal-source-value",
                "target_id": target_id,
                "target_label": " ".join("".join(target.itertext()).split()) if target is not None else None,
            })
        result.append({"source_path": path, "attribute": attribute,
                       "raw_value": raw, "tokens": tokens})
    return result


def _relations_for_app(node: ET.Element, parents, targets) -> list[dict]:
    output = []
    for descendant in node.iter():
        output.extend(_relation_record(descendant, _path_et(descendant, parents), targets))
    return output


def _display_text(node: ET.Element) -> str:
    """Visible source text excluding nested notes, which get their own label."""
    pieces = [node.text or ""]
    for child in node:
        if _local(child.tag) != "note":
            pieces.append(_display_text(child))
        pieces.append(child.tail or "")
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


def _display_ref(relations: list[dict], name: str) -> str | None:
    values = [item["raw_value"] for item in relations if item["attribute"] == name]
    return values[0] if values else None


def _render_apparatus(node: ET.Element, relations: list[dict], parents) -> dict:
    """Return generated labeled context separately from source text/tree."""
    kind = node.get("type")
    displayed = []
    empty = []
    notes = []
    if kind == "witnesses":
        for child in node:
            if _local(child.tag) == "rdg":
                raw_wit = child.get("wit", "")
                child_path = _path_et(child, parents)
                matches = [r for r in relations if r["source_path"] == child_path and r["attribute"] == "wit"]
                target_labels = [t["target_label"] for r in matches for t in r["tokens"] if t["target_label"]]
                displayed.append({"role": "witness-attestation", "raw_wit": raw_wit,
                                  "target_labels": target_labels,
                                  "label": f"Witness attestation ({raw_wit})"})
        if not displayed:
            empty.append("witness-attestation")
    else:
        lemmas = [child for child in node if _local(child.tag) == "lem"]
        readings = [child for child in node if _local(child.tag) == "rdg"]
        if not lemmas:
            empty.append("lemma")
        if not readings:
            empty.append("reading")
        for role, children in (("lemma", lemmas), ("reading", readings)):
            for child in children:
                raw_relations = {key: child.get(key) for key in RELATION_ATTRIBUTES if child.get(key) is not None}
                child_path = _path_et(child, parents)
                relation_items = [r for r in relations if r["source_path"] == child_path]
                target_labels = [token["target_label"] for relation in relation_items
                                 for token in relation["tokens"] if token["target_label"]]
                displayed.append({"role": role, "source_text": _display_text(child),
                                  "raw_relations": raw_relations,
                                  "resolved_target_labels": target_labels})
    for descendant in node.iter():
        if descendant is not node and _local(descendant.tag) == "note":
            notes.append({
                "source_text": " ".join("".join(descendant.itertext()).split()),
                "attributes": {key: value for key, value in descendant.attrib.items()},
            })
    for descendant in node.iter():
        if descendant is node:
            continue
        if kind != "witnesses" and _local(descendant.tag) == "witStart":
            raw_wit = descendant.get("wit", "")
            displayed.append({"role": "source-witness-start-marker", "raw_wit": raw_wit,
                              "label": f"Source witness marker ({raw_wit})"})
    relation_labels = []
    for relation in relations:
        relation_labels.append({
            "source_path": relation["source_path"],
            "attribute": relation["attribute"],
            "raw_value": relation["raw_value"],
            "resolved_target_labels": [token["target_label"] for token in relation["tokens"] if token["target_label"]],
            "unresolved_tokens": [token["token"] for token in relation["tokens"] if token["classification"] == "unresolved-fragment"],
            "literal_tokens": [token["token"] for token in relation["tokens"] if token["classification"] == "literal-source-value"],
        })
    note_records = notes
    return {
        "generated_context_role": "source-apparatus-display",
        "generated_labels_are_not_source_text": True,
        "apparatus_type": kind,
        "lemma_and_reading_slots": displayed,
        "explicitly_absent_slots": empty,
        "generated_relation_labels": relation_labels,
        "notes": [{"generated_label": "Source note", **record} for record in note_records],
        "visible_summary": " ".join(
            [f"[{kind} apparatus]"]
            + [f"[{slot}]" if slot in {"lemma", "reading", "witness-attestation"} else slot for slot in empty]
            + [f"[{item['role']}: {item.get('source_text', item.get('raw_wit', ''))}; source_relations={item.get('raw_relations', {'wit': item.get('raw_wit')} if 'raw_wit' in item else {})}; resolved_targets={item.get('resolved_target_labels', item.get('target_labels', []))}]" for item in displayed]
            + [f"[{item['attribute']}={item['raw_value']}; resolved_targets={item['resolved_target_labels']}; unresolved={item['unresolved_tokens']}; literals={item['literal_tokens']}]" for item in relation_labels]
            + [f"[Source note: {note.get('source_text', '')}; source_attributes={note.get('attributes', {})}]" for note in note_records if note.get("source_text")]
        ),
    }


def produce_apparatus(master_raw: bytes, *, repository_root: Path, identity=IDENTITY, language=LANGUAGE,
                      category=CATEGORY, collection=False,
                      projection_profile=PROFILE_ID,
                      allow_acceptance_metadata=True) -> list[dict]:
    """Produce ordered TEI-shaped apparatus with an exact scoped route."""
    if not admitted(identity=identity, raw=master_raw, language=language,
                    category=category, collection=collection,
                    projection_profile=projection_profile,
                    allow_acceptance_metadata=allow_acceptance_metadata):
        return []
    header = _load_header_module()
    source_raw = io_path(Path(repository_root) / SOURCE_PATH).read_bytes()
    header.observe_source_derivation(
        source_raw, master_raw, repository_root=Path(repository_root), identity=identity,
        language=language, category=category, collection=collection,
        projection_profile=header.PROFILE_ID,
        allow_acceptance_metadata=allow_acceptance_metadata,
    )
    root = ET.fromstring(master_raw)
    parents = {child: parent for parent in root.iter() for child in parent}
    edition = root.find(f"{Q}text/{Q}body/{Q}div[@type='edition'][@n='{EDITION_N}']")
    if edition is None or edition.get(X + "lang") != "syc":
        raise ProfileMismatch("L812 Part III division or language differs")
    targets = {node.get(X + "id"): node for node in root.iter() if node.get(X + "id")}
    output = []
    for app in edition.iter(Q + "app"):
        _validate_l812_subtree_et(app)
        path = _path_et(app, parents)
        relations = _relations_for_app(app, parents, targets)
        output.append({
            "kind": "textual-apparatus",
            "source_path": path,
            "inherited_language": edition.get(X + "lang"),
            "attributes": _attrs_et(app),
            "source_relations": relations,
            "content": _mixed_content_et(app),
            "display": _render_apparatus(app, relations, parents),
            "tail": app.tail or "",
        })
    return output


def _tree_lxml(node) -> dict:
    """Independent observer tree extractor, implemented separately from ET."""
    return {
        "tag": _local(node.tag),
        "attributes": _attrs_lxml(node),
        "text": node.text or "",
        "children": [{"node": _tree_lxml(child), "tail": child.tail or ""} for child in node],
    }


def _relations_lxml(app, root) -> list[dict]:
    """Independently rederive exact relations from LXML source nodes."""
    ids = {node.get(X + "id"): node for node in root.iter() if node.get(X + "id")}
    output = []
    for node in app.iter():
        for attribute in RELATION_ATTRIBUTES:
            raw = node.get(attribute)
            if raw is None:
                continue
            tokens = []
            for token in raw.split():
                target_id = token[1:] if token.startswith("#") else None
                target = ids.get(target_id) if target_id is not None else None
                tokens.append({
                    "token": token,
                    "classification": "resolved-fragment" if target is not None else "unresolved-fragment" if target_id is not None else "literal-source-value",
                    "target_id": target_id,
                    "target_label": " ".join("".join(target.itertext()).split()) if target is not None else None,
                })
            output.append({"source_path": _path_lxml(node), "attribute": attribute,
                           "raw_value": raw, "tokens": tokens})
    return output


def _display_text_lxml(node) -> str:
    pieces = [node.text or ""]
    for child in node:
        if _local(child.tag) != "note":
            pieces.append(_display_text_lxml(child))
        pieces.append(child.tail or "")
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


def _display_lxml(app, relations: list[dict]) -> dict:
    """Independent read-side rendering expectation for generated labels."""
    kind = app.get("type")
    slots, absent, notes = [], [], []
    for child in app:
        tag = _local(child.tag)
        if kind == "witnesses" and tag == "rdg":
            raw = child.get("wit", "")
            path = _path_lxml(child)
            rels = [r for r in relations if r["source_path"] == path and r["attribute"] == "wit"]
            labels = [t["target_label"] for r in rels for t in r["tokens"] if t["target_label"]]
            slots.append({"role": "witness-attestation", "raw_wit": raw,
                          "target_labels": labels, "label": f"Witness attestation ({raw})"})
        elif kind != "witnesses" and tag in {"lem", "rdg"}:
            role = "lemma" if tag == "lem" else "reading"
            raw_rels = {key: child.get(key) for key in RELATION_ATTRIBUTES if child.get(key) is not None}
            path = _path_lxml(child)
            attached = [r for r in relations if r["source_path"] == path]
            labels = [t["target_label"] for r in attached for t in r["tokens"] if t["target_label"]]
            slots.append({"role": role, "source_text": _display_text_lxml(child),
                          "raw_relations": raw_rels, "resolved_target_labels": labels})
    for node in app.iter():
        if node is not app and _local(node.tag) == "note":
            notes.append({"source_text": " ".join("".join(node.itertext()).split()),
                          "attributes": dict(node.attrib)})
    if kind == "witnesses":
        if not slots:
            absent.append("witness-attestation")
    else:
        if not any(slot["role"] == "lemma" for slot in slots):
            absent.append("lemma")
        if not any(slot["role"] == "reading" for slot in slots):
            absent.append("reading")
    for node in app.iter():
        if node is not app and kind != "witnesses" and _local(node.tag) == "witStart":
            raw = node.get("wit", "")
            slots.append({"role": "source-witness-start-marker", "raw_wit": raw,
                          "label": f"Source witness marker ({raw})"})
    relation_labels = []
    for relation in relations:
        relation_labels.append({
            "source_path": relation["source_path"],
            "attribute": relation["attribute"],
            "raw_value": relation["raw_value"],
            "resolved_target_labels": [t["target_label"] for t in relation["tokens"] if t["target_label"]],
            "unresolved_tokens": [t["token"] for t in relation["tokens"] if t["classification"] == "unresolved-fragment"],
            "literal_tokens": [t["token"] for t in relation["tokens"] if t["classification"] == "literal-source-value"],
        })
    notes_out = [{"generated_label": "Source note", **note} for note in notes]
    visible = " ".join(
        [f"[{kind} apparatus]"]
        + [f"[{slot}]" if slot in {"lemma", "reading", "witness-attestation"} else slot for slot in absent]
        + [f"[{item['role']}: {item.get('source_text', item.get('raw_wit', ''))}; source_relations={item.get('raw_relations', {'wit': item.get('raw_wit')} if 'raw_wit' in item else {})}; resolved_targets={item.get('resolved_target_labels', item.get('target_labels', []))}]" for item in slots]
        + [f"[{item['attribute']}={item['raw_value']}; resolved_targets={item['resolved_target_labels']}; unresolved={item['unresolved_tokens']}; literals={item['literal_tokens']}]" for item in relation_labels]
        + [f"[Source note: {note.get('source_text', '')}; source_attributes={note.get('attributes', {})}]" for note in notes_out if note.get("source_text")]
    )
    return {
        "generated_context_role": "source-apparatus-display",
        "generated_labels_are_not_source_text": True,
        "apparatus_type": kind,
        "lemma_and_reading_slots": slots,
        "explicitly_absent_slots": absent,
        "generated_relation_labels": relation_labels,
        "notes": notes_out,
        "visible_summary": visible,
    }


def _source_expectation_lxml(source_raw: bytes) -> list[dict]:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                             remove_comments=False, remove_pis=False)
    root = etree.fromstring(source_raw, parser)
    edition = root.xpath(
        "./t:text/t:body/t:div[@type='edition' and @n=$n]",
        namespaces={"t": NS}, n=EDITION_N,
    )
    if len(edition) != 1 or edition[0].get(X + "lang") != "syc":
        raise ProfileMismatch("independent LXML source edition selection differs")
    expected = []
    for app in edition[0].xpath(".//t:app", namespaces={"t": NS}):
        relations = _relations_lxml(app, root)
        expected.append({
            "source_path": _path_lxml(app),
            "attributes": _attrs_lxml(app),
            "content": _tree_lxml(app),
            "source_relations": relations,
            "display": _display_lxml(app, relations),
            "tail": app.tail or "",
        })
    return expected


def independently_verify(source_raw: bytes, master_raw: bytes,
                         projected: list[dict], *, repository_root: Path, identity=IDENTITY,
                         language=LANGUAGE, category=CATEGORY,
                         collection=False, projection_profile=PROFILE_ID,
                         allow_acceptance_metadata=True) -> dict:
    """Re-derive source app trees with LXML and compare to ET producer output."""
    if _sha(source_raw) != SOURCE_SHA256 or len(source_raw) != SOURCE_BYTES:
        raise ProfileMismatch("independent observer source authority differs")
    if (identity != IDENTITY or language != LANGUAGE or category != CATEGORY
            or collection is not False or projection_profile != PROFILE_ID
            or allow_acceptance_metadata is not True or _sha(master_raw) != MASTER_SHA256):
        raise ProfileMismatch("independent observer exact accepted route differs")
    header = _load_header_module()
    header.observe_source_derivation(
        source_raw, master_raw, repository_root=Path(repository_root), identity=identity,
        language=language, category=category, collection=collection,
        projection_profile=header.PROFILE_ID,
        allow_acceptance_metadata=allow_acceptance_metadata,
    )
    expected = _source_expectation_lxml(source_raw)
    actual_master = _source_expectation_lxml(master_raw)
    if actual_master != expected:
        raise ProfileMismatch("bound master apparatus differs from independently parsed source")
    projected_records = [{
        "source_path": record.get("source_path"),
        "attributes": record.get("attributes"),
        "content": record.get("content"),
        "source_relations": record.get("source_relations"),
        "display": record.get("display"),
        "tail": record.get("tail"),
    } for record in projected]
    if projected_records != expected:
        raise ProfileMismatch("producer apparatus differs from LXML raw-source inventory")
    return {
        "status": "pass",
        "source_sha256": _sha(source_raw),
        "master_sha256": _sha(master_raw),
        "apparatus_units": len(expected),
        "producer_and_independent_source_inventory_equal": True,
        "lxml_source_and_bound_master_equal": True,
        "ordered_source_paths_sha256": _sha(json.dumps(
            [record["source_path"] for record in expected], separators=(",", ":")
        ).encode("utf-8")),
        "ordered_source_tree_sha256": _sha(json.dumps(
            expected, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")),
    }


def _header_ledger(master_raw: bytes) -> dict:
    """Capture ordered PIs and scholarly nodes as nonpublic source evidence."""
    profile = _load_header_module()
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                             remove_comments=False, remove_pis=False)
    root = etree.fromstring(master_raw, parser)
    pis = profile.prolog_processing_instruction_records(root)
    source_desc = root.xpath("./t:teiHeader/t:fileDesc/t:sourceDesc", namespaces={"t": NS})
    if len(source_desc) != 1:
        raise ProfileMismatch("source scholarly header envelope differs")
    binding_nodes = set()
    bindings = source_desc[0].xpath(
        ".//t:bibl/t:idno[@type='representation_revision' and text()='pta-l812-part-iii-syriac-electronic-v2']/..",
        namespaces={"t": NS},
    )
    if len(bindings) != 1:
        raise ProfileMismatch("exact acceptance bibl is missing or duplicated")
    binding = bindings[0]
    wrapper = binding.getparent()
    if wrapper is source_desc[0]:
        binding_nodes.update(binding.iter())
    elif (wrapper is not None and etree.QName(wrapper).localname == "p"
          and wrapper.getparent() is source_desc[0] and not wrapper.attrib
          and len(wrapper) == 1 and wrapper[0] is binding
          and not (wrapper.text or "").strip() and not (wrapper.tail or "").strip()
          and not (binding.tail or "").strip()):
        binding_nodes.update(wrapper.iter())
    else:
        raise ProfileMismatch("acceptance bibl wrapper is not the supported scoped carrier")
    source_children = [child for child in source_desc[0] if child not in binding_nodes]
    if [etree.QName(child).localname for child in source_children] != ["listWit", "listBibl"]:
        raise ProfileMismatch("source scholarly header envelope differs")
    nodes = []
    for node in source_desc[0].iter():
        if node in binding_nodes:
            continue
        nodes.append({
            "path": _path_lxml(node),
            "tag": _local(node.tag),
            "attributes": _attrs_lxml(node),
            "text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_sha256": _sha((node.tail or "").encode("utf-8")),
            "disposition": "source-scholarly-header-context",
        })
    return {"prolog_processing_instructions": list(pis),
            "source_header_nodes": nodes,
            "source_header_node_count_including_sourceDesc": len(nodes)}


def run(source_raw: bytes, master_raw: bytes, *, repository_root: Path) -> dict:
    output = produce_apparatus(master_raw, repository_root=repository_root)
    readback = independently_verify(source_raw, master_raw, output, repository_root=repository_root)
    return {
        "status": "pass",
        "profile_id": PROFILE_ID,
        "identity": IDENTITY,
        "language": LANGUAGE,
        "category": CATEGORY,
        "source_sha256": _sha(source_raw),
        "master_sha256": _sha(master_raw),
        "apparatus_count": len(output),
        "generated_readable_examples": [record["display"] for record in output[:3]],
        "apparatus_records": output,
        "header_ledger": _header_ledger(master_raw),
        "independent_readback": readback,
    }
