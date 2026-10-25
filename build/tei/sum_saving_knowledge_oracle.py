"""Independent source reader for the 37c-300 Sum candidate."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Mapping

from lxml import etree, html

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

_T = "http://www.tei-c.org/ns/1.0"
_X = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _plain(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _expected(node: etree._Element) -> tuple[str, dict[str, str]]:
    tag = str(node.tag).lower()
    if tag == "div": return "div", {"type": "html-div"}
    if tag in {"h1", "h2", "h3"}: return "div", {"type": "source-heading"}
    if tag == "p": return "p", {}
    if tag in {"strong", "b", "em"}: return "hi", {"rend": "italic" if tag == "em" else "bold", "ana": f"html-{tag}"}
    if tag == "br": return "lb", {}
    if tag == "ol": return "list", {"type": "ordered"}
    if tag == "li": return "item", {}
    if tag == "a" and node.get("href") is not None: return "ref", {"target": str(node.get("href")), "type": "html-a"}
    raise ValueError(f"unaccounted 37c-300 source element: {tag}")


def _walk(source: etree._Element, target: etree._Element, events: list[dict[str, object]], tree: etree._ElementTree, slug: str) -> None:
    ordinal = len(events) + 1
    name, attrs = _expected(source)
    if etree.QName(target).namespace != _T or etree.QName(target).localname != name:
        raise ValueError("37c-300 TEI element mapping differs from source")
    got_attrs = {etree.QName(k).localname: v for k, v in target.attrib.items() if k != _X}
    if got_attrs != attrs or target.get(_X) != f"{slug}-node-{ordinal:05d}":
        raise ValueError("37c-300 TEI identity or attributes differ from source")
    if str(source.tag).lower() in {"h1", "h2", "h3"}:
        if target.text is not None or len(target) != 1 or target[0].tag != f"{{{_T}}}head":
            raise ValueError("37c-300 source heading lacks its semantic TEI division/head")
        heading = target[0]
        if heading.text != source.text or len(heading) != len(source):
            raise ValueError("37c-300 heading text or inline children differ")
        events.append({"ordinal": ordinal, "source_xpath": tree.getpath(source), "source_tag": str(source.tag).lower(),
                       "source_attributes": dict(sorted((str(k), str(v)) for k, v in source.attrib.items())),
                       "direct_text_sha256": _sha((source.text or "").encode()), "tail_sha256": _sha((source.tail or "").encode()),
                       "tei_xml_id": target.get(_X), "tei_tag": name, "tei_attributes": attrs, "disposition": "represented"})
        for left, right in zip(source, heading):
            if not isinstance(left.tag, str):
                raise ValueError("comment or processing instruction inside represented heading")
            _walk(left, right, events, tree, slug)
            if left.tail != right.tail:
                raise ValueError("37c-300 heading inline tail moved or changed")
        return
    if target.text != source.text or len(target) != len(source):
        raise ValueError("37c-300 text or child count differs from source")
    events.append({"ordinal": ordinal, "source_xpath": tree.getpath(source), "source_tag": str(source.tag).lower(),
                   "source_attributes": dict(sorted((str(k), str(v)) for k, v in source.attrib.items())),
                   "direct_text_sha256": _sha((source.text or "").encode()), "tail_sha256": _sha((source.tail or "").encode()),
                   "tei_xml_id": target.get(_X), "tei_tag": name, "tei_attributes": attrs, "disposition": "represented"})
    if str(source.tag).lower() == "div" and any(str(child.tag).lower() in {"h1", "h2", "h3"} for child in source):
        if target.text != source.text or len(target) != len(source):
            raise ValueError("37c-300 heading-flow source grouping differs")
        for left, flow in zip(source, target):
            if flow.tag != f"{{{_T}}}div" or flow.attrib != {"type": "source-flow"} or len(flow) != 1 or flow.text is not None:
                raise ValueError("37c-300 heading-flow division differs")
            _walk(left, flow[0], events, tree, slug)
            if left.tail != flow.tail:
                raise ValueError("37c-300 heading-flow tail moved or changed")
        return
    for left, right in zip(source, target):
        if not isinstance(left.tag, str):
            raise ValueError("comment or processing instruction inside represented text")
        _walk(left, right, events, tree, slug)
        if left.tail != right.tail:
            raise ValueError("37c-300 source tail moved or changed")


def _closure(root: Path) -> str:
    members = [Path(__file__).resolve(), root / "ocd_kernel/reconstruction/contract.py", root / "ocd_kernel/reconstruction/verifier.py", root / "ocd_kernel/reconstruction/__init__.py"]
    rows = [{"path": p.resolve().relative_to(root).as_posix(), "sha256": _sha(p.read_bytes())} for p in sorted(members, key=lambda p: p.as_posix())]
    return _sha(_canonical(rows))


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify(); candidate.verify_integrity()
    slug = "sum-of-saving-knowledge"
    profile_path = source_manifest.authority_path("reconstruction-profile")
    profile_bytes = profile_path.read_bytes(); profile = json.loads(profile_bytes)
    policy_path = source_manifest.authority_path("validation-policy")
    policy_bytes = policy_path.read_bytes(); policy = json.loads(policy_bytes)
    raw = source_manifest.authority_path("retained-html").read_bytes()
    if _sha(raw) != profile["source_sha256"] or policy["source_sha256"] != _sha(raw):
        raise ValueError("37c-300 source bindings disagree")
    doc = html.document_fromstring(raw).getroottree()
    columns = doc.xpath("/html/body/div[4]/div[2]/div//div[contains(concat(' ',normalize-space(@class),' '),' wpb_text_column ')]")
    if len(columns) != 13 or profile["column_dispositions"] != [
        "represented-contents", "represented-preface", "represented-introductory-text", "excluded-back-navigation", "excluded-empty-spacer",
        "represented-practical-use", "excluded-back-navigation", "excluded-empty-spacer", "represented-warrants", "excluded-back-navigation",
        "excluded-empty-spacer", "represented-evidences", "excluded-back-navigation"]:
        raise ValueError("37c-300 source carrier boundary changed")
    for i, node in enumerate(columns, 1):
        if i in (4, 7, 10, 13) and _plain(node) != "Back to the Top.": raise ValueError("navigation carrier changed")
        if i in (5, 8, 11) and _plain(node): raise ValueError("empty spacer acquired content")
    body = etree.fromstring(candidate.member_bytes("content.tei.xml")).xpath("/t:TEI/t:text/t:body", namespaces={"t": _T})
    if len(body) != 1 or len(body[0]) != 6: raise ValueError("37c-300 TEI column count differs")
    events: list[dict[str, object]] = []
    observed_rows = []
    all_rows = []
    dispositions = profile["column_dispositions"]
    for position, node in enumerate(columns, 1):
        all_rows.append({"index": position, "source_xpath": doc.getpath(node), "disposition": dispositions[position-1],
                         "subtree_sha256": _sha(etree.tostring(node, encoding="utf-8", with_tail=False)),
                         "normalized_text_sha256": _sha(_plain(node).encode()),
                         "element_count": sum(isinstance(n.tag, str) for n in node.iter()),
                         "word_count": len(_plain(node).split())})
    for index, (source_col, target_col) in enumerate(zip([columns[i-1] for i in (1,2,3,6,9,12)], body[0]), 1):
        if target_col.tag != f"{{{_T}}}div" or target_col.attrib != {"type":"source-column", "n":str((1,2,3,6,9,12)[index-1]), _X:f"{slug}-column-{(1,2,3,6,9,12)[index-1]:02d}"}:
            raise ValueError("37c-300 TEI source-column identity differs")
        if target_col.text != source_col.text or len(target_col) != len(source_col): raise ValueError("37c-300 source-column text/children differ")
        for left, right in zip(source_col, target_col):
            if not isinstance(left.tag, str): raise ValueError("comment within represented carrier")
            _walk(left, right, events, doc, slug)
            if left.tail != right.tail: raise ValueError("source-column tail differs")
        observed_rows.append(all_rows[(1,2,3,6,9,12)[index-1]-1])
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    expected_envelope = {"doctype": doc.docinfo.doctype, "root": str(doc.getroot().tag).lower(),
                         "head_count": len(doc.xpath("/html/head")), "body_count": len(doc.xpath("/html/body")),
                         "script_count": len(doc.xpath("//script")), "style_count": len(doc.xpath("//style")),
                         "work_content_xpath": "/html/body/div[4]/div[2]/div",
                         "outside_work_text": "retained and hash-bound; site shell/support material is not represented as work text"}
    expected_census = dict(sorted(Counter(str(n.tag).lower() for n in doc.iter() if isinstance(n.tag, str)).items()))
    comments = sum(not isinstance(n, etree._Element) or not isinstance(n.tag, str) for n in doc.iter())
    if (accounting.get("source_events") != events or accounting.get("text_columns") != all_rows
        or accounting.get("document_element_census") != expected_census
        or accounting.get("document_element_count") != sum(expected_census.values())
        or accounting.get("document_comment_count") != comments
        or accounting.get("document_envelope") != expected_envelope
        or [r for r in all_rows if r["disposition"].startswith("represented-")] != observed_rows):
        raise ValueError("37c-300 independent source accounting differs")
    if [ _plain(n) for n in doc.xpath("/html/body/div[4]/div[2]/div//h1|/html/body/div[4]/div[2]/div//h2|/html/body/div[4]/div[2]/div//h3") ] != [_plain(n) for n in body[0].xpath(".//t:div[@type='source-heading']/t:head", namespaces={"t":_T})]:
        raise ValueError("37c-300 heading text or order differs")
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    xsd = etree.XMLSchema(etree.parse(str(xsd_path)))
    tei_root = body[0].getroottree().getroot()
    if not xsd.validate(tei_root): raise ValueError(f"37c-300 TEI P5 failure: {xsd.error_log}")
    facts = MechanicalFacts(_sha(Path(__file__).read_bytes()), _closure(source_manifest.repository_root), _sha(raw), _sha(profile_bytes),
                            _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()), _sha(xsd_path.read_bytes()), _sha(policy_bytes), ())
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = "ocd-37c-300-independent-html-tei-oracle"
_oracle.oracle_version = "1"
_oracle.implementation_path = Path(__file__).resolve()
