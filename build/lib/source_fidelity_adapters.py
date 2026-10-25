"""Source readers for explicit XML mappings and catechism JSON relationships.

These emit claims, not serialized TEI, and import no producers or producer inventories.
Mapping policy still needs source-specific review; parser agreement cannot validate it.
"""
from __future__ import annotations

import json
import re
from lxml import etree

from build.lib.source_fidelity import Carrier, Expectations, TEI, XML_ID, digest, tag_name


def strict_json(data: bytes):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"invalid JSON number: {value}")
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)


def _entry(feature):
    return dict(feature=feature, disposition="unsupported", reason="no source mapping claim")


def _pointer(key):
    return str(key).replace("~", "~0").replace("/", "~1")


def _json_inventory(value, coverage, path=""):
    coverage[path] = _entry("json-" + ("object" if isinstance(value, dict) else "array"
                                     if isinstance(value, list) else "value"))
    if isinstance(value, dict):
        for key, child in value.items():
            _json_inventory(child, coverage, path + "/" + _pointer(key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _json_inventory(child, coverage, path + f"/{i}")


def catechism(data: bytes, profile: dict) -> Expectations:
    source = strict_json(data)
    if not isinstance(source, dict) or not isinstance(source.get("Data"), list):
        raise ValueError("catechism source requires an object with a Data array")
    prefix = "lib062-" + profile["work_id"]
    scope = prefix + "-body"
    plan = Expectations(scope, digest(data), profile,
        limitations=["Checks the Data/body subtree; Metadata and generated TEI header are excluded.",
                     "Field-to-role mapping is declared, not independently certified by parser agreement."])
    _json_inventory(source, plan.coverage)
    for path in plan.coverage:
        if path == "/Metadata" or path.startswith("/Metadata/"):
            plan.account(path, disposition="excluded", reason="metadata is outside this body-fidelity adapter")
    children = {}
    def add(key, parent, tag, attrs=None, text="", location=""):
        if not isinstance(text, str):
            raise ValueError(f"expected source string at {location}")
        position = 0 if parent is None else children.get(parent, 0) + 1
        if parent is not None:
            children[parent] = position
        attributes = dict(attrs or {})
        if not key:
            key = f"{parent}/child[{position}]"
        else:
            attributes[XML_ID] = key
        plan.carriers.append(Carrier(key, parent, position, f"{{{TEI}}}{tag}", attributes,
                                     text, "", location))
        if location in plan.coverage:
            plan.account(location, key)
        return key
    def label(value, location):
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"expected integer/string source label at {location}")
        return str(value)
    add(scope, None, "div", {"type": "catechism"}, location="/Data")
    plan.account("", scope)
    for i, row in enumerate(source["Data"]):
        path = f"/Data/{i}"
        if not isinstance(row, dict) or not {"Number", "Question", "Answer"} <= row.keys():
            raise ValueError(f"invalid catechism row at {path}")
        key = f"{prefix}-row-{i+1:04d}"
        add(key, scope, "div", {"type": "question-unit", "n": label(row["Number"], path + "/Number")}, location=path)
        add(key + "-number", key, "label", {"type": "source-number"},
            label(row["Number"], path + "/Number"), path + "/Number")
        for field, role in [("Question", "question"), ("QuestionWithProofs", "question-with-proofs"),
                            ("Answer", "answer"), ("AnswerWithProofs", "answer-with-proofs")]:
            if field in row:
                add(key + "-" + role, key, "p", {"ana": "#" + role}, row[field], path + "/" + field)
        if "SubQuestions" in row:
            subpath = path + "/SubQuestions"
            subs = row["SubQuestions"]
            if not isinstance(subs, list):
                raise ValueError(f"expected array at {subpath}")
            if not subs:
                add(key + "-subquestions-empty", key, "note", {"type": "source-empty-array", "n": "SubQuestions"}, location=subpath)
            else:
                owner = add(key + "-subquestions", key, "list", {"type": "subquestions"}, location=subpath)
                for j, sub in enumerate(subs):
                    loc = subpath + f"/{j}"
                    if not isinstance(sub, dict) or not {"Number", "Question", "Answer"} <= sub.keys():
                        raise ValueError(f"invalid subquestion at {loc}")
                    sid = f"{key}-sub-{j+1:04d}"
                    add(sid, owner, "item", {"n": label(sub["Number"], loc + "/Number")}, location=loc)
                    add(sid + "-number", sid, "label", {"type": "subquestion-number"}, label(sub["Number"], loc + "/Number"), loc + "/Number")
                    for field in ("Question", "Answer"):
                        role = field.lower()
                        add(sid + "-" + role, sid, "p", {"ana": "#subquestion-" + role}, sub[field], loc + "/" + field)
        if "Proofs" in row:
            proofpath = path + "/Proofs"
            proofs = row["Proofs"]
            if not isinstance(proofs, list):
                raise ValueError(f"expected array at {proofpath}")
            if not proofs:
                add(key + "-proofs-empty", key, "note", {"type": "source-empty-array", "n": "Proofs"}, location=proofpath)
            else:
                owner = add(key + "-proofs", key, "list", {"type": "proofs"}, location=proofpath)
                for j, proof in enumerate(proofs):
                    loc = proofpath + f"/{j}"
                    if not isinstance(proof, dict) or not {"Id", "References"} <= proof.keys() or not isinstance(proof["References"], list):
                        raise ValueError(f"invalid proof at {loc}")
                    pid = f"{key}-proof-{j+1:03d}"
                    add(pid, owner, "item", {"n": label(proof["Id"], loc + "/Id")}, location=loc)
                    add(pid + "-id", pid, "label", {"type": "proof-id"}, label(proof["Id"], loc + "/Id"), loc + "/Id")
                    refs = add(None, pid, "listBibl", {"type": "source-references"}, location=loc + "/References")
                    for k, ref in enumerate(proof["References"]):
                        rloc = loc + f"/References/{k}"
                        rid = add(f"{pid}-ref-{k+1:03d}", refs, "bibl", location=rloc)
                        add(None, rid, "ref", {"type": "scripture"}, ref, rloc)
    return plan


def xml_mapping(data: bytes, profile: dict) -> Expectations:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                             remove_blank_text=False, remove_comments=False, remove_pis=False)
    root = etree.fromstring(data, parser)
    if any(isinstance(n, etree._Entity) for n in root.iter()):
        raise ValueError("unexpanded source entities require a dedicated reader")
    selected = root.xpath("//*[@id=$identity or @xml:id=$identity]", identity=profile["source_root_id"])
    if len(selected) != 1:
        raise ValueError(f"source selection must resolve once, observed {len(selected)}")
    selected = selected[0]
    tree = root.getroottree()
    plan = Expectations(profile["candidate_root_id"], digest(data), profile,
        limitations=["Only the explicitly selected source subtree is compared; outer material and TEI header are excluded.",
                     "Mapping and exclusion policy requires source review; parser agreement does not certify semantics."])
    count = 0
    native_ids = {}
    all_ids = {}
    for item in root.iter():
        if isinstance(item.tag, str):
            for native in set(filter(None, (item.get("id"), item.get(XML_ID)))):
                all_ids[native] = all_ids.get(native, 0) + 1
    ordinal = 0
    for item in selected.iter():
        if isinstance(item.tag, str):
            ordinal += 1
            for native in (item.get("id"), item.get(XML_ID)):
                if native:
                    if native in native_ids and native_ids[native] != profile["id_prefix"] + str(ordinal):
                        raise ValueError(f"ambiguous native source identity: {native}")
                    native_ids[native] = profile["id_prefix"] + str(ordinal)
    tag_map, attr_map = profile["tags"], profile["attributes"]
    excluded = profile["excluded_attributes"]
    def account(loc, feature, key=None, disposition="checked", reason=""):
        plan.coverage[loc] = _entry(feature)
        if key is not None or disposition != "checked":
            plan.account(loc, key, disposition=disposition, reason=reason)
    def visit(node, parent, position):
        nonlocal count
        loc = tree.getpath(node)
        if isinstance(node.tag, str):
            count += 1
            key = profile["id_prefix"] + str(count)
            attrs = {XML_ID: key}
            source_tag = node.tag
            target_tag = tag_map.get(source_tag)
            account(loc, "xml-element:" + source_tag, key if target_tag else None)
            tag = f"{{{TEI}}}{target_tag}" if target_tag else "#unsupported:" + source_tag
            for attr, value in node.attrib.items():
                aloc = loc + "/@" + attr
                rule_key = source_tag + "@" + attr
                target = attr_map.get(rule_key, attr_map.get(attr))
                if target:
                    if target in attrs:
                        raise ValueError(f"conflicting source mappings to {target} at {loc}")
                    if attr in profile.get("native_link_attributes", []):
                        tokens = value.split()
                        resolved = []
                        for token in tokens:
                            native = token.removeprefix("#")
                            if native in native_ids:
                                if all_ids.get(native) != 1:
                                    raise ValueError(f"ambiguous native source link target: {native}")
                                resolved.append("#" + native_ids[native])
                            elif all_ids.get(native) == 1 and profile.get("external_base"):
                                resolved.append(profile["external_base"] + "#" + native)
                            else:
                                resolved = []
                                break
                        if resolved:
                            value = " ".join(resolved)
                            account(aloc, "xml-link:" + attr, key)
                        else:
                            account(aloc, "xml-link:" + attr)
                    elif target in ("target", "corresp", "facs", "next", "prev", "sameAs", "resp") and any(
                            token.startswith("#") for token in value.split()):
                        tokens = value.split()
                        if any(token.startswith("#") and all_ids.get(token[1:], 0) > 1 for token in tokens):
                            ambiguous = next(token[1:] for token in tokens if token.startswith("#")
                                             and all_ids.get(token[1:], 0) > 1)
                            raise ValueError(f"ambiguous native source link target: {ambiguous}")
                        if any(token.startswith("#") and token[1:] not in native_ids for token in tokens):
                            account(aloc, "xml-link:" + attr)
                        else:
                            value = " ".join("#" + native_ids[token[1:]] if token.startswith("#") else token
                                             for token in tokens)
                            account(aloc, "xml-link:" + attr, key)
                    else:
                        account(aloc, "xml-attribute:" + attr, key)
                    attrs[target] = value
                elif rule_key in excluded or attr in excluded:
                    account(aloc, "xml-attribute:" + attr, disposition="excluded",
                            reason=excluded.get(rule_key, excluded.get(attr)))
                else:
                    account(aloc, "xml-attribute:" + attr)
            fixed = profile.get("fixed_attributes", {}).get(source_tag, {})
            if set(fixed) & set(attrs):
                raise ValueError(f"fixed/source attribute collision at {loc}")
            attrs.update(fixed)
        else:
            key = f"{parent}/child[{position}]"
            tag, attrs = tag_name(node), {}
            account(loc, tag, key)
        for suffix in ("text", "tail"):
            account(loc + "/" + suffix, "xml-" + suffix, key)
        plan.carriers.append(Carrier(key, parent, position, tag, attrs, node.text or "", node.tail or "", loc))
        for i, child in enumerate(node, 1):
            visit(child, key, i)
    visit(selected, None, 0)
    if plan.carriers[0].key != plan.scope_id:
        raise ValueError("candidate_root_id must match the source root's ordinal identity")
    plan.coverage["@outside-selection"] = dict(feature="source-envelope", disposition="excluded",
        reason="declared selected-work comparison, not whole-member coverage", targets=[],
        element_count=sum(isinstance(n.tag, str) for n in root.iter()) - count)
    return plan


