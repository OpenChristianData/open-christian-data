"""Independent retained-XML check of one NPNF113 child candidate."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from build.tei import npnf113_lib041_oracle as source_rules
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


ORACLE_ID = "ocd-npnf113-work-root-source-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _check_node(source: etree._Element, target: etree._Element, ordinal: int, *, root: bool, work_id: str) -> int:
    expected_attrs, _ = source_rules._expected_attrs(source, ordinal)
    if root:
        expected_attrs["corresp"] = f"#npnf113:{source.get('id')}:{work_id}"
    if (etree.QName(target).namespace != TEI
            or etree.QName(target).localname != source_rules._target_tag(source)
            or source_rules._observed_attrs(target) != expected_attrs
            or (target.text or "") != (source.text or "")
            or (target.tail or "") != ("" if root else source.tail or "")):
        raise ValueError(f"source feature {ordinal} differs in readable TEI")
    children = [item for item in source if isinstance(item.tag, str)]
    if len(children) != len(source):
        raise ValueError("source work contains unaccounted comment or instruction")
    offset = 0
    if source.tag in {"div2", "div3"} and source.get("title") is not None:
        if not len(target) or target[0].tag != f"{{{TEI}}}head" or target[0].text != source.get("title") or target[0].attrib or len(target[0]):
            raise ValueError(f"source title head differs at feature {ordinal}")
        offset = 1
    if len(target) != len(children) + offset:
        raise ValueError(f"source feature {ordinal} has omitted or invented children")
    cursor = ordinal
    for source_child, target_child in zip(children, list(target)[offset:], strict=True):
        cursor = _check_node(source_child, target_child, cursor + 1, root=False, work_id=work_id)
    return cursor


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    binding_bytes = manifest.authority_path("work-binding").read_bytes()
    binding = json.loads(binding_bytes)
    if binding.get("contract") != "ocd-npnf113-work-binding-v1":
        raise ValueError("work binding contract changed")
    policy_bytes = manifest.authority_path("validation-policy").read_bytes()
    policy = json.loads(policy_bytes)
    if (policy.get("contract") != "ocd-npnf113-work-validation-policy-v1"
            or policy.get("source_sha256") != binding["source_sha256"]
            or policy.get("aggregate_tei_sha256") != binding["aggregate_tei_sha256"]
            or policy.get("publication") != "not_ready"
            or set(policy.get("required_member_names", [])) != set(candidate.member_names)):
        raise ValueError("work validation policy or candidate inventory changed")
    source_bytes = manifest.authority_path("retained-thml").read_bytes()
    if _sha(source_bytes) != binding["source_sha256"] or len(source_bytes) != 4441248:
        raise ValueError("retained XML identity changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    source = etree.fromstring(source_bytes, parser)
    if source.getroottree().docinfo.doctype != (
        '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" '
        '"http://www.ccel.org/dtd/ThML10.dtd">'
    ):
        raise ValueError("retained XML doctype changed")
    body = source.find("ThML.body")
    if body is None:
        raise ValueError("retained XML body absent")
    roots = source.xpath("//*[@id=$id]", id=binding["source_root_id"])
    if len(roots) != 1 or roots[0].tag != "div2":
        raise ValueError("work root is absent or repeated")
    selected = roots[0]
    parent = selected.getparent()
    if (parent is None or parent.tag != "div1" or parent.get("id") != binding["source_parent_id"]
            or parent.getparent() is not body or selected.get("title") != binding["source_title"]
            or _sha(etree.tostring(selected, method="c14n")) != binding["source_root_c14n_sha256"]):
        raise ValueError("source work boundary, title, or content changed")
    volume_profile = json.loads(manifest.authority_path("aggregate-profile").read_bytes())
    assigned = [(str(root_id), str(work_id)) for root_id, work_id in volume_profile["assigned"]]
    if len(assigned) != 10 or len(set(assigned)) != 10 or (binding["source_root_id"], binding["work_id"]) not in assigned:
        raise ValueError("work is outside the verified ten-root source plan")
    if [node.get("id") for node in body.iter("div2") if node.get("id") in {row[0] for row in assigned}] != [row[0] for row in assigned]:
        raise ValueError("ten retained work roots reordered")
    start = 1
    for root_id, work_id in assigned:
        if root_id == binding["source_root_id"] and work_id == binding["work_id"]:
            break
        earlier = source.xpath("//*[@id=$id]", id=root_id)
        if len(earlier) != 1:
            raise ValueError("earlier source work root changed")
        start += len([node for node in earlier[0].iter() if isinstance(node.tag, str)])

    work_path = Path(binding["work_path"])
    acquisition_path = Path(binding["acquisition_path"])
    if (not work_path.is_relative_to(Path("library/works") / binding["work_id"])
            or not acquisition_path.is_relative_to(Path("library/works") / binding["work_id"])):
        raise ValueError("work or acquisition binding escapes child work")
    work_bytes = Path(_io_path(manifest.repository_root / work_path)).read_bytes()
    acquisition_bytes = Path(_io_path(manifest.repository_root / acquisition_path)).read_bytes()
    if (_sha(work_bytes) != binding["work_sha256"]
            or _sha(acquisition_bytes) != binding["acquisition_sha256"]):
        raise ValueError("work or acquisition sidecar bytes changed")
    work_record = json.loads(work_bytes)
    acquisition = json.loads(acquisition_bytes)
    edition_matches = [edition for form in work_record["textual_forms"] for edition in form["editions"]
                       if form["textual_form_id"] == binding["textual_form_id"]
                       and edition["edition_id"] == binding["edition_id"]]
    if (work_record["work_id"] != binding["work_id"] or len(edition_matches) != 1
            or edition_matches[0]["containing_source"]["locator"]
            != f"{binding['source_path']}#{binding['source_root_id']}"
            or binding["acquisition_id"] not in edition_matches[0]["acquisition_ids"]
            or acquisition["source_path"] != binding["source_path"]
            or acquisition["source_sha256"] != binding["source_sha256"]):
        raise ValueError("work, edition, or acquisition route changed")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    tree = etree.ElementTree(etree.fromstring(
        tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    ))
    xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(tree):
        raise ValueError(f"TEI P5 XSD failure: {xsd.error_log.last_error}")
    root = tree.getroot()
    ns = {"t": TEI}
    candidates = root.xpath("./t:text/t:body/t:div", namespaces=ns)
    body_nodes = root.xpath("./t:text/t:body", namespaces=ns)
    if (root.tag != f"{{{TEI}}}TEI" or root.get(XML_ID) != f"npnf113-{binding['work_id']}-electronic"
            or len(body_nodes) != 1 or body_nodes[0].get(XML_ID) != f"npnf113-{binding['work_id']}-body"
            or len(candidates) != 1 or len(body_nodes[0]) != 1):
        raise ValueError("candidate must contain exactly one independent work root")
    title = root.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
    source_idno = root.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc/{{{TEI}}}bibl/{{{TEI}}}idno[@type='SHA-256']")
    if title is None or title.text != binding["source_title"] or source_idno is None or source_idno.text != binding["source_sha256"]:
        raise ValueError("candidate work title or source header differs")
    last = _check_node(selected, candidates[0], start, root=True, work_id=binding["work_id"])
    expected_count = len([node for node in selected.iter() if isinstance(node.tag, str)])
    if last != start + expected_count - 1:
        raise ValueError("candidate source feature walk incomplete")
    apparatus = []
    for identifier in binding["shared_apparatus_ids"]:
        nodes = source.xpath("//*[@id=$id]", id=identifier)
        if len(nodes) != 1 or nodes[0].tag != "div2" or nodes[0].getparent() is not parent:
            raise ValueError("shared title or preface boundary changed")
        apparatus.append({"source_root_id": identifier, "title": nodes[0].get("title"),
                          "source_c14n_sha256": _sha(etree.tostring(nodes[0], method="c14n")),
                          "disposition": "retained-volume-shared-matter-outside-child-body"})
    accounting = {
        "contract": "ocd-npnf113-work-accounting-v1", "work_id": binding["work_id"],
        "source_path": binding["source_path"], "source_sha256": binding["source_sha256"],
        "source_root_id": binding["source_root_id"], "source_parent_id": binding["source_parent_id"],
        "source_title": binding["source_title"],
        "source_root_c14n_sha256": binding["source_root_c14n_sha256"],
        "source_element_count": expected_count,
        "source_attribute_count": sum(len(node.attrib) for node in selected.iter() if isinstance(node.tag, str)),
        "tei_work_c14n_sha256": _sha(etree.tostring(candidates[0], method="c14n")),
        "aggregate_tei_sha256": binding["aggregate_tei_sha256"],
        "shared_apparatus": apparatus,
        "root_tail_disposition": "excluded-selected-root-boundary",
    }
    if json.loads(candidate.member_bytes("source-accountability.json")) != accounting:
        raise ValueError("work source accountability differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance != {
        "contract": "ocd-npnf113-work-provenance-v1", "status": "nonaccepted",
        "work_id": binding["work_id"], "textual_form_id": binding["textual_form_id"],
        "edition_id": binding["edition_id"], "acquisition_id": binding["acquisition_id"],
        "source_root_id": binding["source_root_id"], "canonical_ir_written": False,
        "publication": "not_ready",
    }:
        raise ValueError("candidate provenance differs")
    if (b"Sourced via CCEL.org" not in candidate.member_bytes("README.source.md")
            or not candidate.member_bytes("unresolved.jsonl").strip()):
        raise ValueError("attribution or unresolved evidence absent")
    result = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": manifest.record["validator"]["import_closure_sha256"],
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        "source_sha256": _sha(source_bytes), "profile_sha256": _sha(binding_bytes),
        "package_schema_sha256": _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes), "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
