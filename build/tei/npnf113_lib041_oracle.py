"""Producer-independent retained-source oracle for LIB-041.

The oracle never imports the producer.  It reparses retained NPNF113 bytes,
interprets the source-to-TEI policy independently, and exact-checks the sealed
candidate and every evidence object.
"""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib041-npnf113-source-to-tei-oracle"
ORACLE_VERSION = "21"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "HE": "he"}
EXPECTED_AUTHORITY_SHA256 = {
    "reconstruction-profile": "3fccce199713eab2c6bf5b9640a2c9b7564fef3296aa99db5dfcb13a6850fced",
    "validation-policy": "212eeafebed85a071351a15e8ea2af9cefedb6d3e57148db5326645753e687ac",
    "candidate-package-schema": "3aea71ac3407e3ac9b82a6ba89e13430251de685f8efd2399e1bd5176f41a4e3",
    "source-accountability-schema": "1c164afea9ff8ee8e977d028c9577196de8abceab99854f1e3aa981a66e39dae",
    "tei-p5-xsd": "2d886fb9354567ab91d8a52286ef66276c6a932228ccbec04d7c4c9b6aa5a05f",
    "tei-p5-xml-xsd": "4f3a8348802f3bc968cbdd2a9d54a38a0549e5e4e7bc8d4338404f85f89568ba",
    "tei-p5-teix-xsd": "51ab8c0071f2abc375090829acadf7cb57c707fe17a993cdb2213e84932a6fac",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _verify_forbidden_oracle_imports(policy: Mapping[str, object]) -> None:
    """Fail closed when the executing oracle reaches producer code directly."""

    forbidden = policy.get("forbidden_oracle_imports")
    if not isinstance(forbidden, list) or any(
        not isinstance(name, str) or not name for name in forbidden
    ):
        raise ValueError("oracle forbidden-import policy is invalid")
    tree = ast.parse(Path(__file__).read_bytes(), filename=str(Path(__file__)))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for forbidden_name in forbidden:
        match = next(
            (
                name
                for name in sorted(imported)
                if name == forbidden_name
                or name.startswith(f"{forbidden_name}.")
                or name.endswith(f".{forbidden_name}")
                or f".{forbidden_name}." in name
            ),
            None,
        )
        if match is not None:
            raise ValueError(f"oracle forbidden producer import: {match}")


def _verify_runtime_closure(root: Path, closure: Mapping[str, object]) -> None:
    """Reject a validator running with a kernel imported from another root."""

    entries = closure.get("first_party")
    if not isinstance(entries, list) or not entries:
        raise ValueError("oracle import closure first-party entries are invalid")
    expected: dict[str, tuple[Path, str]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("oracle import closure entry is invalid")
        relative = entry.get("path")
        expected_sha256 = entry.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
        ):
            raise ValueError("oracle import closure entry binding is invalid")
        path = (root / relative).resolve(strict=True)
        try:
            relative_path = path.relative_to(root)
        except ValueError as exc:
            raise ValueError("oracle import closure escapes repository") from exc
        parts = relative_path.parts
        if not parts:
            raise ValueError("oracle import closure path is empty")
        if parts[-1] == "__init__.py":
            module_name = ".".join(parts[:-1])
        else:
            module_name = ".".join((*parts[:-1], Path(parts[-1]).stem))
        if not module_name or module_name in expected:
            raise ValueError("oracle import closure module names are invalid")
        expected[module_name] = (path, expected_sha256)

    required = {
        "ocd_kernel",
        "ocd_kernel.reconstruction",
        "ocd_kernel.reconstruction.contract",
    }
    for module_name, (expected_path, expected_sha256) in expected.items():
        module = sys.modules.get(module_name)
        if module is None:
            if module_name in required:
                raise ValueError(f"required runtime module {module_name!r} is not loaded")
            continue
        runtime_file = getattr(module, "__file__", None)
        if not runtime_file:
            raise ValueError(f"runtime module {module_name!r} has no source file")
        try:
            runtime_path = Path(str(runtime_file)).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ValueError(f"runtime module {module_name!r} source is not resolvable") from exc
        if not runtime_path.samefile(expected_path):
            raise ValueError(f"runtime module {module_name!r} loaded from the wrong root")
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None)
        if origin and origin not in {"built-in", "frozen"}:
            try:
                origin_path = Path(str(origin)).resolve(strict=True)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                raise ValueError(f"runtime module {module_name!r} origin is not resolvable") from exc
            if not origin_path.samefile(expected_path):
                raise ValueError(f"runtime module {module_name!r} origin drift")
        if _sha(runtime_path.read_bytes()) != expected_sha256:
            raise ValueError(f"runtime module {module_name!r} bytes drifted from import closure")


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            huge_tree=True,
        ),
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        if not isinstance(current.tag, str):
            break
        parent = current.getparent()
        if parent is None:
            break
        siblings = [
            child
            for child in parent
            if isinstance(child.tag, str) and child.tag == current.tag
        ]
        parts.append(f"{current.tag}[{siblings.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _target_tag(source: etree._Element) -> str:
    if source.tag in {"div2", "div3"}:
        return "div"
    if source.tag == "i":
        return "hi"
    if source.tag == "span":
        return "foreign" if source.get("lang") else "seg"
    if source.tag == "scripRef":
        return "ref"
    if source.tag == "scripCom":
        parent = source.getparent()
        return "p" if parent is not None and str(parent.tag).startswith("div") else "seg"
    if source.tag in {"note", "p", "pb"}:
        return str(source.tag)
    raise ValueError(f"oracle found unsupported retained source element {source.tag!r}")


def _expected_attrs(
    source: etree._Element, ordinal: int
) -> tuple[dict[str, str], list[dict[str, str]]]:
    tag = str(source.tag)
    source_id = source.get("id")
    result = {
        "xml:id": "npnf113-"
        + (_safe_id(source_id) if source_id else f"feature-{ordinal:05d}")
    }
    dispositions: list[dict[str, str]] = []
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-verbatim-in-accountability"
        if name == "id":
            destination, method = "@xml:id", "deterministic-npnf113-prefix"
        elif name == "title" and tag in {"div2", "div3"}:
            destination, method = "child::head[1]", "preserved-exactly"
        elif name == "n" and tag in {"div2", "div3", "note", "pb"}:
            result["n"], destination, method = value, "@n", "preserved-exactly"
        elif name == "type" and tag in {"div2", "div3"}:
            result["type"], destination, method = value, "@type", "preserved-exactly"
        elif name == "type" and tag == "scripCom":
            attribute = "rend" if _target_tag(source) == "p" else "type"
            result[attribute], destination, method = value, f"@{attribute}", "preserved-exactly"
        elif name == "class":
            result["rend"], destination, method = value, "@rend", "preserved-exactly"
        elif name == "place" and tag == "note":
            result["place"], destination, method = value, "@place", "preserved-exactly"
        elif name == "href" and tag == "pb":
            result["facs"], destination, method = value, "@facs", "preserved-exactly"
        elif name == "passage" and tag == "scripRef":
            result["cRef"], destination, method = value, "@cRef", "preserved-exactly"
        elif name == "osisRef" and tag == "scripRef":
            result["target"], destination, method = value, "@target", "preserved-exactly"
        elif name == "passage" and tag == "scripCom":
            result["n"], destination, method = value, "@n", "preserved-exactly"
        elif name == "lang" and tag == "span":
            if value not in LANGUAGE_MAP:
                raise ValueError(f"oracle found unsupported language code {value!r}")
            result["xml:lang"] = LANGUAGE_MAP[value]
            destination, method = "@xml:lang", "declared-language-code-map"
        dispositions.append(
            {
                "source_attribute": name,
                "source_value": value,
                "destination": destination,
                "method": method,
            }
        )
    if tag == "i":
        result["rend"] = "italic"
    elif tag == "scripRef":
        result["type"] = "scripture"
    elif tag == "scripCom":
        attribute = "rend" if _target_tag(source) == "p" else "type"
        result.setdefault(attribute, "scripture-commentary")
    return result, dispositions


def _observed_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key: value
        for key, value in node.attrib.items()
    }


