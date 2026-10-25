"""Source-bound L812 projection adapter for the accepted Syriac Part III witness."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import importlib.util

from lxml import etree
import jsonschema

from ocd_kernel.lib.path_io import io_path
from ocd_kernel.projection.native_content import content_policy, project_content
from ocd_kernel.projection.native_content_check import observe_content

PROFILE_MODULE = Path(__file__).with_name("reader_profile.py")
MASTER_RELATIVE = ("library/works/john-of-ephesus-ecclesiastical-history/forms/syriac/editions/"
                   "pta-ef861ab3-john-ecclesiastical-history-part-iii/master.tei.xml")
PROFILE = "ocd-prose-pta-l812-john-ephesus-part-iii-apparatus-v1"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
Q = "{" + TEI + "}"
X = "{" + XML + "}"
REL_ATTRS = ("wit", "resp", "source", "hand")
PROFILE_LINK_ATTRS = ("edRef", "ref", "target")
POSTIMAGE_SCHEMA_RELATIVE = "schemas/v2/native-content.schema.json"
APP_ATTRS = {
    "add": {"hand", "place"}, "app": {"type"}, "del": {"hand", "rend"},
    "gap": {"quantity", "reason", "unit"}, "hi": {"rend"},
    "lacunaEnd": set(), "lacunaStart": set(), "lem": {"hand", "rend", "resp", "source", "type", "varSeq", "wit"},
    "note": {"hand", "place"}, "pb": {"edRef", "n"}, "rdg": {"hand", "resp", "source", "type", "varSeq", "wit"},
    "subst": {"hand"}, "supplied": set(), "title": set(), "witStart": set(),
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _local(tag):
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _path(node, parent_map):
    chain = []
    while True:
        parent = parent_map.get(node)
        siblings = list(parent) if parent is not None else [node]
        same = [child for child in siblings if child.tag == node.tag]
        chain.append(f"{_local(node.tag)}[{same.index(node) + 1}]")
        if parent is None:
            break
        node = parent
    return "/" + "/".join(reversed(chain))


def _tree(node):
    return {
        "tag": _local(node.tag),
        "attributes": [{"name": k, "value": v} for k, v in sorted(node.attrib.items())],
        "text": node.text or "",
        "children": [{"node": _tree(child), "tail": child.tail or ""} for child in node],
    }


def _tree_lxml(node):
    return {
        "tag": _local(node.tag),
        "attributes": [{"name": k, "value": v} for k, v in sorted(node.attrib.items())],
        "text": node.text or "",
        "children": [{"node": _tree_lxml(child), "tail": child.tail or ""} for child in node],
    }


def _text(node):
    parts = [node.text or ""]
    for child in node:
        parts.append(_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _public_records_lxml(nodes, targets):
    """Independent reader-facing expectation derived from the lxml source tree."""
    records = []
    for node in nodes:
        tag = _local(node.tag)
        if tag == "app":
            app_type = node.get("type", "")
            slots = []
            wanted = ([("witness-attestation", child) for child in node
                       if _local(child.tag) == "rdg"] if app_type == "witnesses" else
                      [(role, child) for role, local in (("lemma", "lem"), ("reading", "rdg"))
                       for child in node if _local(child.tag) == local])
            for role, child in wanted:
                def visible_lxml(current):
                    parts = [current.text or ""]
                    for nested in current:
                        if _local(nested.tag) != "note":
                            parts.append(visible_lxml(nested))
                        parts.append(nested.tail or "")
                    return "".join(parts)
                source_text = re.sub(r"\s+", " ", visible_lxml(child)).strip()
                relation_summaries = []
                for descendant in child.iter():
                    for relation_attr in REL_ATTRS + PROFILE_LINK_ATTRS:
                        raw = descendant.get(relation_attr)
                        if raw:
                            labels, unresolved, literals = [], 0, []
                            for token in raw.split():
                                target_id = token[1:] if token.startswith("#") else None
                                target = targets.get(target_id) if target_id else None
                                if target is not None:
                                    label = re.sub(r"\s+", " ", "".join(target.itertext())).strip()
                                    if label:
                                        labels.append(label)
                                elif target_id is not None:
                                    unresolved += 1
                                else:
                                    literals.append(token)
                            relation_summaries.append({"attribute": relation_attr,
                                                       "resolved_labels": labels,
                                                       "unresolved_count": unresolved,
                                                       "literal_values": literals})
                slots.append({"role": role, "text": source_text,
                              "relations": relation_summaries})
            absent = []
            if app_type != "witnesses":
                if not any(_local(child.tag) == "lem" for child in node):
                    absent.append("lemma")
                if not any(_local(child.tag) == "rdg" for child in node):
                    absent.append("reading")
            elif not slots:
                absent.append("witness-attestation")
            notes = [re.sub(r"\s+", " ", "".join(note.itertext())).strip()
                     for note in node.iterdescendants() if _local(note.tag) == "note"]
            display = {"type": app_type, "slots": slots, "absent_slots": absent,
                       "notes": notes,
                       "notice": "Generated reading labels distinguish source alternatives; they are not source wording."}
            public = {"kind": "l812-apparatus", "attributes": {"type": app_type},
                      "content": [{"kind": "text", "text": _readable_apparatus(display)}],
                      "apparatus": display}
        else:
            refs = []
            for descendant in node.iter():
                for attr in PROFILE_LINK_ATTRS:
                    raw = descendant.get(attr)
                    if raw:
                        refs.append(raw)
            text = " ".join("".join(node.itertext()).split())
            if tag in {"persName", "placeName", "pb", "cb"} and refs:
                labels = []
                for raw in refs:
                    for token in raw.split():
                        target_id = token[1:] if token.startswith("#") else None
                        target = targets.get(target_id) if target_id else None
                        if target is not None:
                            label = " ".join("".join(target.itertext()).split())
                            if label:
                                labels.append(label)
                readable = f"[{tag} source reference {'; '.join(refs)}"
                if labels:
                    readable += f"; retained target labels: {'; '.join(labels)}"
                readable += f": {text}]"
            else:
                readable = "".join(node.itertext())
            public = {"kind": "l812-source-context", "attributes": {"type": tag},
                      "content": [{"kind": "text", "text": readable}] if readable else []}
        records.append(public)
    return records


def _observe_generic_spans_lxml(body, carriers, public_records):
    """Independently derive ordinary spans from an LXML placeholder source."""
    body_raw = etree.tostring(body, encoding="utf-8")
    clone = etree.fromstring(body_raw, etree.XMLParser(resolve_entities=False, load_dtd=False,
                                                       no_network=True, remove_comments=False,
                                                       remove_pis=False))
    comments = []
    for comment in clone.xpath(".//comment()"):
        parent = comment.getparent()
        siblings = [child for child in parent if isinstance(child, etree._Comment)]
        comments.append({"parent_path": _path_lxml(parent),
                         "ordinal_in_parent": siblings.index(comment) + 1,
                         "text": comment.text or "", "tail": comment.tail or ""})
    # The maintained stdlib producer parser discards XML comment nodes while
    # retaining their following character data. Mirror that exact behavior in
    # the independent LXML oracle and bind comment payloads in a private ledger.
    for comment in clone.xpath(".//comment()"):
        parent = comment.getparent()
        position = parent.index(comment)
        if comment.tail:
            if position:
                previous = parent[position - 1]
                previous.tail = (previous.tail or "") + comment.tail
            else:
                parent.text = (parent.text or "") + comment.tail
        parent.remove(comment)
    clone_nodes = {_relative_path_lxml(node, clone): node for node in clone.iter()
                   if isinstance(node.tag, str) and node is not clone}
    bindings = []
    for ordinal, source_node in enumerate(carriers, 1):
        path = _relative_path_lxml(source_node, body)
        cloned = clone_nodes.get(path)
        if cloned is None:
            raise ValueError(f"independent generic observer cannot locate carrier path {path}")
        token = f"L812PROFILE{ordinal:05d}X"
        stub = etree.Element(Q + "seg", type="l812-profile-placeholder")
        stub.text = token
        stub.tail = cloned.tail
        parent = cloned.getparent()
        position = parent.index(cloned)
        parent.remove(cloned)
        parent.insert(position, stub)
        bindings.append((token, public_records[ordinal - 1]))
    generic, generic_text = observe_content(etree.tostring(clone, encoding="utf-8"))
    by_token = dict(bindings)
    def substitute(node):
        if (node.get("kind") == "segment"
                and node.get("attributes", {}).get("type") == "l812-profile-placeholder"):
            text = "".join(child.get("text", "") for child in node.get("content", [])
                           if child.get("kind") == "text")
            try:
                return by_token.pop(text)
            except KeyError as exc:
                raise ValueError(f"independent generic observer saw an unknown placeholder: {text}") from exc
        if "content" in node:
            node["content"] = [substitute(child) for child in node["content"]]
        return node
    complete = substitute(generic)
    if by_token:
        raise ValueError(f"independent generic observer missed placeholders: {len(by_token)}")
    return complete, generic_text, comments


def _raw_c14n(node):
    return etree.tostring(etree.fromstring(ET.tostring(node, encoding="utf-8")), method="c14n", with_comments=True)


def _source_candidates(body, parents):
    policy = content_policy()
    candidates = []
    for node in body.iter():
        if not isinstance(node.tag, str):
            continue
        tag = _local(node.tag)
        rule = policy["elements"].get(tag)
        attrs = {_local(k) if not k.startswith(X) else "xml:" + k[len(X):] for k in node.attrib}
        unsupported = rule is None or attrs - set(rule.get("attributes", {}))
        if not unsupported:
            continue
        ancestor = parents.get(node)
        nested_in_candidate = False
        while ancestor is not None:
            if any(ancestor is existing for existing in candidates):
                nested_in_candidate = True
                break
            ancestor = parents.get(ancestor)
        if not nested_in_candidate:
            candidates.append(node)
    return candidates, parents


def _nearest_language(node, parents):
    current = node
    while current is not None:
        lang = current.get(X + "lang")
        if lang:
            return lang
        current = parents.get(current)
    return None


def _apparatus_display(node):
    kind = node.get("type")
    parts = [f"[{kind} apparatus]"]
    lemmas = [x for x in node if _local(x.tag) == "lem"]
    readings = [x for x in node if _local(x.tag) == "rdg"]
    if kind == "witnesses":
        readings = [x for x in node if _local(x.tag) == "rdg"]
        if not readings:
            parts.append("[witness attestation absent]")
        for reading in readings:
            parts.append(f"[Witness attestation; wit={reading.get('wit', '')}: {_text(reading)}]")
    else:
        if not lemmas:
            parts.append("[lemma absent]")
        if not readings:
            parts.append("[reading absent]")
        for label, values in (("Lemma", lemmas), ("Reading", readings)):
            for value in values:
                parts.append(f"[{label}: {_text(value)}]")
    for note in node.iter():
        if note is not node and _local(note.tag) == "note":
            parts.append(f"[Source note: {_text(note)}]")
    return " ".join(parts)


def _carrier(node, path, language, parents, targets, profile_module):
    tag = _local(node.tag)
    attrs = [{"name": k, "value": v} for k, v in sorted(node.attrib.items())]
    relations = []
    for descendant in node.iter():
        for attr in REL_ATTRS + PROFILE_LINK_ATTRS:
            raw = descendant.get(attr)
            if raw is None:
                continue
            target_tokens = []
            for token in raw.split():
                target_id = token[1:] if token.startswith("#") else None
                target = targets.get(target_id) if target_id is not None else None
                target_tokens.append({
                    "token": token,
                    "classification": "resolved-fragment" if target is not None else "unresolved-fragment" if target_id is not None else "literal-source-value",
                    "target_id": target_id,
                    "target_label": " ".join("".join(target.itertext()).split()) if target is not None else None,
                })
            relations.append({"source_path": _path(descendant, parents), "attribute": attr, "raw_value": raw,
                              "tokens": target_tokens})
    if tag == "app":
        display = profile_module._render_apparatus(
            node, profile_module._relations_for_app(node, parents, targets), parents,
        )
        visible = display["visible_summary"]
    else:
        display = None
        link_relations = [item for item in relations if item["attribute"] in PROFILE_LINK_ATTRS]
        if tag in {"persName", "placeName", "pb", "cb"} and link_relations:
            labels = [token["target_label"] for relation in link_relations
                      for token in relation["tokens"] if token["target_label"]]
            raw_links = [relation["raw_value"] for relation in link_relations]
            visible = f"[{tag} source reference {'; '.join(raw_links)}"
            if labels:
                visible += f"; retained target labels: {'; '.join(labels)}"
            visible += f": {_text(node)}]"
        else:
            visible = _text(node)
    # The native/public carrier contains only reader-facing semantics. Exact
    # XPath, source tree, raw attributes and raw relation tokens belong in the
    # separate private ledger returned by project(), never in public content.
    if tag == "app":
        public_display = _public_apparatus_display(display, node, parents, relations)
        readable = _readable_apparatus(public_display)
        public = {
            "kind": "l812-apparatus",
            "attributes": {"type": node.get("type", "")},
            "content": [{"kind": "text", "text": readable}] if readable else [],
            "apparatus": public_display,
        }
    else:
        public = {
            "kind": "l812-source-context",
            "attributes": {"type": tag},
            "content": [{"kind": "text", "text": visible}] if visible else [],
        }
    private = {"source_path": path, "source_tag": tag,
               "inherited_language": language, "source_attributes": attrs,
               "source_tree": _tree(node), "source_tail": node.tail or "",
               "source_relations": relations}
    return public, private


def _public_apparatus_display(display, node, parents, relations):
    if not isinstance(display, dict):
        raise ValueError("apparatus display missing")
    slots = []
    candidate_children = [child for child in node if _local(child.tag) in {"lem", "rdg"}]
    for index, slot in enumerate(display.get("lemma_and_reading_slots", [])):
        child = candidate_children[index]
        source_path = _path(child, parents)
        relation_summaries = []
        for relation in relations:
            rel_path = relation.get("source_path", "")
            if rel_path == source_path or rel_path.startswith(source_path + "/"):
                relation_summaries.append({
                    "attribute": relation.get("attribute"),
                    "resolved_labels": [token["target_label"] for token in relation["tokens"]
                                        if token["classification"] == "resolved-fragment" and token["target_label"]],
                    "unresolved_count": sum(token["classification"] == "unresolved-fragment"
                                             for token in relation["tokens"]),
                    "literal_values": [token["token"] for token in relation["tokens"]
                                       if token["classification"] == "literal-source-value"],
                })
        slots.append({"role": slot.get("role"),
                      "text": slot.get("source_text", ""),
                      "relations": relation_summaries})
    return {"type": display.get("apparatus_type"),
            "slots": slots,
            "absent_slots": display.get("explicitly_absent_slots", []),
            "notes": [note.get("source_text", "") for note in display.get("notes", [])],
            "notice": "Generated reading labels distinguish source alternatives; they are not source wording."}


def _readable_apparatus(display):
    chunks = [f"[{display['type']} apparatus]"]
    for slot in display["slots"]:
        label = slot["role"].replace("-", " ").capitalize()
        if slot["text"]:
            chunks.append(f"{label}: {slot['text']}")
        for relation in slot["relations"]:
            detail = "; ".join(relation["resolved_labels"] + relation["literal_values"])
            if detail:
                chunks.append(f"{label} {relation['attribute']}: {detail}")
            if relation["unresolved_count"]:
                chunks.append(f"{label} {relation['attribute']}: {relation['unresolved_count']} unresolved source reference(s)")
    for missing in display["absent_slots"]:
        chunks.append(f"[{missing.replace('-', ' ')} absent]")
    for note in display["notes"]:
        chunks.append(f"Source note: {note}")
    return " ".join(chunks)


def project(master_raw: bytes, *, root: Path):
    repository_root = Path(root)
    if _sha(master_raw) != "c0aab5dd6685ee6b29db074426e5395871171664a5b3029714d250f599e3a153":
        raise ValueError("L812 master bytes do not match the accepted profile")
    spec = importlib.util.spec_from_file_location("ocd_john_l812_source_profile", PROFILE_MODULE)
    if spec is None or spec.loader is None:
        raise ValueError("source profile cannot be loaded")
    profile_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(profile_module)
    source_raw = io_path(repository_root / profile_module.SOURCE_PATH).read_bytes()
    source_proof = profile_module.run(source_raw, master_raw, repository_root=repository_root)
    if (source_proof.get("status") != "pass"
            or source_proof.get("source_sha256") != profile_module.SOURCE_SHA256
            or source_proof.get("master_sha256") != profile_module.MASTER_SHA256
            or source_proof.get("apparatus_count") != 710
            or source_proof.get("independent_readback", {}).get("status") != "pass"):
        raise ValueError("frozen raw source/master profile derivation did not pass")
    root = ET.fromstring(master_raw)
    body = root.find(f"{Q}text/{Q}body")
    if body is None:
        raise ValueError("TEI body missing")
    parents = {child: parent for parent in root.iter() for child in parent}
    candidates, parents = _source_candidates(body, parents)
    candidate_bindings = [(_path(node, parents), _nearest_language(node, parents)) for node in candidates]
    targets = {node.get(X + "id"): node for node in root.iter() if node.get(X + "id")}
    # Freeze all relation paths/records before replacing any sibling. ET
    # computes positional selectors from the live parent tree, so lazy
    # re-evaluation after a replacement would drift same-tag sibling numbers.
    prepared_records = [
        _carrier(node, path, lang, parents, targets, profile_module)
        for node, (path, lang) in zip(candidates, candidate_bindings, strict=True)
    ]
    replacements = []
    for index, (node, (path, lang), record) in enumerate(
            zip(candidates, candidate_bindings, prepared_records, strict=True), 1):
        token = f"L812PROFILE{index:05d}X"
        parent = parents[node]
        position = list(parent).index(node)
        stub = ET.Element(Q + "seg", {"type": "l812-profile-placeholder"})
        stub.text = token
        stub.tail = node.tail
        parent.remove(node)
        parent.insert(position, stub)
        public, private = record
        replacements.append((token, public, private, path))

    projected = project_content(body)
    by_token = {token: (public, private) for token, public, private, _ in replacements}
    found = []
    private_ledger = []

    def substitute(node):
        if node.get("kind") == "segment" and node.get("attributes", {}).get("type") == "l812-profile-placeholder":
            children = node.get("content", [])
            text = "".join(child.get("text", "") for child in children if child.get("kind") == "text")
            replacement = by_token.pop(text, None)
            if replacement is None:
                raise ValueError(f"unknown or duplicate profile placeholder: {text}")
            public, private = replacement
            found.append(private["source_path"])
            private_ledger.append(private)
            return public
        if "content" in node:
            node["content"] = [substitute(child) for child in node["content"]]
        return node

    projected = substitute(projected)
    if by_token:
        raise ValueError(f"profile placeholders not projected: {len(by_token)}")

    # Independent lxml source walk rederives the selected carrier paths/order,
    # exact carrier C14N, and non-carrier source text/tail commitment.
    lroot = etree.fromstring(master_raw, etree.XMLParser(resolve_entities=False, load_dtd=False,
                                                          no_network=True, remove_comments=False,
                                                          remove_pis=False))
    lbody = lroot.find(f"{Q}text/{Q}body")
    lparents = {child: parent for parent in lroot.iter() for child in parent}
    expected = []
    for node in lbody.iter():
        if not isinstance(node.tag, str):
            continue
        tag = _local(node.tag)
        rule = content_policy()["elements"].get(tag)
        attrs = {_local(k) if not k.startswith(X) else "xml:" + k[len(X):] for k in node.attrib}
        if rule is None or attrs - set(rule.get("attributes", {})):
            ancestor = lparents.get(node)
            nested = False
            while ancestor is not None:
                if any(ancestor is prior for prior in expected):
                    nested = True
                    break
                ancestor = lparents.get(ancestor)
            if nested:
                continue
            expected.append(node)
    expected_paths = [_path_lxml(node) for node in expected]
    if found != expected_paths:
        mismatch = next((i for i, pair in enumerate(zip(found, expected_paths, strict=False)) if pair[0] != pair[1]), None)
        raise ValueError(f"producer placeholder order differs from independent source walk: found={len(found)} expected={len(expected_paths)} mismatch={mismatch} found_at_mismatch={found[mismatch:mismatch+3] if mismatch is not None else []} expected_at_mismatch={expected_paths[mismatch:mismatch+3] if mismatch is not None else []}")
    tree_equal = all(
        _tree(et_node) == _tree_lxml(l_node)
        and (et_node.tail or "") == (l_node.tail or "")
        for et_node, l_node in zip(candidates, expected, strict=True)
    )
    if not tree_equal:
        mismatch = next(i for i, pair in enumerate(zip(candidates, expected, strict=True))
                        if _tree(pair[0]) != _tree_lxml(pair[1])
                        or (pair[0].tail or "") != (pair[1].tail or ""))
        raise ValueError(f"producer carrier trees differ from independent source carriers at {mismatch}")
    actual_public = []
    def collect_public(value):
        if value.get("kind") in {"l812-apparatus", "l812-source-context"}:
            actual_public.append(value)
            return
        for child in value.get("content", []):
            collect_public(child)
    collect_public(projected)
    ltargets = {node.get(X + "id"): node for node in lroot.iter()
                if isinstance(node.tag, str) and node.get(X + "id")}
    expected_public = _public_records_lxml(expected, ltargets)
    if actual_public != expected_public:
        mismatch = next((i for i, pair in enumerate(zip(actual_public, expected_public, strict=False))
                         if pair[0] != pair[1]), None)
        raise ValueError(f"emitted public source carriers differ from independent lxml rendering at {mismatch}; actual={actual_public[mismatch] if mismatch is not None else None}; expected={expected_public[mismatch] if mismatch is not None else None}")
    independent_full, independent_text, source_comments = _observe_generic_spans_lxml(lbody, expected, expected_public)
    if independent_full != projected:
        raise ValueError("actual full projection differs from independent LXML generic-span and public-carrier observation")
    forbidden_public_keys = {"source_path", "source_tree", "source_relations", "source_profile",
                             "inherited_language", "source_attributes", "source_tail", "raw_value"}
    def assert_public_private_split(value):
        if isinstance(value, dict):
            leaked = forbidden_public_keys.intersection(value)
            if leaked:
                raise ValueError(f"private source fields leaked into public carrier: {sorted(leaked)}")
            for child in value.values():
                assert_public_private_split(child)
        elif isinstance(value, list):
            for child in value:
                assert_public_private_split(child)
    assert_public_private_split(projected)
    expected_private = []
    for node in expected:
        language = node.get(X + "lang")
        parent = lparents.get(node)
        while language is None and parent is not None:
            language = parent.get(X + "lang")
            parent = lparents.get(parent)
        attrs = [{"name": key, "value": value} for key, value in sorted(node.attrib.items())]
        rels = []
        for descendant in node.iter():
            for attr in REL_ATTRS + PROFILE_LINK_ATTRS:
                raw = descendant.get(attr)
                if raw is None:
                    continue
                tokens = []
                for token in raw.split():
                    target_id = token[1:] if token.startswith("#") else None
                    target = ltargets.get(target_id) if target_id is not None else None
                    tokens.append({
                        "token": token,
                        "classification": "resolved-fragment" if target is not None else
                                         "unresolved-fragment" if target_id is not None else
                                         "literal-source-value",
                        "target_id": target_id,
                        "target_label": " ".join("".join(target.itertext()).split()) if target is not None else None,
                    })
                rels.append({"source_path": _path_lxml(descendant), "attribute": attr,
                             "raw_value": raw, "tokens": tokens})
        expected_private.append({"source_path": _path_lxml(node), "source_tag": _local(node.tag),
                                 "inherited_language": language, "source_attributes": attrs,
                                 "source_tree": _tree_lxml(node), "source_tail": node.tail or "",
                                 "source_relations": rels})
    if private_ledger != expected_private:
        mismatch = next((i for i, pair in enumerate(zip(private_ledger, expected_private, strict=False))
                         if pair[0] != pair[1]), None)
        raise ValueError(f"private source ledger differs from independent raw-source derivation at {mismatch}")
    source_text = "".join(lbody.itertext())
    ledger_for_text = list(private_ledger)
    projected_source_text = _projected_text(projected, ledger_for_text)
    if ledger_for_text:
        raise ValueError(f"unconsumed private source ledger entries: {len(ledger_for_text)}")
    if source_text != projected_source_text:
        raise ValueError(f"complete ordered source text/tail stream differs: source_chars={len(source_text)} projected_chars={len(projected_source_text)}")
    return {"status": "pass", "master_sha256": hashlib.sha256(master_raw).hexdigest(),
            "profile_id": PROFILE, "carrier_count": len(candidates),
            "carrier_tags": dict(sorted(__import__('collections').Counter(_local(x.tag) for x in candidates).items())),
            "carrier_paths_sha256": hashlib.sha256("\n".join(expected_paths).encode()).hexdigest(),
            "carrier_tree_and_tail_equal": True, "source_text_stream_equal": True,
            "emitted_public_carriers_equal_independent_lxml": True,
            "full_projection_equal_independent_lxml_native_observer": True,
            "independent_generic_text_chars": len(independent_text),
            "source_comment_count": len(source_comments),
            "source_comment_ledger_sha256": hashlib.sha256(
                json.dumps(source_comments, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "private_ledger_equal_independent_lxml": True,
            "public_private_field_separation": True,
            "private_ledger_count": len(private_ledger),
            "private_ledger_sha256": hashlib.sha256(
                json.dumps(private_ledger, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "private_source_ledger": private_ledger,
            "private_source_comment_ledger": source_comments,
            "source_text_chars": len(source_text), "native_projection": projected,
            "visible_text_sample": _visible(projected)[:2500]}


def observe_emitted(candidate_projection, candidate_ledger, candidate_comments, source_bound_expected, *, repository_root: Path):
    """Validate emitted values and schema using the caller's explicit repository root."""
    repository_root = Path(repository_root)
    errors = []
    if candidate_projection != source_bound_expected["native_projection"]:
        errors.append("public native projection differs from source-bound expected projection")
    if candidate_ledger != source_bound_expected["private_source_ledger"]:
        errors.append("private source ledger differs from source-bound expected ledger")
    if candidate_comments != source_bound_expected["private_source_comment_ledger"]:
        errors.append("private source comment ledger differs from source-bound expected comments")
    schema = json.loads(io_path(repository_root / POSTIMAGE_SCHEMA_RELATIVE).read_bytes())
    errors.extend("native schema: " + error.message
                  for error in jsonschema.Draft202012Validator(schema).iter_errors(candidate_projection))
    return errors


