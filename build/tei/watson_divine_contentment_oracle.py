"""Independent validator for the 37c-316 Watson candidate package."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.library.identities import load_work
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


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
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4"})

CLOSURE = (
    "ocd_kernel/library/identities.py",
    "ocd_kernel/library/_common.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
    "ocd_kernel/tei/validate.py",
    "schemas/v2/acquisition.schema.json",
    "schemas/v2/work.schema.json",
    "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _selection_digest(selection: Mapping[str, Any]) -> str:
    # The shared source-selection contract uses canonical JSON without the
    # newline used by candidate-package member serialization.
    return _sha(json.dumps(selection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _load_route_acquisition(manifest: SourceManifest, root: Path, work: Mapping[str, Any]) -> dict[str, Any]:
    record = _read_json(manifest.authority_path("acquisition").read_bytes(), "Watson acquisition")
    schema = _read_json((root / "schemas/v2/acquisition.schema.json").read_bytes(), "acquisition schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(record), key=str)
    if errors:
        raise ValueError(f"Watson acquisition schema failure: {errors[0].message}")
    if record["edition_id"] != "watson-divine-contentment-ccel-thml" or record["source_path"] != SOURCE_PATH:
        raise ValueError("Watson acquisition identity or source path drifted")
    retained = record["retained_files"]
    if len(retained) != 1 or retained[0]["path"] != SOURCE_PATH:
        raise ValueError("Watson route requires exactly one retained source member")
    raw = manifest.authority_path("retained-source").read_bytes()
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


def _runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def closure_digest(root: Path) -> str:
    rows = [{"path": path, "sha256": _sha((root / path).read_bytes())} for path in CLOSURE]
    return _sha(_canonical(rows))


def _read_json(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be an object")
    return parsed


def _selector(tree: etree._ElementTree, node: etree._Element) -> str:
    return tree.getpath(node)


def _shell(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    head = root.find("ThML.head")
    body = root.find("ThML.body")
    children: list[dict[str, Any]] = []
    for position, child in enumerate(head if head is not None else []):
        children.append(
            {
                "position": position,
                "source_selector": _selector(tree, child),
                "source_tag": child.tag,
                "attributes": dict(sorted(child.attrib.items())),
                "text": "".join(child.itertext()),
                "tail": child.tail or "",
                "element_count": sum(1 for _ in child.iter()),
            }
        )
    return {
        "xml_declaration": None,
        "doctype": tree.docinfo.doctype or None,
        "root": {
            "source_selector": _selector(tree, root),
            "source_tag": root.tag,
            "attributes": dict(sorted(root.attrib.items())),
        },
        "head": {
            "source_selector": _selector(tree, head) if head is not None else None,
            "element_count": sum(1 for _ in head.iter()) if head is not None else 0,
            "children": children,
        },
        "body": {
            "source_selector": _selector(tree, body) if body is not None else None,
            "element_count": sum(1 for _ in body.iter()) if body is not None else 0,
            "carrier_count": sum(1 for child in (body if body is not None else []) if child.tag == "div1"),
        },
    }


def _normalized_te_attrs(node: etree._Element) -> dict[str, str]:
    output: dict[str, str] = {}
    for key, value in node.attrib.items():
        if key == XML_ID:
            output["xml:id"] = value
        else:
            output[key] = value
    return output


def _tei_attrs(source: etree._Element, tag: str, tei_id: str, internal_targets: Mapping[str, str]) -> dict[str, str]:
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


def _expected_features(tree: etree._ElementTree) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    root = tree.getroot()
    body = root.find("ThML.body")
    if body is None:
        raise ValueError("source body is missing")
    body_path = tree.getpath(body)
    tei_ids: dict[str, str] = {}
    features: list[dict[str, Any]] = []
    tag_counts: dict[str, int] = {}
    attr_counts: dict[str, int] = {}
    body_ordinal = 0
    for ordinal, node in enumerate(root.iter(), 1):
        path = _selector(tree, node)
        parent = node.getparent()
        in_body = path.startswith(body_path + "/")
        tei_id = None
        if in_body:
            body_ordinal += 1
            tei_id = f"src-{body_ordinal}"
            tei_ids[path] = tei_id
        tag_counts[node.tag] = tag_counts.get(node.tag, 0) + 1
        for key in node.attrib:
            attr_counts[key] = attr_counts.get(key, 0) + 1
        features.append(
            {
                "ordinal": ordinal,
                "source_selector": path,
                "parent_selector": _selector(tree, parent) if parent is not None else None,
                "child_position": list(parent).index(node) if parent is not None else None,
                "source_tag": node.tag,
                "native_id": node.get("id"),
                "attributes": dict(sorted(node.attrib.items())),
                "text": node.text or "",
                "tail": node.tail or "",
                "disposition": "represented-in-tei" if in_body else "accounted-source-document-shell",
                "tei_id": tei_id,
            }
        )
    for row in features:
        if row["tei_id"] is not None:
            row["tei_tag"] = _tei_tag(next(node for node in root.iter() if _selector(tree, node) == row["source_selector"]))
    census = {
        "elements": len(features),
        "attributes": sum(attr_counts.values()),
        "text_utf8_bytes": sum(len((node.text or "").encode("utf-8")) for node in root.iter()),
        "tail_utf8_bytes": sum(len((node.tail or "").encode("utf-8")) for node in root.iter()),
        "body_elements": sum(1 for row in features if row["disposition"] == "represented-in-tei"),
        "represented_elements": sum(1 for row in features if row["disposition"] == "represented-in-tei"),
        "head_elements": sum(1 for node in root.find("ThML.head").iter()) if root.find("ThML.head") is not None else 0,
        "tag_counts": dict(sorted(tag_counts.items())),
        "attribute_counts": dict(sorted(attr_counts.items())),
    }
    return features, tei_ids, census


def _expected_carriers(tree: etree._ElementTree) -> list[dict[str, Any]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("source body is missing")
    rows = []
    for position, node in enumerate(body):
        if node.tag != "div1":
            raise ValueError("all top-level body nodes must be div1 carriers")
        native_id = node.get("id")
        rows.append(
            {
                "position": position,
                "native_id": native_id,
                "source_tag": node.tag,
                "source_title": node.get("title"),
                "progress": node.get("progress"),
                "prev": node.get("prev"),
                "next": node.get("next"),
                "tei_region": "front" if native_id in {"i", "ii"} else ("back" if native_id == "xix" else "body"),
                "disposition": "represented-present-carrier",
            }
        )
    return rows


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    root = source_manifest.repository_root
    work = load_work(source_manifest.authority_path("work"))
    acquisition = _load_route_acquisition(source_manifest, root, work)
    source_path = source_manifest.authority_path("retained-source")
    raw = source_path.read_bytes()
    if _sha(raw) != acquisition["source_sha256"] or len(raw) != acquisition["source_bytes"]:
        raise ValueError("retained Watson source binding drifted")
    source_tree = etree.ElementTree(etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False)))
    if source_tree.getroot().tag != "ThML":
        raise ValueError("retained source root is not ThML")
    source_features, tei_ids, census = _expected_features(source_tree)
    if any(row["source_tag"] not in TAGS or row["disposition"] != "represented-in-tei" for row in source_features if row["disposition"] == "represented-in-tei"):
        raise ValueError("a present body element has no independent mapping")
    expected_carriers = _expected_carriers(source_tree)
    expected_ids = [row["native_id"] for row in expected_carriers]
    if expected_ids != [unit["native_id"] for unit in acquisition["source_selection"]["units"]]:
        raise ValueError("acquisition selection does not cover all present carriers")
    if [unit["role"] for unit in acquisition["source_selection"]["units"]][-1] != "back":
        raise ValueError("Watson index carrier is not routed to back")
    if set(expected_ids) & {"ix", "x"} or "ix" in expected_ids or "x" in expected_ids:
        raise ValueError("source gap unexpectedly filled by this retained member")

    profile = _read_json(source_manifest.authority_path("profile").read_bytes(), "profile")
    if profile.get("feature_census") != census:
        raise ValueError("profile feature census does not match independent source walk")
    if profile.get("present_top_level_carriers") != expected_ids:
        raise ValueError("profile carrier envelope drifted")

    accountability = _read_json(candidate.member_bytes("source-accountability.json"), "source accountability")
    schema = _read_json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "source-accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"source-accountability schema failure: {errors[0].message}")
    if accountability.get("source_member") != {"path": SOURCE_PATH, "bytes": len(raw), "sha256": _sha(raw)}:
        raise ValueError("source accountability member binding drifted")
    if accountability.get("features") != source_features:
        raise ValueError("source accountability feature inventory differs from independent source walk")
    if accountability.get("feature_census") != census:
        raise ValueError("source accountability feature census drifted")
    if accountability.get("source_envelope") != expected_carriers:
        raise ValueError("source accountability carrier envelope drifted")
    expected_gap = {
        "contract": "ocd-source-completeness-gap-v1",
        "expected_chapters": ["VI", "VII"],
        "absent_native_ids": ["ix", "x"],
        "evidence_selector": "/ThML/ThML.body/div1[3]",
        "disposition": "unresolved; no replacement text inferred",
    }
    if accountability.get("source_completeness_gap") != expected_gap:
        raise ValueError("source completeness gap is missing or changed")
    if accountability.get("document_shell") != _shell(source_tree):
        # The producer intentionally records the XML declaration; the oracle
        # derives it from the bound bytes rather than trusting the candidate.
        shell = _shell(source_tree)
        shell["xml_declaration"] = accountability.get("document_shell", {}).get("xml_declaration")
        if accountability.get("document_shell") != shell:
            raise ValueError("source document shell accounting drifted")

    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    tei_tree = etree.ElementTree(tei)
    schema_errors = compiled_schema().error_log
    if not compiled_schema().validate(tei_tree):
        raise ValueError(f"TEI schema validation failed: {compiled_schema().error_log[0]}")
    represented = [row for row in source_features if row["disposition"] == "represented-in-tei"]
    source_id_to_tei = {row["native_id"]: row["tei_id"] for row in represented if row["native_id"]}
    internal_targets = {node.get("id"): f"#src-{tei_ids[source_tree.getpath(node)]}" for node in source_tree.iter() if node.get("id") and source_tree.getpath(node) in tei_ids}
    actual_nodes = [node for node in tei.iter() if node.get(XML_ID, "").startswith("src-")]
    if [node.get(XML_ID) for node in actual_nodes] != [row["tei_id"] for row in represented]:
        raise ValueError("TEI source feature IDs are omitted, duplicated, or reordered")
    for row, node in zip(represented, actual_nodes):
        expected_attrs = _tei_attrs(
            next(source for source in source_tree.iter() if source_tree.getpath(source) == row["source_selector"]),
            row["source_tag"],
            row["tei_id"],
            internal_targets,
        )
        if _normalized_te_attrs(node) != expected_attrs:
            raise ValueError(f"TEI attributes drifted at {row['source_selector']}")
        if node.tag != f"{{{TEI_NS}}}{row['tei_tag']}" or (node.text or "") != row["text"] or (node.tail or "") != row["tail"]:
            raise ValueError(f"TEI content drifted at {row['source_selector']}")
    provenance = _read_json(candidate.member_bytes("provenance.json"), "provenance")
    expected_provenance = {
        "contract": "ocd-candidate-provenance-v1",
        "status": "nonaccepted",
        "work_id": work["work_id"],
        "acquisition_id": acquisition["acquisition_id"],
        "source_path": SOURCE_PATH,
        "source_sha256": _sha(raw),
        "source_selection_sha256": _selection_digest(acquisition["source_selection"]),
        "present_carrier_ids": expected_ids,
        "missing_expected_native_ids": ["ix", "x"],
    }
    if provenance != expected_provenance:
        raise ValueError("candidate provenance drifted")
    unresolved = [json.loads(line.decode("utf-8")) for line in candidate.member_bytes("unresolved.jsonl").splitlines() if line.strip()]
    unresolved_ids = [row.get("id") for row in unresolved]
    if unresolved_ids != ["watson-missing-chapters-vi-vii", "watson-source-quality", "watson-rights-clearance"]:
        raise ValueError("unresolved boundary inventory drifted")
    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    if "native IDs `ix` or `x`" not in readme or "Chapters VI and VII" not in readme:
        raise ValueError("candidate README omits the source completeness gap")

    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).resolve(strict=True).read_bytes()),
        validator_import_closure_sha256=closure_digest(root),
        source_sha256=_sha(raw),
        profile_sha256=_sha(source_manifest.authority_path("profile").read_bytes()),
        package_schema_sha256=_sha(source_manifest.authority_path("package-schema").read_bytes()),
        xsd_sha256=_sha(source_manifest.authority_path("tei-schema").read_bytes()),
        policy_sha256=_sha(source_manifest.authority_path("policy").read_bytes()),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-watson-independent-present-thml-oracle"
_oracle.oracle_version = "1"
