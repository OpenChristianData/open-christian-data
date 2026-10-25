"""Independent retained-source oracle for the complete Schaff volume."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import sys

from jsonschema import Draft202012Validator
from lxml import etree

from build.tei.lib029_oracle import _closure_paths, _expected_body, _retained_members, _same_tree
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib029-complete-volume-source-oracle"
ORACLE_VERSION = "1"
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
FRONT = ("i", "ii")
BODY = ("iii", "iv", "v", "vi", "vii", "viii", "ix", "x")
BACK = ("xi", "xii")
LATE_HEADINGS = {
    "i-p1.2", "i-p1.3", "i-p1.4", "i-p2.1", "i-p2.2", "i-p2.3",
    "i-p5.1", "i-p6.1", "i-p6.4", "iii-p4.1", "iii-p8.1",
    "iii-p8.3", "iii-p8.4", "xi-p842.1",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _import_closure_sha256(repository_root: Path) -> str:
    implementation = Path(__file__).resolve(strict=True)
    syntax = ast.parse(implementation.read_text(encoding="utf-8"))
    forbidden = ("build.tei.lib029_reconstruction", "build.tei.lib029_complete_volume")
    for node in ast.walk(syntax):
        if isinstance(node, ast.ImportFrom) and node.module and any(node.module == name or node.module.startswith(name + ".") for name in forbidden):
            raise ValueError("Schaff oracle imports its producer")
        if isinstance(node, ast.Import) and any(any(alias.name == name or alias.name.startswith(name + ".") for name in forbidden) for alias in node.names):
            raise ValueError("Schaff oracle imports its producer")
    policy = json.loads((repository_root / "sources/structured-text/creeds-of-christendom-vol-1/lib029.validation-policy.json").read_bytes())
    paths = sorted({implementation, *_closure_paths(repository_root, policy)}, key=lambda path: path.as_posix())
    records = [{"path": path.relative_to(repository_root).as_posix(), "sha256": _sha(path.read_bytes())} for path in paths]
    return _sha((json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    repository_root = source_manifest.repository_root
    expected_binding = {
        "path": source_manifest.path.relative_to(repository_root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_manifest") != expected_binding:
        raise ValueError("Schaff candidate source or status binding drifted")
    if candidate.manifest.get("converter") != source_manifest.record["converter"]:
        raise ValueError("Schaff converter binding drifted")
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("selected_div1_ids") != [*FRONT, *BODY, *BACK]:
        raise ValueError("Schaff complete source scope drifted")
    source_members = _retained_members(source_manifest, profile)
    expected_body, expected_rows = _expected_body(source_manifest, profile, source_members)
    expected_work = expected_body[0]
    source_divisions = list(expected_work)[1:]
    if len(source_divisions) != 12:
        raise ValueError("Schaff source has no complete twelve-division envelope")
    expected_front = etree.Element(f"{{{NS}}}front", {XML_ID: "lib029-front"})
    expected_back = etree.Element(f"{{{NS}}}back", {XML_ID: "lib029-back"})
    for child in source_divisions[:2]:
        expected_front.append(child)
    for child in source_divisions[-2:]:
        expected_back.append(child)
    top = {row["source_xml_id"]: row for row in expected_rows if row["source_tag"] == "div1"}
    if list(top) != [*FRONT, *BODY, *BACK]:
        raise ValueError("Schaff independent source order drifted")
    for index, source_id in enumerate(FRONT, 1):
        top[source_id]["tei_parent_id"] = "lib029-front"
        top[source_id]["tei_child_ordinal"] = index
    for index, source_id in enumerate(BODY, 2):
        top[source_id]["tei_child_ordinal"] = index
    for index, source_id in enumerate(BACK, 1):
        top[source_id]["tei_parent_id"] = "lib029-back"
        top[source_id]["tei_child_ordinal"] = index
    source_ids = {}
    for row in expected_rows:
        source_id = row["source_xml_id"]
        if source_id:
            if source_id in source_ids:
                raise ValueError(f"Schaff source ID is duplicated: {source_id}")
            source_ids[source_id] = row["tei_xml_id"]
    expected_nodes = {node.get(XML_ID): node for node in expected_body.iter() if node.get(XML_ID)}
    expected_nodes.update({node.get(XML_ID): node for parent in (expected_front, expected_back) for node in parent.iter() if node.get(XML_ID)})
    links = 0
    for row in expected_rows:
        href = row["attributes"].get("href")
        if row["source_tag"] != "a" or not isinstance(href, str) or not href.startswith("#"):
            continue
        destination = source_ids.get(href[1:])
        if destination is None:
            raise ValueError(f"Schaff retained link target is missing: {href}")
        node = expected_nodes[row["tei_xml_id"]]
        if node.tag != f"{{{NS}}}ref" or node.get("target") != href:
            raise ValueError(f"Schaff independent link source mapping drifted: {href}")
        node.set("target", f"#{destination}")
        row["tei_attributes"]["target"] = f"#{destination}"
        links += 1
    if links != 5327:
        raise ValueError(f"Schaff retained link census drifted: {links}")
    headings = 0
    for row in expected_rows:
        if row["source_tag"] not in {"h1", "h2", "h3", "h4", "h5", "h6", "title"}:
            continue
        node = expected_nodes[row["tei_xml_id"]]
        if node.tag != f"{{{NS}}}p" or node.getparent().tag != f"{{{NS}}}div":
            raise ValueError("Schaff source heading hierarchy drifted")
        if row["source_xml_id"] in LATE_HEADINGS:
            rendition = f"source-{row['source_tag']}"
            node.set("rend", rendition)
            row["tei_attributes"]["rend"] = rendition
        else:
            node.tag = f"{{{NS}}}head"
            row["tei_tag"] = "head"
        headings += 1
    if headings != 52:
        raise ValueError(f"Schaff retained heading census drifted: {headings}")
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if tei.tag != f"{{{NS}}}TEI" or tei.get(XML_ID) != "lib029-candidate" or tei.getroottree().docinfo.doctype:
        raise ValueError("Schaff TEI root drifted")
    header_hashes = tei.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256']", namespaces={"tei": NS})
    if len(header_hashes) != 1 or header_hashes[0].text != _sha(source_manifest.authority_path("creeds-of-christendom-vol-1-source").read_bytes()):
        raise ValueError("Schaff TEI header does not bind the retained source bytes")
    text = tei.find(f"{{{NS}}}text")
    if text is None or [child.tag for child in text] != [f"{{{NS}}}{part}" for part in ("front", "body", "back")]:
        raise ValueError("Schaff front/body/back structure drifted")
    if not all(_same_tree(actual, expected) for actual, expected in zip(text, (expected_front, expected_body, expected_back), strict=True)):
        raise ValueError("Schaff TEI differs from independent retained-source projection")
    etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))).assertValid(tei)
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    schema = json.loads(source_manifest.authority_path("source-accountability-schema").read_bytes())
    Draft202012Validator(schema).validate(accounting)
    if accounting.get("crosswalk") != expected_rows or accounting.get("feature_count") != len(expected_rows):
        raise ValueError("Schaff source-carrier accounting drifted")
    if any(accounting.get(name) != 0 for name in ("omitted_feature_count", "duplicate_feature_count", "unresolved_feature_count")):
        raise ValueError("Schaff source accounting has gaps")
    if accounting["document_accounting"][0]["scope_div1_ids"] != [*FRONT, *BODY, *BACK]:
        raise ValueError("Schaff document boundary drifted")
    if b"CCEL.org" not in candidate.member_bytes("README.source.md"):
        raise ValueError("Schaff attribution deliverable absent")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("status") != "nonaccepted" or provenance.get("canonical_ir_written") or provenance.get("canonical_data_written"):
        raise ValueError("Schaff candidate claims unsupported acceptance")
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _import_closure_sha256(repository_root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source_manifest.authority_path("creeds-of-christendom-vol-1-source").read_bytes()),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(source_manifest.authority_path("validation-policy").read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha((json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