def _path_lxml(node):
    pieces = []
    current = node
    while current is not None and isinstance(current.tag, str):
        parent = current.getparent()
        siblings = [child for child in parent if child.tag == current.tag] if parent is not None else [current]
        pieces.append(f"{_local(current.tag)}[{siblings.index(current)+1}]")
        current = parent
    return "/" + "/".join(reversed(pieces))


def _relative_path_lxml(node, ancestor):
    pieces = []
    current = node
    while current is not ancestor:
        parent = current.getparent()
        if parent is None:
            raise ValueError("LXML node is not descended from expected body")
        siblings = [child for child in parent if child.tag == current.tag]
        pieces.append(f"{_local(current.tag)}[{siblings.index(current) + 1}]")
        current = parent
    return "/" + "/".join(reversed(pieces))


def _visible(node):
    if node.get("kind") == "text":
        return node.get("text", "")
    return "".join(_visible(child) for child in node.get("content", []))


def _tree_text(tree):
    return tree["text"] + "".join(
        _tree_text(child["node"]) + child["tail"] for child in tree["children"]
    )


def _projected_text(node, private_ledger):
    if node.get("kind") in {"l812-apparatus", "l812-source-context"}:
        if not private_ledger:
            raise ValueError("private source ledger exhausted before public carrier")
        return _tree_text(private_ledger.pop(0)["source_tree"])
    if node.get("kind") == "text":
        return node.get("text", "")
    return "".join(_projected_text(child, private_ledger) for child in node.get("content", []))


