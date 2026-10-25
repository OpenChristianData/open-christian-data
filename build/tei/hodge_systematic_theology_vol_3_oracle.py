"""Independent ticket-local source-to-TEI checker for Hodge Volume III."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

from lxml import etree
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding, _validation_authority_bindings
from ocd_kernel.reconstruction import CandidatePackage


WORK_ID = "hodge-systematic-theology-vol-3"
SOURCE_KEY = "retained-hodge-vol-3"  # gitleaks:allow
TAGS = {"div":"quote","div1":"div","div2":"div","div3":"div","h1":"p","h2":"p","h3":"p","h4":"p","p":"p","i":"hi","span":"seg","note":"note","pb":"pb","scripRef":"ref","verse":"lg","l":"l","table":"table","tr":"row","td":"cell","th":"cell","colgroup":"row","col":"cell","ul":"list","li":"item","a":"ref","br":"lb","insertIndex":"milestone"}


def _oracle(source, candidate: CandidatePackage):
    source.verify()
    raw = source.authority_path(SOURCE_KEY).read_bytes()
    xml = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, remove_pis=False, huge_tree=True))
    roots = list(xml.find("ThML.body"))
    expected_ids = ["i", "ii", "iii", "iv", "v"]
    if [r.get("id") for r in roots] != expected_ids:
        raise ValueError("37c-205 complete source envelope is not current")
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"t":"http://www.tei-c.org/ns/1.0"}
    body = tei.xpath("/t:TEI/t:text/t:body", namespaces=ns)
    if len(body) != 1:
        raise ValueError("37c-205 TEI body missing or duplicated")
    target_roots = list(body[0])
    if len(target_roots) != len(roots):
        raise ValueError("37c-205 one or more source roots omitted or invented")
    observed = []

    def compare(src, dst):
        if not isinstance(src.tag, str):
            raise ValueError("37c-205 unsupported source node")
        index = len(observed) + 1
        attrs = {"xml:id": f"{WORK_ID}-feature-{index:06d}"}
        for sk, dk in (("n","n"),("class","rend"),("osisRef","target"),("passage","cRef"),("href","target"),("style","rend")):
            if src.get(sk): attrs[dk] = src.get(sk)
        if src.tag == "i": attrs["rend"] = "italic"
        if src.tag in ("h1", "h2", "h3", "h4"): attrs["rend"] = "source-" + src.tag
        if src.tag == "verse": attrs["type"] = "source-verse"
        if src.tag == "insertIndex": attrs["unit"] = "insertIndex"
        if src.tag not in TAGS or etree.QName(dst).localname != TAGS[src.tag] or dict(dst.attrib) != {f"{{http://www.w3.org/XML/1998/namespace}}id" if k == "xml:id" else k: v for k,v in attrs.items()}:
            raise ValueError(f"37c-205 structural/tag/attribute drift at source node {index}")
        if (src.text or "") != (dst.text or "") or (src.tail or "") != (dst.tail or ""):
            raise ValueError(f"37c-205 text or mixed-content order drift at node {index}")
        observed.append({"ordinal":index,"source_tag":src.tag,"source_id":src.get("id"),"source_attributes":dict(src.attrib),"source_text":src.text or "","source_tail":src.tail or "","tei_id":attrs["xml:id"],"tei_tag":TAGS[src.tag]})
        if len(src) != len(dst): raise ValueError(f"37c-205 child omission or invention at node {index}")
        for left,right in zip(src,dst,strict=True): compare(left,right)

    for left,right in zip(roots,target_roots,strict=True): compare(left,right)
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    if accountability != {"contract":"37c-205-accountability-v1","source":{"path":"raw/ccel/hodge/theology3.xml","bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()},"root_ids_in_order":expected_ids,"root_titles_in_order":[r.get("title") for r in roots],"features":observed,"feature_count":len(observed)}:
        raise ValueError("37c-205 source accountability differs from independent traversal")
    xsd = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    xsd.assertValid(tei)
    profile_sha = next(a["sha256"] for a in source.record["authorities"] if a["role"] == "complete-source-feature-profile")
    policy_sha = next(a["sha256"] for a in source.record["authorities"] if a["role"] == "independent-validation-policy")
    schema_sha = next(a["sha256"] for a in source.record["authorities"] if a["role"] == "candidate-package-schema")
    result = {"status":"pass","oracle_id":_oracle.oracle_id,"oracle_version":_oracle.oracle_version,"implementation_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"import_closure_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"runtime":_runtime_binding(),"source_manifest_sha256":source.sha256,"candidate_sha256":candidate.sha256,"profile_sha256":profile_sha,"package_schema_sha256":schema_sha,"source_sha256":hashlib.sha256(raw).hexdigest(),"xsd_sha256":next(a["sha256"] for a in source.record["authorities"] if a["role"] == "tei-validation-schema"),"policy_sha256":policy_sha,"findings":[f"Independently compared all {len(observed)} source elements, their attributes, direct text, tails, child order, complete five-root envelope, and TEI schema."]}
    result["result_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


_oracle.oracle_id = "ocd-37c205-hodge-vol-3-independent-check"
_oracle.oracle_version = "1"
