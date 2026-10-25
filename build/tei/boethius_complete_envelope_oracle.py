"""Independent source comparison for the complete Boethius CCEL envelope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding


WORK_ID = "boethius-theological-tractates"
NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TAGS = {
    "div1": "div", "div2": "div", "div": "quote", "p": "p", "h1": "p",
    "h2": "p", "h3": "p", "pb": "pb", "note": "note", "i": "hi",
    "b": "hi", "sup": "hi", "span": "seg", "sync": "anchor",
    "unclear": "seg", "scripRef": "ref", "insertIndex": "milestone",
    "ul": "list", "li": "item", "a": "ref",
}


def _oracle(source: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source.verify()
    candidate.verify_integrity()
    if candidate.manifest["status"] != "nonaccepted" or candidate.manifest["converter"] != source.record["converter"]:
        raise ValueError("Boethius candidate status or converter binding drifted")
    raw = source.authority_path("retained-thml").read_bytes()
    if len(raw) != 162005 or hashlib.sha256(raw).hexdigest() != "406487abffb39f63934771ce3b4d23b69ce4488d6bc1ccc6a6cad5b4b1e01de8":
        raise ValueError("Boethius retained source identity drifted")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, remove_pis=False, huge_tree=True)
    body = etree.fromstring(raw, parser).find("ThML.body")
    if body is None:
        raise ValueError("Boethius ThML.body is absent")
    roots = [node for node in body if isinstance(node.tag, str)]
    if [node.get("id") for node in roots] != ["i", "ii", "iii", "iv", "v"]:
        raise ValueError("Boethius five-root source envelope drifted")
    ids = [node.get("id") for node in body.iter() if isinstance(node.tag, str) and node.get("id")]
    if len(ids) != len(set(ids)):
        raise ValueError("Boethius source IDs are not unique")
    id_set = set(ids)
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"t": NS}
    text = tei.xpath("/t:TEI/t:text", namespaces=ns)
    if len(text) != 1 or [etree.QName(node).localname for node in text[0]] != ["front", "body", "back"]:
        raise ValueError("Boethius front, body, back envelope drifted")
    front, main, back = text[0]
    if [node.get(XML_ID) for node in (front, main, back)] != [
        WORK_ID + "-front", WORK_ID + "-body", WORK_ID + "-back"
    ]:
        raise ValueError("Boethius envelope identity drifted")
    if front.text != body.text or main.text or back.text:
        raise ValueError("Boethius source body text drifted")
    source_groups = [list(body)[:3], list(body)[3:4], list(body)[4:]]
    rows: list[dict[str, object]] = []
    comments: list[dict[str, object]] = []

    def record_comment(left: etree._Element) -> None:
        if left.tag is not etree.Comment or (left.tail or "").strip():
            raise ValueError("Boethius comment has unsupported visible content")
        comments.append({"text": left.text or "", "tail": left.tail or "",
                         "after_feature": len(rows), "disposition": "source-comment-ledger-only"})

    def compare(left: etree._Element, right: etree._Element) -> None:
        if not isinstance(left.tag, str):
            raise ValueError("Boethius source comment reached an element comparison")
        ordinal = len(rows) + 1
        sid = left.get("id")
        attrs = {"xml:id": f"{WORK_ID}-{sid}" if sid else f"{WORK_ID}-feature-{ordinal:06d}"}
        if left.get("n"):
            attrs["n"] = left.get("n")
        if left.get("title") and left.tag in {"div1", "div2"}:
            attrs["n"] = left.get("title")
        if left.get("class"):
            attrs["rend"] = "source-class-" + left.get("class")
        if left.get("style"):
            attrs["rend"] = "source-style-" + left.get("style")
        if left.tag in {"h1", "h2", "h3"}:
            attrs["rend"] = "source-" + left.tag
        if left.tag in {"i", "b", "sup"}:
            attrs["rend"] = {"i": "italic", "b": "bold", "sup": "superscript"}[left.tag]
        if left.tag == "unclear":
            attrs["type"] = "source-unclear"
        if left.get("lang"):
            attrs["xml:lang"] = left.get("lang").lower()
        if left.tag == "pb" and left.get("href"):
            attrs["facs"] = left.get("href")
        if left.tag == "insertIndex":
            attrs["unit"] = "insertIndex"
        if left.tag == "scripRef" and left.get("osisRef"):
            attrs["target"] = left.get("osisRef")
        if left.tag == "a":
            href = left.get("href")
            if not href or not href.startswith("#") or href[1:] not in id_set:
                raise ValueError(f"Boethius source link is unresolved: {href}")
            attrs["target"] = f"#{WORK_ID}-{href[1:]}"
        if left.tag not in TAGS or right.tag != f"{{{NS}}}{TAGS[left.tag]}":
            raise ValueError(f"Boethius TEI tag drifted at source feature {ordinal}")
        expected_attrs = {XML_ID if key == "xml:id" else "{http://www.w3.org/XML/1998/namespace}lang" if key == "xml:lang" else key: value for key, value in attrs.items()}
        if dict(right.attrib) != expected_attrs:
            raise ValueError(f"Boethius TEI attributes drifted at source feature {ordinal}")
        if (left.text or "") != (right.text or "") or (left.tail or "") != (right.tail or ""):
            raise ValueError(f"Boethius direct text or tail drifted at source feature {ordinal}")
        rows.append({
            "ordinal": ordinal, "source_tag": left.tag, "source_id": sid,
            "source_attributes": dict(left.attrib), "source_text": left.text or "",
            "source_tail": left.tail or "", "tei_id": attrs["xml:id"],
            "tei_tag": TAGS[left.tag], "tei_attributes": attrs,
        })
        source_children = [child for child in left if isinstance(child.tag, str)]
        if len(source_children) != len(right):
            raise ValueError(f"Boethius child omission or invention at source feature {ordinal}")
        target = iter(right)
        for child in left:
            if isinstance(child.tag, str):
                compare(child, next(target))
            else:
                record_comment(child)

    for source_group, target_group in zip(source_groups, (front, main, back), strict=True):
        if sum(isinstance(node.tag, str) for node in source_group) != len(target_group):
            raise ValueError("Boethius source root or comment omitted or invented")
        target = iter(target_group)
        for left in source_group:
            if isinstance(left.tag, str):
                compare(left, next(target))
            else:
                record_comment(left)
    if any(node.tag is etree.Comment for node in tei.iter()):
        raise ValueError("Boethius administrative source comments entered the TEI reading text")
    if len(rows) != 1119 or len(comments) != 10 or sum(row["source_tag"] == "a" for row in rows) != 136:
        raise ValueError("Boethius source census drifted")
    expected = {
        "contract": "ocd-boethius-complete-envelope-accountability-v1",
        "source": {"path": "raw/ccel/boethius/tracts.xml", "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
        "root_ids_in_order": ["i", "ii", "iii", "iv", "v"],
        "root_disposition": {"front": ["i", "ii", "iii"], "body": ["iv"], "back": ["v"]},
        "source_body_text": body.text or "", "features": rows, "feature_count": len(rows),
        "comments": comments, "comment_count": len(comments),
    }
    if json.loads(candidate.member_bytes("source-accountability.json")) != expected:
        raise ValueError("Boethius accountability differs from independent source traversal")
    xsd = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    xsd.assertValid(tei)
    result = {
        "status": "pass", "oracle_id": _oracle.oracle_id, "oracle_version": _oracle.oracle_version,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "import_closure_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime": _runtime_binding(), "source_manifest_sha256": source.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "complete-source-feature-profile"),
        "package_schema_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "candidate-package-schema"),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "xsd_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "tei-validation-schema"),
        "policy_sha256": next(a["sha256"] for a in source.record["authorities"] if a["role"] == "independent-validation-policy"),
        "findings": ["Independently compared 1119 source elements, 10 comments, 136 resolved links, all attributes and direct text/tails, ordered front/body/back roots, and TEI P5."],
    }
    result["result_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


_oracle.oracle_id = "ocd-boethius-complete-envelope-independent-oracle"
_oracle.oracle_version = "1"