def _census(nodes: list[etree._Element]) -> dict[str, object]:
    return {
        "elements": len(nodes),
        "attributes": sum(len(node.attrib) for node in nodes),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes": sum(node.tail is not None for node in nodes),
        "characters": sum(len((node.text or "") + (node.tail or "")) for node in nodes),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in (node.text or "") + (node.tail or ""))
            for node in nodes
        ),
        "tag_counts": dict(sorted(Counter(str(node.tag) for node in nodes).items())),
    }


def _comment_record(comment: etree._Comment, ordinal: int) -> dict[str, object]:
    ancestor = next(
        (item.get("id") for item in comment.iterancestors() if item.tag == "div1"),
        None,
    )
    return {
        "ordinal": ordinal,
        "ancestor_div1": ancestor,
        "text": comment.text or "",
        "text_sha256": _sha((comment.text or "").encode("utf-8")),
        "tail": comment.tail or "",
        "tail_sha256": _sha((comment.tail or "").encode("utf-8")),
    }


def _head_claims(tree: etree._ElementTree) -> dict[str, object]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("oracle found no retained ThML.head")
    result: dict[str, object] = {}
    expressions = {
        "dc_title": ".//DC.Title[not(@sub)]",
        "dc_author": ".//DC.Creator[@sub='Author'][@scheme='short-form']",
        "dc_editor": ".//DC.Creator[@sub='Editor'][@scheme='short-form']",
        "dc_publisher": ".//DC.Publisher",
        "dc_rights": ".//DC.Rights",
        "dc_language": ".//DC.Language",
        "electronic_status": ".//electronicEdInfo/status",
        "print_published": ".//printSourceInfo/published",
    }
    for key, expression in expressions.items():
        matches = head.xpath(expression)
        if len(matches) != 1:
            raise ValueError(f"oracle retained header claim {key} is not unique")
        result[key] = "".join(matches[0].itertext())
    result["head_xml_sha256"] = _sha(etree.tostring(head, encoding="UTF-8"))
    return result


