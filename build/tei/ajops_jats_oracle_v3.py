from __future__ import annotations

import base64
import hashlib
import json
import platform
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping

import fitz
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from build.tei.durham_import_closure import digest as closure_digest
from build.lib.tei_link_check import check_links

TEI = "http://www.tei-c.org/ns/1.0"
ORACLE_ID = "ocd-ajops-jats-article-independent-source-census-oracle"
ORACLE_VERSION = "3"
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
def _canon(o: object) -> bytes:
    return (json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()

def _path_records(root):
    records=[]
    def visit(node,path,parent_path):
        tag=_local(node.tag)
        records.append((node,path,parent_path))
        ranks={}
        for child in list(node):
            child_tag=_local(child.tag);ranks[child_tag]=ranks.get(child_tag,0)+1
            visit(child,f"{path}/{child_tag}[{ranks[child_tag]}]",path)
    root_tag=_local(root.tag)
    visit(root,f"/{root_tag}[1]",None)
    return records

def _attrs_token(element):
    attrs=dict(element.attrib)
    if not attrs:return None
    return "urn:ocd:jats-attrs:"+base64.urlsafe_b64encode(_canon(attrs)).decode("ascii").rstrip("=")

def _ana_path(ana):
    tokens=[x for x in ana.split() if x.startswith("urn:ocd:jats-path:")]
    if len(tokens)!=1:raise ValueError("source locus marker is absent or duplicated")
    token=tokens[0].split(":",3)[-1]
    return base64.urlsafe_b64decode(token+"="*((-len(token))%4)).decode("utf-8")

TRACKED_TAGS={"article","front","body","back","sec","p","fig","graphic","inline-graphic","table-wrap","table-wrap-foot","caption","table","tr","td","th","fn","ref","ref-list","list","list-item","article-title","break"}

def _authority(source: SourceManifest, name: str):
    for item in source.record["authorities"]:
        if item["name"] == name:
            return item
    raise ValueError(f"missing authority {name}")
def _runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"

def _check_readable_links(source, tei) -> dict:
    """Derive destinations from JATS, independently of the producer mapping."""
    marked = {}
    for node in tei.iter():
        if "urn:ocd:jats-path:" not in node.get("ana", ""):
            continue
        path = _ana_path(node.get("ana"))
        if path in marked:
            raise ValueError(f"duplicate readable source locus {path}")
        marked[path] = node
    for node, path, _ in _path_records(source):
        tag = _local(node.tag)
        identity = node.get("id")
        if identity and (path not in marked or marked[path].get("{http://www.w3.org/XML/1998/namespace}id") != identity):
            raise ValueError(f"readable source ID differs at {path}")
        if tag not in {"xref", "ext-link", "email"}:
            continue
        target = node.get("{http://www.w3.org/1999/xlink}href")
        if tag == "xref" and node.get("rid"):
            target = " ".join(f"#{value}" for value in node.get("rid").split())
        elif tag == "email":
            target = target or "".join(node.itertext()).strip()
            if target and not target.startswith("mailto:"):
                target = "mailto:" + target
        actual = marked.get(path)
        if actual is None or actual.tag != f"{{{TEI}}}ref" or actual.get("target") != (target or None):
            raise ValueError(f"readable link destination differs at {path}")
    result = check_links(etree.tostring(tei))
    if result["status"] != "pass":
        raise ValueError("readable local link closure failed")
    return {"local_fragments": len(result["checked"]), "status": result["status"]}

def _oracle(source: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source.verify()
    candidate.verify_integrity()
    root = source.repository_root
    converter = source.record["converter"]
    validator = source.record["validator"]
    live_producer = closure_digest(root, root / converter["implementation_path"])
    if source.record.get("producer_import_closure_sha256") != live_producer:
        raise ValueError("AJOPS producer import closure drifted")
    live_oracle = closure_digest(root, Path(__file__))
    if live_oracle != validator["import_closure_sha256"]:
        raise ValueError("AJOPS oracle import closure drifted")
    xml_bytes = source.authority_path("publisher-xml").read_bytes()
    pdf_bytes = source.authority_path("publisher-pdf").read_bytes()
    xml_auth = _authority(source, "publisher-xml")
    pdf_auth = _authority(source, "publisher-pdf")
    profile_bytes = source.authority_path("feature-profile").read_bytes()
    profile = json.loads(profile_bytes)
    if _sha(xml_bytes) != xml_auth["sha256"] or _sha(pdf_bytes) != pdf_auth["sha256"]:
        raise ValueError("AJOPS source witness digest drifted")
    src = ET.fromstring(xml_bytes)
    src_text = _norm(" ".join(src.itertext()))
    tei_parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), tei_parser)
    readable_links = _check_readable_links(src, tei)
    ns = {"t": TEI}
    body = tei.find(f"{{{TEI}}}text/{{{TEI}}}body")
    if body is None:
        raise ValueError("TEI body is absent")
    tei_text = _norm(" ".join(body.itertext()))
    if tei_text != src_text:
        raise ValueError("TEI source text is omitted, changed, duplicated, or reordered")
    title = " ".join(next((e.text or "" for e in src.iter() if _local(e.tag) == "article-title"), "").split())
    tei_title = " ".join(tei.xpath("string(/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title)", namespaces=ns).split())
    if title != tei_title:
        raise ValueError("TEI header title differs from publisher JATS")
    source_counts = {}
    for element in src.iter():
        tag = _local(element.tag)
        source_counts[tag] = source_counts.get(tag, 0) + 1
    if source_counts != profile["element_counts"]:
        raise ValueError("source element census differs from bound profile")
    source_records=_path_records(src)
    expected=[(_local(node.tag),path,_attrs_token(node)) for node,path,_ in source_records if _local(node.tag) in TRACKED_TAGS]
    actual=[];actual_nodes={}
    for node in tei.iter():
        tag_tokens=[x.split(":",3)[-1] for x in node.get("ana","").split() if x.startswith("urn:ocd:jats-tag:")]
        if len(tag_tokens)!=1 or tag_tokens[0] not in TRACKED_TAGS:continue
        path=_ana_path(node.get("ana",""));attrs=[x for x in node.get("ana","").split() if x.startswith("urn:ocd:jats-attrs:")]
        if len(attrs)>1:raise ValueError("source attribute marker is duplicated")
        record=(tag_tokens[0],path,attrs[0] if attrs else None)
        actual.append(record)
        if path in actual_nodes:raise ValueError(f"duplicate TEI source locus {path}")
        actual_nodes[path]=node
    if expected!=actual:
        limit=min(len(expected),len(actual));index=next((i for i in range(limit) if expected[i]!=actual[i]),limit)
        wanted=expected[index] if index<len(expected) else None;found=actual[index] if index<len(actual) else None
        raise ValueError(f"source carrier order, ancestry, tag, or attributes differ at event {index}: expected={wanted!r} actual={found!r}")
    roles={"table-wrap":"div","table-wrap-foot":"div","caption":"div","fig":"div","table":"table","tr":"row","td":"cell","th":"cell","fn":"note","graphic":"graphic","inline-graphic":"graphic","break":"lb"}
    for node,path,parent_path in source_records:
        tag=_local(node.tag)
        if path in actual_nodes and tag in roles and _local(actual_nodes[path].tag)!=roles[tag]:
            raise ValueError(f"TEI carrier role differs for {tag} at {path}")
        if parent_path not in actual_nodes or path not in actual_nodes or tag not in TRACKED_TAGS:continue
        parent=actual_nodes[parent_path];child=actual_nodes[path]
        current=child.getparent()
        while current is not None and current is not parent:current=current.getparent()
        if current is None:raise ValueError(f"source ancestry was flattened at {path}")
        if tag=="p" and _local(parent.tag) in {"caption","fn"} and _local(child.tag) not in {"p","div"}:
            raise ValueError(f"caption or footnote paragraph carrier differs at {path}")
    for element in src.iter():
        if _local(element.tag)!="tr":continue
        path=next(path for node,path,_ in source_records if node is element)
        tei_row=actual_nodes[path]
        path_parts=path.split("/")[:-1]
        section=next((part.split("[",1)[0] for part in reversed(path_parts) if part.split("[",1)[0] in {"thead","tbody","tfoot"}),None)
        expected_section=f"urn:ocd:jats-row-section:{section}" if section else None
        actual_sections=[token for token in tei_row.get("ana","").split() if token.startswith("urn:ocd:jats-row-section:")]
        if actual_sections!=([expected_section] if expected_section else []):raise ValueError(f"table row section differs at {path}")
    figures = []
    for element in src.iter():
        if _local(element.tag) == "fig":
            captions = " ".join(" ".join("".join(c.itertext()).split()) for c in element.iter() if _local(c.tag) == "caption")
            graphics = [v for e in element.iter() for k,v in e.attrib.items() if k.endswith("}href") and _local(e.tag) == "graphic"]
            figures.append({"caption":captions,"graphics":graphics})
    profile_figures=[{"caption":item.get("caption"),"graphics":item.get("graphics")} for item in profile["figures"]]
    if figures != profile_figures:
        raise ValueError("figure caption or graphic inventory differs from source profile")
    for figure in profile["figures"]:
        pages=figure.get("pdf_pages")
        if not isinstance(pages,list) or any(not isinstance(page,int) or page<1 or page>profile["pdf_page_count"] for page in pages):
            raise ValueError("figure PDF page locators are invalid")
    expected_graphics=[]
    for element,path,_ in source_records:
        if _local(element.tag) in {"graphic","inline-graphic"}:
            href=next((value for key,value in element.attrib.items() if key.endswith("}href")),None)
            if href is not None:expected_graphics.append((path,href))
    actual_graphics=[]
    for node in tei.iter():
        tag_tokens=[x.split(":",3)[-1] for x in node.get("ana","").split() if x.startswith("urn:ocd:jats-tag:")]
        if tag_tokens and tag_tokens[0] in {"graphic","inline-graphic"}:
            if node.tag!=f"{{{TEI}}}graphic":raise ValueError("JATS graphic is not represented by TEI graphic")
            actual_graphics.append((_ana_path(node.get("ana","")),node.get("url")))
    if expected_graphics!=actual_graphics:raise ValueError("graphic source loci, order, or references differ")
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        page_hashes = [_sha(p.get_text("text", sort=True).encode("utf-8")) for p in pdf]
        page_text = _norm(" ".join(p.get_text("text", sort=True) for p in pdf))
        if page_hashes != profile["pdf_page_text_sha256"]:
            raise ValueError("PDF page text or page order differs from source profile")
        if len(pdf) != profile["pdf_page_count"] or any(not h for h in page_hashes):
            raise ValueError("PDF page envelope is incomplete")
        if _norm(title) not in page_text:
            raise ValueError("publisher PDF does not independently corroborate article title")
        for figure in profile["figures"]:
            caption=_norm(figure["caption"])
            if not figure["pdf_pages"] or not any(caption in _norm(pdf[page-1].get_text("text", sort=True)) for page in figure["pdf_pages"]):
                raise ValueError("figure caption is absent from its recorded PDF page locator")
    xsd = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    if not xsd.validate(tei):
        raise ValueError(f"TEI P5 validation failed: {xsd.error_log.last_error}")
    findings = [
        f"Readable source IDs and intended link destinations checked; local fragments={readable_links['local_fragments']}.",
        f"Exact text order conserved across {profile['text_node_count']} non-whitespace JATS text nodes.",
        f"Source carrier tags, exact source paths, attributes, document order, direct ancestry, table row groups, and graphic references were checked; source elements={sum(source_counts.values())}, figures={len(figures)}, tables={profile['table_count']}, notes={profile['note_count']}.",
        f"Publisher PDF independently bound by SHA-256 and {profile['pdf_page_count']} nonempty pages; title corroborated.",
        "Oracle source XML parsing uses Python's stdlib ElementTree; producer uses lxml. P5 validation uses lxml; no source-selection or converter function is shared."
    ]
    result = {
        "status":"pass",
        "oracle_id":ORACLE_ID,
        "oracle_version":ORACLE_VERSION,
        "implementation_sha256":_sha(Path(__file__).read_bytes()),
        "import_closure_sha256":live_oracle,
        "runtime":_runtime(),
        "source_manifest_sha256":source.sha256,
        "candidate_sha256":candidate.sha256,
        "profile_sha256":_sha(profile_bytes),
        "package_schema_sha256":_authority(source,"candidate-package-schema")["sha256"],
        "source_sha256":xml_auth["sha256"],
        "xsd_sha256":_authority(source,"tei-p5-xsd")["sha256"],
        "policy_sha256":_authority(source,"independent-validation-policy")["sha256"],
        "result_sha256":"",
        "findings":findings
    }
    result["result_sha256"] = _sha(_canon({k:v for k,v in result.items() if k != "result_sha256"}))
    return result
_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