def tei_body_identity(data: bytes, profile: dict) -> Expectations:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                             remove_blank_text=False, remove_comments=False, remove_pis=False)
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DTDs are unsupported; no external subset was loaded")
    if any(isinstance(node, etree._Entity) for node in root.iter()):
        raise ValueError("source entity references are unsupported; no expansion was attempted")
    if root.tag != f"{{{TEI}}}TEI":
        raise ValueError("tei-body-identity requires a TEI source root")
    bodies = root.xpath("/t:TEI/t:text/t:body", namespaces={"t": TEI})
    if len(bodies) != 1:
        raise ValueError(f"source must have exactly one readable TEI body, observed {len(bodies)}")
    selected = bodies[0]
    tree = root.getroottree()
    plan = Expectations(None, digest(data), profile,
        limitations=["Compares the complete readable TEI body by structural position, tag, attributes, exact text, and tails.",
                     "Excludes the source TEI header and outer document envelope; this is a bounded body comparison."])
    def account(location, feature, key):
        plan.coverage[location] = _entry(feature)
        plan.account(location, key)
    def visit(node, parent, position):
        key = f"{parent}/child[{position}]" if parent else "@scope"
        location = tree.getpath(node)
        tag = tag_name(node)
        attrs = dict(node.attrib) if isinstance(node.tag, str) else {}
        account(location, "xml-element:" + etree.QName(node).localname if isinstance(node.tag, str)
                else "xml-node:" + tag, key)
        for attr in attrs:
            account(location + "/@" + attr, "xml-attribute:" + attr, key)
        account(location + "/text", "xml-text", key)
        account(location + "/tail", "xml-tail", key)
        plan.carriers.append(Carrier(key, parent, position, tag, attrs,
                                     node.text or "", node.tail or "", location))
        for child_position, child in enumerate(node, 1):
            visit(child, key, child_position)
    visit(selected, None, 0)
    plan.coverage["@outside-selection"] = dict(
        feature="source-document-envelope", disposition="excluded",
        reason="TEI header and outer wrappers are outside this readable-body identity profile",
        targets=[], element_count=sum(isinstance(node.tag, str) for node in root.iter())
        - sum(isinstance(node.tag, str) for node in selected.iter()))
    return plan