def _header_observations(tree: etree._ElementTree) -> dict[str, object]:
    ns = {"tei": TEI}
    root = tree.getroot()
    header = root.find("tei:teiHeader", ns)
    if header is None:
        raise ValueError("candidate TEI has no teiHeader")
    return {
        "root_tag": etree.QName(root).localname,
        "root_namespace": etree.QName(root).namespace,
        "root_attributes": _observed_attrs(root),
        "header_child_tags": [etree.QName(item).localname for item in header],
        "title": header.xpath("string(tei:fileDesc/tei:titleStmt/tei:title)", namespaces=ns),
        "author": header.xpath("string(tei:fileDesc/tei:titleStmt/tei:author)", namespaces=ns),
        "editor": header.xpath("string(tei:fileDesc/tei:titleStmt/tei:editor)", namespaces=ns),
        "publisher": header.xpath("string(tei:fileDesc/tei:publicationStmt/tei:publisher)", namespaces=ns),
        "availability_status": header.xpath("string(tei:fileDesc/tei:publicationStmt/tei:availability/@status)", namespaces=ns),
        "availability": header.xpath("string(tei:fileDesc/tei:publicationStmt/tei:availability/tei:p)", namespaces=ns),
        "source_title": header.xpath("string(tei:fileDesc/tei:sourceDesc/tei:bibl/tei:title)", namespaces=ns),
        "source_publisher": header.xpath("string(tei:fileDesc/tei:sourceDesc/tei:bibl/tei:publisher)", namespaces=ns),
        "source_hash": header.xpath("string(tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='SHA-256'])", namespaces=ns),
        "project_desc": header.xpath("string(tei:encodingDesc/tei:projectDesc/tei:p)", namespaces=ns),
        "element_tags": [etree.QName(item).localname for item in header.iter() if isinstance(item.tag, str)],
    }


