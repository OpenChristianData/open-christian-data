"""Independent ElementTree reader for the three retained NPNF2 work roots.

No producer or producer selection helpers are imported. Source-root and readable
relationship expectations are established directly from the retained XML.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Mapping
import xml.etree.ElementTree as ET
from xml.parsers import expat

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-npnf2-missing-work-source-oracle"
ORACLE_VERSION = "1"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
ROOTS = {
    "cyril-of-jerusalem-catechetical-lectures": ("npnf207", ("ii",), "The Catechetical Lectures of S. Cyril."),
    "gregory-of-nazianzus-select-orations": ("npnf207", ("iii",), "Select Orations of Saint Gregory Nazianzen."),
    "gregory-of-nyssa-against-eunomius": ("npnf205", ("viii", "viii.i"), "Against Eunomius."),
}
PINS = {
    "npnf207": (4247548, "3ac73f4179c0b7d6e66e6fea04ae572e64c0e4a80e8fa38980b40366c8a13928"),
    "npnf205": (4225695, "43e87ed232457fd2d5862f72dd2d5d84fe1e8b69f4c3eec839bad04579327bf3"),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure(root: Path) -> str:
    names = ["build/tei/npnf2_missing_work_oracle.py", "ocd_kernel/reconstruction/__init__.py",
             "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py"]
    return _sha(_canonical([{"path": name, "sha256": _sha((root / name).read_bytes())} for name in sorted(names)]))


def _paths(root: ET.Element) -> dict[ET.Element, str]:
    result = {root: "/" + root.tag}
    def visit(parent: ET.Element) -> None:
        totals: dict[str, int] = {}
        positions: dict[str, int] = {}
        for child in parent:
            totals[child.tag] = totals.get(child.tag, 0) + 1
        for child in parent:
            positions[child.tag] = positions.get(child.tag, 0) + 1
            suffix = f"[{positions[child.tag]}]" if totals[child.tag] > 1 else ""
            label = child.tag if isinstance(child.tag, str) else "comment()"
            if child.tag is ET.ProcessingInstruction:
                raise ValueError("ungoverned processing instruction inside source document")
            result[child] = result[parent] + "/" + label + suffix
            visit(child)
    visit(root)
    return result


def _declaration(content: bytes) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    parser = expat.ParserCreate()
    declaration: dict[str, object] = {"xml_version": "1.0", "encoding": "UTF-8", "standalone": False, "doctype": ""}
    before: list[dict[str, object]] = []
    after: list[dict[str, object]] = []
    depth, seen_root = 0, False
    def xml_decl(version, encoding, standalone):
        declaration.update(xml_version=version, encoding=encoding or "UTF-8", standalone=standalone == 1)
    def start(name, attrs):
        nonlocal depth, seen_root
        depth += 1
        seen_root = True
    def end(name):
        nonlocal depth
        depth -= 1
    def shell(kind, value):
        if depth == 0:
            (after if seen_root else before).append({"kind": kind, "text": value, "tail": None})
    def doctype(name, system, public, internal):
        if internal:
            raise ValueError("unexpected internal document subset in pinned NPNF source")
        declaration["doctype"] = f'<!DOCTYPE {name}'
        if public:
            declaration["doctype"] += f' PUBLIC "{public}" "{system}"'
        elif system:
            declaration["doctype"] += f' SYSTEM "{system}"'
        declaration["doctype"] += ">"
    parser.XmlDeclHandler = xml_decl
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CommentHandler = lambda value: shell("comment", value)
    parser.ProcessingInstructionHandler = lambda name, value: shell("processing-instruction", value)
    parser.StartDoctypeDeclHandler = doctype
    parser.Parse(content, True)
    return declaration, before, after


def check_readable(source_bytes: bytes, tei_bytes: bytes, work_id: str) -> dict[str, object]:
    """Compare actual ordered carriers, attachment, text/tails, and attributes."""
    member, ancestors, title = ROOTS[work_id]
    if (len(source_bytes), _sha(source_bytes)) != PINS[member]:
        raise ValueError("independent source identity mismatch")
    source = ET.fromstring(source_bytes, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    body = source.find("ThML.body")
    if source.tag != "ThML" or body is None or len(source.findall("ThML.body")) != 1:
        raise ValueError("invalid source envelope")
    selected = body
    for depth, source_id in enumerate(ancestors, 1):
        matches = [n for n in selected if n.tag == f"div{depth}" and n.get("id") == source_id]
        if len(matches) != 1 or sum(n.get("id") == source_id for n in source.iter()) != 1:
            raise ValueError("independent root ancestry mismatch")
        selected = matches[0]
    if selected.get("title") != title:
        raise ValueError("independent root title mismatch")
    target = ET.fromstring(tei_bytes)
    if target.tag != TEI + "TEI" or target.attrib != {XML_ID: work_id}:
        raise ValueError("target work identity mismatch")
    children = list(target)
    if [n.tag for n in children] != [TEI + "teiHeader", TEI + "text"]:
        raise ValueError("unexpected TEI document structure")
    text = children[1]
    if text.attrib or len(text) != 1 or text[0].tag != TEI + "body" or text[0].attrib or len(text[0]) != 1:
        raise ValueError("unexpected work container")
    if any(n.text or n.tail for n in (target, text, text[0])):
        raise ValueError("invented text outside source work")
    paths = _paths(source)
    rows: list[dict[str, object]] = []
    inverse = {"p": "p", "note": "note", "i": "hi", "span": "seg", "sup": "hi",
               "pb": "pb", "scripRef": "ref", "table": "table", "tr": "row", "td": "cell", "br": "lb"}
    def compare(original: ET.Element, actual: ET.Element) -> None:
        tag = "div" if original.tag in {"div1", "div2", "div3", "div4"} else inverse.get(original.tag)
        if original.tag == "span" and original.get("lang"):
            tag = "foreign"
        if tag is None or actual.tag != TEI + tag:
            raise ValueError(f"readable carrier type changed at {paths[original]}")
        attrs = {XML_ID: f"{work_id}-{len(rows) + 1}"}
        if tag == "foreign":
            lang = original.get("lang")
            attrs[XML_LANG] = {"EL": "grc", "HE": "he", "LA": "la"}.get(lang, lang.lower())
        if tag == "div":
            attrs["type"] = original.get("type", "source-division")
        if original is selected:
            attrs.update(type="work", subtype=work_id)
        if original.tag in {"i", "sup"}:
            attrs["rend"] = "italic" if original.tag == "i" else "superscript"
        style = " ".join(original.attrib[k] for k in ("class", "style") if original.get(k))
        if style:
            attrs["rend"] = style
        if tag in {"div", "note", "pb"} and "n" in original.attrib:
            attrs["n"] = original.get("n")
        if tag == "note":
            if "place" in original.attrib:
                attrs["place"] = original.get("place")
            if "anchored" in original.attrib:
                value = original.get("anchored")
                if value not in {"yes", "no", "true", "false"}:
                    raise ValueError("unexpected source anchored value")
                attrs["anchored"] = "true" if value in {"yes", "true"} else "false"
        if tag == "pb" and original.get("href"):
            attrs["facs"] = original.get("href")
        if original.tag == "scripRef":
            if original.get("passage"):
                attrs["cRef"] = original.get("passage")
            if original.get("osisRef"):
                attrs["target"] = original.get("osisRef")
        if actual.attrib != attrs or (actual.text or "") != (original.text or "") or (actual.tail or "") != (original.tail or ""):
            raise ValueError(f"readable attributes or mixed text changed at {paths[original]}")
        heading = original.get("title") if tag == "div" else None
        target_children = list(actual)
        if heading is not None:
            if not target_children:
                raise ValueError("missing generated source title")
            head = target_children.pop(0)
            if head.tag != TEI + "head" or head.attrib or len(head) or head.text != heading or head.tail:
                raise ValueError("source title representation mismatch")
        if len(target_children) != len(original):
            raise ValueError(f"readable child count changed at {paths[original]}")
        rows.append({"source_path": paths[original], "source_tag": original.tag,
                     "source_attributes": dict(original.attrib), "source_text": original.text,
                     "source_tail": original.tail, "tei_xml_id": attrs[XML_ID], "tei_tag": tag,
                     "generated_title_head": heading})
        for source_child, target_child in zip(original, target_children):
            if tag == "div" and source_child.tag in {"i", "sup", "span", "scripRef"}:
                if target_child.tag != TEI + "ab" or target_child.attrib != {"type": "source-inline-container"} or len(target_child) != 1 or target_child.text or target_child.tail:
                    raise ValueError("inline work wrapper mismatch")
                target_child = target_child[0]
            compare(source_child, target_child)
    compare(selected, text[0][0])
    represented = set(selected.iter())
    envelope = [{"source_path": paths[n], "source_tag": n.tag if isinstance(n.tag, str) else "comment", "source_attributes": dict(n.attrib),
                 "source_text": n.text, "source_tail": n.tail,
                 "disposition": "represented" if n in represented else "outside-selected-work"} for n in source.iter()]
    declaration, before, after = _declaration(source_bytes)
    return {"represented_carriers": rows, "document_carriers": envelope,
            "document_declaration": declaration, "pre_root_nodes": before, "post_root_nodes": after}


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    work_id = str(source_manifest.record.get("work_id"))
    if work_id not in ROOTS:
        raise ValueError("unsupported oracle work")
    manifest_relative = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if (candidate.manifest.get("source_manifest") != {"path": manifest_relative, "sha256": source_manifest.sha256}
            or candidate.manifest.get("converter") != dict(source_manifest.record["converter"])
            or candidate.manifest.get("source_id") != source_manifest.record["source_id"]
            or candidate.manifest.get("status") != "nonaccepted"
            or candidate.manifest.get("package_schema") != dict(source_manifest.record["package_schema"])):
        raise ValueError("candidate source/converter binding mismatch")
    source_bytes = source_manifest.authority_path("retained-source").read_bytes()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile, policy = json.loads(profile_bytes), json.loads(policy_bytes)
    if profile.get("work_id") != work_id or policy.get("work_id") != work_id:
        raise ValueError("profile/policy work mismatch")
    member, ancestors, title = ROOTS[work_id]
    if profile.get("root_path") != list(ancestors) or profile.get("source_sha256") != _sha(source_bytes):
        raise ValueError("profile source root mismatch")
    content = candidate.member_bytes("content.tei.xml")
    expected = check_readable(source_bytes, content, work_id)
    represented_rows = expected["represented_carriers"]
    document_rows = expected["document_carriers"]
    selected_path = represented_rows[0]["source_path"]
    if (profile.get("contract") != "ocd-npnf2-missing-work-profile-v1"
            or profile.get("root_title") != title
            or profile.get("source_path") != f"raw/ccel/npnf2/{member}.xml"
            or profile.get("source_bytes") != len(source_bytes)
            or profile.get("selected_tag_counts") != dict(Counter(row["source_tag"] for row in represented_rows))
            or profile.get("document_tag_counts") != dict(Counter(row["source_tag"] for row in document_rows))
            or profile.get("selected_child_ids") != [row["source_attributes"].get("id") for row in represented_rows if row["source_path"].rsplit("/", 1)[0] == selected_path]):
        raise ValueError("source profile inventory mismatch")
    if (policy.get("contract") != "ocd-npnf2-missing-work-validation-policy-v1"
            or policy.get("source_sha256") != _sha(source_bytes)
            or policy.get("root_path") != list(ancestors)):
        raise ValueError("independent validation policy source mismatch")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    for name, value in expected.items():
        if accounting.get(name) != value:
            raise ValueError(f"independent source accounting mismatch: {name}")
    if accounting.get("tei_sha256") != _sha(content) or accounting.get("work_id") != work_id:
        raise ValueError("accounting candidate binding mismatch")
    expected_accounting = {
        **expected, "work_id": work_id, "source_path": f"raw/ccel/npnf2/{member}.xml",
        "source_sha256": _sha(source_bytes), "root_path": list(ancestors), "tei_sha256": _sha(content),
        "scope": "complete selected subtree; enclosing and sibling material accounted outside projection",
        "verification_status": "independent fidelity verification and candidate packaging pending",
    }
    if candidate.member_bytes("source-accountability.json") != _canonical(expected_accounting):
        raise ValueError("complete source-accounting record mismatch")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("candidate attribution README mismatch")
    xsd = source_manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(xsd)))
    if not schema.validate(etree.fromstring(content)):
        raise ValueError(f"TEI schema failure: {schema.error_log}")
    def node(tag, text=None, attrs=None, children=()):
        return (TEI + tag, attrs or {}, text or "", "", tuple(children))
    def signature(element):
        return (element.tag, dict(element.attrib), element.text or "", element.tail or "",
                tuple(signature(child) for child in element))
    expected_header = node("teiHeader", children=(node("fileDesc", children=(
        node("titleStmt", children=(node("title", title),)),
        node("publicationStmt", children=(node("publisher", "Open Christian Data"),
            node("availability", attrs={"status": "restricted"}, children=(node("p", "Nonaccepted reconstruction candidate; publication is not authorized."),)))),
        node("sourceDesc", children=(node("bibl", children=(node("title", title),
            node("ptr", attrs={"target": f"raw/ccel/npnf2/{member}.xml"}),
            node("idno", _sha(source_bytes), {"type": "sha256"}))),)),
    )),))
    if signature(ET.fromstring(content)[0]) != expected_header:
        raise ValueError("complete header metadata mismatch")
    expected_provenance = {
        "contract": "ocd-npnf2-missing-work-provenance-v1", "work_id": work_id,
        "source_manifest_sha256": source_manifest.sha256, "source_sha256": _sha(source_bytes),
        "root_path": list(ancestors), "profile_sha256": _sha(profile_bytes), "publication": False,
    }
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError("complete provenance mismatch")
    unresolved = {"id": "acceptance-and-metadata-review", "status": "unresolved",
                  "detail": "Candidate technical checks do not establish human acceptance, rights clearance, work-level contributor allocation, or publication authorization."}
    if candidate.member_bytes("unresolved.jsonl") != _canonical(unresolved):
        raise ValueError("unresolved decision scope mismatch")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_closure(source_manifest.repository_root),
        profile_sha256=_sha(profile_bytes), policy_sha256=_sha(policy_bytes),
        package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        source_sha256=_sha(source_bytes), xsd_sha256=_sha(xsd.read_bytes()), findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