def plain_text_lines(data: bytes, profile: dict) -> Expectations:
    if profile["encoding"] != "utf-8":
        raise ValueError("plain-text-lines currently requires an explicit UTF-8 profile")
    if profile["candidate_carrier"] != "tei:ab":
        raise ValueError("plain-text-lines supports only declared tei:ab line carriers")
    if profile["line_terminator_policy"] != "trim-one-final-empty-segment":
        raise ValueError("unsupported plain-text line-terminator policy")
    if not isinstance(profile["line_endings"], list) or not profile["line_endings"]:
        raise ValueError("line_endings must be a nonempty list")
    ending_map = {"CRLF": "\r\n", "LF": "\n", "CR": "\r"}
    if any(ending not in ending_map for ending in profile["line_endings"]):
        raise ValueError("line_endings entries must be CRLF, LF, or CR")
    exclusions = profile["candidate_attribute_exclusions"]
    if (not isinstance(exclusions, dict) or "xml:id" not in exclusions
            or any(not isinstance(name, str) or not isinstance(reason, str) or not reason.strip()
                   for name, reason in exclusions.items())):
        raise ValueError("declare reasons for candidate-only attributes, including generated xml:id")
    text = data.decode("utf-8", errors="strict")
    observed_endings = re.findall(r"\r\n|\r|\n", text)
    allowed_endings = {ending_map[name] for name in profile["line_endings"]}
    if any(ending not in allowed_endings for ending in observed_endings):
        raise ValueError("source contains a line ending not declared in the profile")
    if not text:
        raise ValueError("an empty plain-text source has no line carriers to compare")
    lines = re.split(r"\r\n|\r|\n", text)
    terminal_newline_present = text.endswith(("\r\n", "\n", "\r"))
    if terminal_newline_present:
        lines.pop()
    normalized_profile = dict(profile)
    normalized_profile["candidate_projection"] = "tei-ab-lines"
    normalized_profile["identity_mode"] = "structural-position"
    normalized_profile["candidate_attribute_exclusions"] = {
        XML_ID if name == "xml:id" else name: reason for name, reason in exclusions.items()
    }
    plan = Expectations(None, digest(data), normalized_profile,
        limitations=["Compares exact UTF-8 source line content and document order against TEI ab carriers.",
                     "Candidate divisions, headings, page markers, inline semantics, and wrapper relationships are not asserted by a plain-text source profile.",
                     "Physical line-ending bytes and terminal newline presence are not encoded by TEI ab carriers; candidate formatting whitespace outside ab carriers is not compared."])
    plan.claim_scopes.update({
        "omission": "declared plain-text line carriers",
        "duplication": "declared plain-text line carriers",
        "invention": "line carriers and nonwhitespace readable body text",
        "order": "document order of line carriers",
        "role": "tei:ab carrier tag only; higher TEI roles are unassessed",
        "attributes": "line-carrier attributes except declared candidate-only exclusions",
        "text": "exact decoded UTF-8 content of each line carrier",
    })
    plan.unsupported_claims.update({
        "attachment": "Plain text does not identify TEI parent or wrapper relationships.",
        "inline-tail": "Plain text does not identify inline TEI text boundaries.",
    })
    keys = []
    for position, line in enumerate(lines, 1):
        key = f"line-{position:06d}"
        keys.append(key)
        location = f"/line/{position:06d}"
        plan.coverage[location] = _entry("plain-text-line")
        plan.account(location, key)
        plan.carriers.append(Carrier(key, "@scope", position, f"{{{TEI}}}ab", {},
                                     line, "", location))
    if keys:
        plan.coverage["@strict-utf8-decode"] = _entry("source-encoding")
        plan.account("@strict-utf8-decode", keys[0])
        for index, ending in enumerate(observed_endings):
            location = f"/line-ending/{index + 1:06d}"
            plan.coverage[location] = dict(
                feature="plain-text-line-ending-bytes", disposition="excluded",
                reason="TEI ab carrier order checks line boundaries, but does not encode the physical line-ending sequence.",
                targets=[], source_sequence={"\r\n": "CRLF", "\n": "LF", "\r": "CR"}[ending])
    plan.coverage["@terminal-newline"] = dict(
        feature="source-terminal-newline", disposition="excluded",
        reason="A final source line terminator has no distinct representation in the TEI ab line projection.",
        targets=[], present=terminal_newline_present)
    plan.coverage["@candidate-unprojected-structure"] = dict(
        feature="candidate-structure-outside-ab-line-carriers", disposition="unsupported",
        reason="A plain-text source does not determine TEI hierarchy or semantic roles; those features need a richer reviewed profile.",
        targets=[])
    return plan