def _expected_header(claims: Mapping[str, object], source_hash: str) -> dict[str, object]:
    return {
        "root_tag": "TEI",
        "root_namespace": TEI,
        "root_attributes": {"xml:id": "lib041-npnf113-ten-work-candidate"},
        "header_child_tags": ["fileDesc", "encodingDesc"],
        "title": claims["dc_title"],
        "author": claims["dc_author"],
        "editor": claims["dc_editor"],
        "publisher": claims["dc_publisher"],
        "availability_status": "restricted",
        "availability": (
            f"Retained DC.Rights: {claims['dc_rights']}. CCEL permits parsing "
            "the retained ThML and asks for attribution; this candidate is "
            "nonaccepted and publication is not ready."
        ),
        "source_title": claims["dc_title"],
        "source_publisher": claims["print_published"],
        "source_hash": source_hash,
        "project_desc": (
            "Faithful projection of the ten assigned NPNF113 work roots; "
            "source root tails outside each selected subtree are excluded and accounted."
        ),
        "element_tags": [
            "teiHeader", "fileDesc", "titleStmt", "title", "author", "editor",
            "publicationStmt", "publisher", "availability", "p", "sourceDesc",
            "bibl", "title", "publisher", "idno", "encodingDesc", "projectDesc", "p",
        ],
    }