def prepare(source: bytes, profile: dict) -> Expectations:
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    adapter = profile.get("adapter")
    if adapter == "catechism-json":
        if set(profile) != {"adapter", "work_id"} or not isinstance(profile["work_id"], str) or not profile["work_id"]:
            raise ValueError("catechism profile requires only adapter and nonempty work_id")
        return catechism(source, profile)
    if adapter == "tei-body-identity":
        if set(profile) != {"adapter", "identity_mode"} or profile["identity_mode"] != "structural-position":
            raise ValueError("tei-body-identity requires structural-position identity mode")
        return tei_body_identity(source, profile)
    if adapter == "plain-text-lines":
        required = {"adapter", "encoding", "line_endings", "line_terminator_policy",
                    "candidate_carrier", "candidate_attribute_exclusions"}
        if set(profile) != required:
            raise ValueError("invalid plain-text-lines profile fields")
        return plain_text_lines(source, profile)
    if adapter == "xml-map":
        required = {"adapter", "source_root_id", "candidate_root_id", "id_prefix", "tags", "attributes", "excluded_attributes"}
        if not required <= profile.keys() or set(profile) - required - {"fixed_attributes", "candidate_attribute_exclusions", "native_link_attributes", "external_base"}:
            raise ValueError("invalid xml-map profile fields")
        for field in ("source_root_id", "candidate_root_id", "id_prefix"):
            if not isinstance(profile[field], str) or not profile[field]:
                raise ValueError(f"invalid profile {field}")
        for field in ("tags", "attributes", "excluded_attributes"):
            if not isinstance(profile[field], dict) or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() for k, v in profile[field].items()):
                raise ValueError(f"invalid profile {field}")
        exclusions = profile.get("candidate_attribute_exclusions", {})
        if not isinstance(exclusions, dict) or any(not isinstance(k,str) or not isinstance(v,str) or not v.strip() for k,v in exclusions.items()):
            raise ValueError("candidate attribute exclusions require explicit reasons")
        native_links = profile.get("native_link_attributes", [])
        if not isinstance(native_links, list) or any(not isinstance(v,str) for v in native_links):
            raise ValueError("invalid native_link_attributes")
        if "external_base" in profile and (not isinstance(profile["external_base"],str) or not profile["external_base"].startswith(("https://", "http://")) or "#" in profile["external_base"]):
            raise ValueError("external_base must be a declared HTTP(S) document URL")
        fixed = profile.get("fixed_attributes", {})
        if not isinstance(fixed, dict) or any(not isinstance(v, dict) or any(not isinstance(a, str) or not isinstance(b, str) for a,b in v.items()) for v in fixed.values()):
            raise ValueError("invalid fixed_attributes")
        return xml_mapping(source, profile)
    raise ValueError(f"unsupported source adapter: {adapter}")