def _division_accounting(
    body: etree._Element, selected_ids: set[str], apparatus_ids: set[str]
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    top_divisions = [item for item in body if isinstance(item.tag, str) and item.tag == "div1"]
    for top_ordinal, top in enumerate(top_divisions, start=1):
        top_id = str(top.get("id"))
        records.append(
            {
                "level": "div1",
                "ordinal": top_ordinal,
                "source_xml_id": top_id,
                "title": top.get("title", ""),
                "element_count": len([node for node in top.iter() if isinstance(node.tag, str)]),
                "text_sha256": _sha("".join(top.itertext()).encode("utf-8")),
                "disposition": "parent-container-partially-selected" if top_id in {"iii", "iv", "v"} else "outside-assigned-work-scope",
            }
        )
        children = [item for item in top if isinstance(item.tag, str) and item.tag == "div2"]
        for child_ordinal, child in enumerate(children, start=1):
            child_id = str(child.get("id"))
            records.append(
                {
                    "level": "div2",
                    "parent_div1_id": top_id,
                    "ordinal": child_ordinal,
                    "source_xml_id": child_id,
                    "title": child.get("title", ""),
                    "element_count": len([node for node in child.iter() if isinstance(node.tag, str)]),
                    "text_sha256": _sha("".join(child.itertext()).encode("utf-8")),
                    "disposition": "assigned-work-represented" if child_id in selected_ids else "shared-title-or-preface-accounted-excluded" if child_id in apparatus_ids else "index-or-other-work-outside-ticket",
                }
            )
    return records


def _expected_readme(claims: Mapping[str, object], member: Mapping[str, object]) -> bytes:
    return (
        "# LIB-041 retained-source attribution\n\n"
        f"Source: {claims['dc_title']}\n\n"
        "Retained member: `raw/ccel/npnf1/npnf113.xml`\n\n"
        f"SHA-256: `{member['sha256']}` ({member['bytes']} bytes)\n\n"
        "This package faithfully projects the ten assigned work roots in retained order. "
        "The title/preface apparatus, document header, shell, comments, root-boundary tails, "
        "front matter, and indexes are explicitly accounted in `source-accountability.json`.\n\n"
        "Sourced via CCEL.org. CCEL permits parsing its ThML/XML files and asks for attribution; "
        "do not sell CCEL files or derivatives of CCEL formatting. The retained header states "
        "Public Domain. Human textual acceptance is absent and publication is not ready.\n"
    ).encode("utf-8")


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    for authority_id, expected_sha256 in EXPECTED_AUTHORITY_SHA256.items():
        observed_sha256 = _sha(source_manifest.authority_path(authority_id).read_bytes())
        if observed_sha256 != expected_sha256:
            raise ValueError(
                f"oracle pinned authority drifted: {authority_id}"
            )
    observed_manifest = json.loads(candidate.member_bytes("manifest.json"))
    expected_manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_manifest": {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "converter": dict(source_manifest.record["converter"]),
        "package_schema": dict(source_manifest.record["package_schema"]),
        "members": observed_manifest.get("members"),
    }
    if observed_manifest != expected_manifest:
        raise ValueError("candidate manifest authority bindings drifted")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    schema_bytes = source_manifest.authority_path("candidate-package-schema").read_bytes()
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    accountability_schema_bytes = source_manifest.authority_path("source-accountability-schema").read_bytes()
    permission_bytes = source_manifest.authority_path("ccel-permission-evidence").read_bytes()
    closure_bytes = source_manifest.authority_path("oracle-import-closure").read_bytes()
    profile = json.loads(profile_bytes)
    policy = json.loads(policy_bytes)
    closure = json.loads(closure_bytes)
    if not isinstance(closure, Mapping):
        raise ValueError("oracle import closure is invalid")
    _verify_runtime_closure(source_manifest.repository_root, closure)
    _verify_forbidden_oracle_imports(policy)
    member = profile["source_member"]
    source_path = source_manifest.authority_path("npnf113-retained-xml")
    source_content = source_path.read_bytes()
    if len(source_content) != member["bytes"] or _sha(source_content) != member["sha256"]:
        raise ValueError("oracle retained source identity mismatch")
    source_tree = _parse(source_path)
    if source_tree.docinfo.doctype != profile["document"]["doctype"]:
        raise ValueError("oracle retained doctype mismatch")
    source_root = source_tree.getroot()
    source_body = source_root.find("ThML.body")
    if source_body is None:
        raise ValueError("oracle retained body missing")
    assigned = [(str(root_id), str(work_id)) for root_id, work_id in profile["assigned"]]
    selected = []
    for root_id, work_id in assigned:
        matches = source_body.xpath(f".//*[@id='{root_id}']")
        if len(matches) != 1 or matches[0].tag != "div2":
            raise ValueError(f"oracle assigned root {root_id} is not one div2")
        selected.append((root_id, work_id, matches[0]))
    document_order = [node.get("id") for node in source_body.iter("div2") if node.get("id") in {item[0] for item in assigned}]
    if document_order != [item[0] for item in assigned]:
        raise ValueError("oracle assigned root order mismatch")
    source_nodes = [node for _, _, root in selected for node in root.iter() if isinstance(node.tag, str)]
    observed_census = _census(source_nodes)
    expected_profile_census = {
        "elements": profile["expected"]["retained_elements"],
        "attributes": profile["expected"]["retained_attributes"],
        "text_nodes": profile["expected"]["retained_text_nodes"],
        "tail_nodes": profile["expected"]["retained_tail_nodes"],
        "characters": profile["expected"]["retained_characters_including_root_tails"],
        "non_ascii_characters": profile["expected"]["non_ascii_characters_including_root_tails"],
        "tag_counts": profile["expected"]["tag_counts"],
    }
    if observed_census != expected_profile_census:
        raise ValueError("oracle source census/profile mismatch")
    root_tail_records = [
        {
            "root_id": root_id,
            "tail": root.tail or "",
            "tail_sha256": _sha((root.tail or "").encode("utf-8")),
            "characters": len(root.tail or ""),
            "disposition": "excluded-selected-root-boundary",
        }
        for root_id, _, root in selected
    ]
    if sum(item["characters"] for item in root_tail_records) != profile["expected"]["excluded_root_tail_characters"]:
        raise ValueError("oracle root-tail boundary mismatch")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    candidate_tree = etree.ElementTree(
        etree.fromstring(
            tei_bytes,
            parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
        )
    )
    xsd = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not xsd.validate(candidate_tree):
        error = xsd.error_log.last_error
        raise ValueError(f"TEI P5 XSD failure: {error}")
    claims = _head_claims(source_tree)
    if _header_observations(candidate_tree) != _expected_header(claims, member["sha256"]):
        raise ValueError("candidate TEI header or namespace shell drifted")
    ns = {"tei": TEI}
    candidate_body = candidate_tree.getroot().find("tei:text/tei:body", ns)
    if candidate_body is None or candidate_body.get(XML_ID) != "lib041-npnf113-assigned-body":
        raise ValueError("candidate body identity drifted")
    candidate_by_id: dict[str, etree._Element] = {}
    for node in candidate_body.iter():
        if not isinstance(node.tag, str):
            raise ValueError("candidate body contains a non-element node")
        xml_id = node.get(XML_ID)
        if xml_id:
            if xml_id in candidate_by_id:
                raise ValueError("candidate contains duplicate xml:id")
            candidate_by_id[xml_id] = node

    expected_crosswalk: list[dict[str, object]] = []
    selected_node_lists = [
        (root_id, work_id, selected_root, [node for node in selected_root.iter() if isinstance(node.tag, str)])
        for root_id, work_id, selected_root in selected
    ]
    feature_ordinals: dict[etree._Element, int] = {}
    ordinal_cursor = 0
    for _, _, _, nodes in selected_node_lists:
        for node in nodes:
            ordinal_cursor += 1
            feature_ordinals[node] = ordinal_cursor
    source_cursor = 0
    for root_id, work_id, selected_root, selected_root_nodes in selected_node_lists:
        for source_node in selected_root_nodes:
            source_cursor += 1
            feature_id = f"lib041-feature-{source_cursor:05d}"
            attrs, dispositions = _expected_attrs(source_node, source_cursor)
            parent_source = source_node.getparent()
            is_root = source_node is selected_root
            parent_feature_id = None
            if not is_root:
                parent_ordinal = feature_ordinals[parent_source]
                parent_feature_id = f"lib041-feature-{parent_ordinal:05d}"
            if is_root:
                attrs["corresp"] = f"#npnf113:{root_id}:{work_id}"
            tei_id = attrs["xml:id"]
            target = candidate_by_id.get(tei_id)
            if target is None:
                raise ValueError(f"candidate omitted source feature {source_cursor}")
            if etree.QName(target).namespace != TEI or etree.QName(target).localname != _target_tag(source_node):
                raise ValueError(f"candidate tag drift at source feature {source_cursor}")
            if _observed_attrs(target) != attrs:
                raise ValueError(f"candidate attribute drift at source feature {source_cursor}")
            if (target.text or "") != (source_node.text or ""):
                raise ValueError(f"candidate direct text drift at source feature {source_cursor}")
            expected_tail = "" if is_root else source_node.tail or ""
            if (target.tail or "") != expected_tail:
                raise ValueError(f"candidate tail drift at source feature {source_cursor}")
            target_parent = target.getparent()
            expected_parent_id = "lib041-npnf113-assigned-body" if is_root else _expected_attrs(parent_source, feature_ordinals[parent_source])[0]["xml:id"]
            if target_parent is None or target_parent.get(XML_ID) != expected_parent_id:
                raise ValueError(f"candidate parent drift at source feature {source_cursor}")
            element_siblings = [item for item in target_parent if isinstance(item.tag, str)]
            child_ordinal = element_siblings.index(target) + 1
            source_title = source_node.get("title") if source_node.tag in {"div2", "div3"} else None
            if source_title is not None:
                heads = [item for item in target if etree.QName(item).localname == "head"]
                if len(heads) != 1 or heads[0].text != source_title or heads[0].attrib or len(heads[0]):
                    raise ValueError(f"candidate title-head drift at source feature {source_cursor}")
            expected_crosswalk.append(
                {
                    "ordinal": source_cursor,
                    "feature_id": feature_id,
                    "work_id": work_id,
                    "root_id": root_id,
                    "source_selector": _selector(source_node),
                    "source_tag": source_node.tag,
                    "source_xml_id": source_node.get("id"),
                    "source_attributes": dict(source_node.attrib),
                    "source_text_present": source_node.text is not None,
                    "source_text_sha256": _sha((source_node.text or "").encode("utf-8")),
                    "source_tail_present": source_node.tail is not None,
                    "source_tail_sha256": _sha((source_node.tail or "").encode("utf-8")),
                    "tail_disposition": "excluded-selected-root-boundary" if is_root else "represented",
                    "tei_tag": etree.QName(target).localname,
                    "tei_xml_id": tei_id,
                    "tei_parent_id": expected_parent_id,
                    "tei_child_ordinal": child_ordinal,
                    "tei_attributes": attrs,
                    "attribute_dispositions": dispositions,
                    "tei_selector": f"#{tei_id}",
                    "parent_feature_id": parent_feature_id,
                    "source_title_head": source_title,
                    "disposition": "represented",
                }
            )
    if source_cursor != profile["expected"]["retained_elements"]:
        raise ValueError("oracle feature walk incomplete")
    mapped_ids = {row["tei_xml_id"] for row in expected_crosswalk}
    if set(candidate_by_id) != mapped_ids | {"lib041-npnf113-assigned-body"}:
        raise ValueError("candidate body contains invented or duplicate mapped elements")
    body_elements = [item for item in candidate_body.iter() if item is not candidate_body and isinstance(item.tag, str)]
    title_count = sum(row["source_title_head"] is not None for row in expected_crosswalk)
    if len(body_elements) != len(expected_crosswalk) + title_count:
        raise ValueError("candidate body contains unaccounted elements")

    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    accountability_schema = json.loads(accountability_schema_bytes)
    errors = sorted(Draft202012Validator(accountability_schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"candidate accountability schema failure: {errors[0].message}")
    pre_comments = source_tree.xpath("/comment()")
    embedded_comments = [item for item in source_tree.xpath("//comment()") if item.getparent() is not None]
    division_records = _division_accounting(
        source_body,
        {root_id for root_id, _ in assigned},
        set(profile["document"]["shared_apparatus_divisions"]),
    )
    complete_nodes = [node for node in source_root.iter() if isinstance(node.tag, str)]
    head_node = source_root.find("ThML.head")
    body_nodes = [node for node in source_body.iter() if isinstance(node.tag, str)]
    expected_accountability = {
        "contract": "ocd-lib041-npnf113-source-accountability-v1",
        "profile_id": profile["profile_id"],
        "source_member": {**member, "disposition": "included retained member with ten exact assigned div2 subtrees"},
        "document_accounting": {
            "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
            "doctype": source_tree.docinfo.doctype,
            "root_tag": source_root.tag,
            "root_attributes": dict(source_root.attrib),
            "root_namespace_declarations": dict(source_root.nsmap),
            "pre_root_comments": [_comment_record(item, ordinal) for ordinal, item in enumerate(pre_comments, start=1)],
            "embedded_comments": [_comment_record(item, ordinal) for ordinal, item in enumerate(embedded_comments, start=1)],
            "assigned_comment_count": 0,
            "assigned_processing_instruction_count": 0,
            "thml_head_xml_sha256": claims["head_xml_sha256"],
            "header_claims": claims,
        },
        "scope_accounting": {
            "selected_root_ids": [root_id for root_id, _ in assigned],
            "selected_work_ids": [work_id for _, work_id in assigned],
            "root_tail_exclusions": root_tail_records,
            "shared_apparatus_divisions": list(profile["document"]["shared_apparatus_divisions"]),
            "shared_apparatus_disposition": "metadata and text identities retained in division_accounting; outside exact assigned work roots",
            "remaining_source_disposition": "front matter, editorial essay, indexes, and unassigned containers are fully counted and outside this ticket's ten work roots",
        },
        "source_census": {
            "complete_document": _census(complete_nodes),
            "thml_head": _census([node for node in head_node.iter() if isinstance(node.tag, str)]),
            "thml_body": _census(body_nodes),
            "assigned_retained_including_root_tails": observed_census,
            "projected": {
                **{key: observed_census[key] for key in ("elements", "attributes", "text_nodes", "tail_nodes", "non_ascii_characters", "tag_counts")},
                "characters": profile["expected"]["projected_characters"],
                "root_tail_characters_excluded": profile["expected"]["excluded_root_tail_characters"],
            },
        },
        "assigned_work_count": 10,
        "feature_count": len(expected_crosswalk),
        "attribute_count": observed_census["attributes"],
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "division_accounting": division_records,
        "crosswalk": expected_crosswalk,
    }
    if accountability != expected_accountability:
        raise ValueError("candidate accountability differs from independent retained-source reconstruction")

    apparatus_ids = set(profile["document"]["shared_apparatus_divisions"])
    apparatus = [
        {
            "source_xml_id": item["source_xml_id"],
            "title": item["title"],
            "text_sha256": item["text_sha256"],
            "disposition": item["disposition"],
        }
        for item in division_records
        if item["level"] == "div2" and item["source_xml_id"] in apparatus_ids
    ]
    work_titles = profile["work_titles"]
    works = [
        {
            "ordinal": ordinal,
            "root_id": root_id,
            "work_id": work_id,
            "catalog_title": work_titles[work_id],
            "retained_division_title": selected_root.get("title", ""),
            "candidate_verification": "candidate_verified",
            "human_review": "human_required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        }
        for ordinal, (root_id, work_id, selected_root) in enumerate(selected, start=1)
    ]
    expected_provenance = {
        "contract": "ocd-lib041-npnf113-provenance-v1",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source_member": member,
        "retained_header_claims": claims,
        "shared_apparatus": apparatus,
        "works": works,
        "legacy_config_disposition": "route and catalog evidence only; contributor, date, title, rights, and edition claims are not reconstruction authority",
        "rights": {
            "retained_dc_rights": claims["dc_rights"],
            "permission_evidence_path": "docs/sources/ccel-permission.md",
            "permission_evidence_sha256": _sha(permission_bytes),
            "attribution": "sourced via CCEL.org",
            "publication": "not_ready",
        },
        "canonical_data_written": False,
    }
    if json.loads(candidate.member_bytes("provenance.json")) != expected_provenance:
        raise ValueError("candidate provenance metadata or rights drifted")
    expected_unresolved = [
        {
            "id": "lib041-print-collation-not-performed",
            "scope": "retained NPNF113 electronic witness",
            "status": "unresolved",
            "question": "Does the retained CCEL witness differ substantively from the named print edition?",
            "evidence": "The candidate is byte-bound to retained NPNF113 XML; no print collation was performed.",
        },
        {
            "id": "lib041-human-textual-acceptance",
            "scope": "ten assigned works",
            "status": "unresolved",
            "question": "Will the project maintainer accept the exact candidate?",
            "evidence": "Technical verification is separate; all ten works remain human_required and not_accepted.",
        },
        {
            "id": "lib041-publication-authorization",
            "scope": "candidate package",
            "status": "unresolved",
            "question": "Has publication been authorized?",
            "evidence": "No publication authorization exists; publication remains not_ready.",
        },
    ]
    unresolved_lines = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()]
    if unresolved_lines != expected_unresolved:
        raise ValueError("candidate unresolved evidence drifted")
    if candidate.member_bytes("README.source.md") != _expected_readme(claims, member):
        raise ValueError("candidate attribution README drifted")
    if set(policy["required_member_names"]) != set(candidate.member_names) or policy["candidate_status"] != "nonaccepted" or policy["publication_state"] != "not_ready":
        raise ValueError("candidate validation policy drifted")
    closure = json.loads(closure_bytes)
    if closure.get("contract") != "ocd-lib041-oracle-import-closure-v1" or closure.get("oracle_sha256") != _sha(Path(__file__).read_bytes()):
        raise ValueError("oracle import closure drifted")
    validator = source_manifest.record["validator"]
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": validator["import_closure_sha256"],
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(schema_bytes),
        "source_sha256": _sha(source_content),
        "xsd_sha256": _sha(xsd_path.read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
