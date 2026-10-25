"""Independent direct-source oracle for the second complete Georgius epitaph."""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from xml.etree import ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction.contract import _canonical,_validation_authority_bindings
from ocd_kernel.tei.validate import compiled_schema

ORACLE_ID="ocd-georgii-aliud-independent-source-check"
ORACLE_VERSION="1"
ROOT=Path(__file__).resolve().parents[2]
TEI="http://www.tei-c.org/ns/1.0"
T="{"+TEI+"}"
X="{http://www.w3.org/XML/1998/namespace}id"
SHA="2a096d80ae17e4f701fdce91585d77afb5d69e385167a46f45173e887dc38ce5"
TITLE="Second Epitaph for Georgius (from Epitaphium senioris Georgii triplex)"
WORK_ID="lambertus-epitaphium-georgii-aliud"

def closure_sha():
    paths=[Path(__file__).resolve(),ROOT/"ocd_kernel/reconstruction/contract.py",ROOT/"ocd_kernel/tei/validate.py"]
    return sha256(_canonical([dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(p.read_bytes()).hexdigest()) for p in sorted(paths,key=str)])).hexdigest()

def _stats(nodes):
    nodes=list(nodes)
    return dict(elements=len(nodes),attributes=sum(len(n.attrib) for n in nodes),tags=dict(sorted(Counter(n.tag.rsplit("}",1)[-1] for n in nodes).items())),text_characters=sum(len(n.text or "")+len(n.tail or "") for n in nodes))

def _same(a,b,*,outer=False):
    if (a.tag,dict(a.attrib),a.text,len(a))!=(b.tag,dict(b.attrib),b.text,len(b)) or (not outer and a.tail!=b.tail):
        raise ValueError("source tag/attribute/text/tail/attachment mismatch at "+(a.get(X) or a.tag))
    for x,y in zip(a,b,strict=True): _same(x,y)

def _oracle(manifest,candidate):
    findings=[]
    try:
        manifest.verify(); candidate.verify_integrity()
        raw=manifest.authority_path("retained-source").read_bytes()
        if sha256(raw).hexdigest()!=SHA or len(raw)!=405383 or b"<!DOCTYPE" in raw: raise ValueError("exact retained source mismatch")
        source=ET.fromstring(raw); volume=source.find(T+"text/"+T+"body")[0]; divisions=list(volume)
        if volume.get("type")!="volume" or len(divisions)!=3 or divisions[2].attrib!={"n":"Carmina","type":"work"} or len(divisions[2])!=1: raise ValueError("source envelope/boundary mismatch")
        ab=divisions[2][0]; children=list(ab)
        if len(children)!=959 or ab.tag!=T+"ab": raise ValueError("source Carmina carrier mismatch")
        markers={"bsb00000720_00271_10":89,"bsb00000720_00271_16":95,"bsb00000720_00271_17":96,"bsb00000720_00272":99,"bsb00000720_00272_4":103,"bsb00000720_00272_5":104,"bsb00000720_00272_12":111}
        counts=Counter(n.get(X) for n in source.iter() if n.get(X))
        if any(counts[i]!=1 or children[p].get(X)!=i for i,p in markers.items()): raise ValueError("unique native poem/page markers mismatch")
        if (children[89].tail or "").strip()!="〈18.〉 EPITAPHIUM SENIORIS GEORGII TRIPLEX" or (children[96].tail or "").strip()!="ALIUD" or (children[104].tail or "").strip()!="TERTIUM" or (children[111].tail or "").strip()!="〈19.〉 EPITAPHIUM ENGELBERTI": raise ValueError("triplex member/group headings mismatch")
        line_positions=[97,98,100,101,102,103]
        if not (children[97].tail or "").startswith("Sublevita dei, frater salveto Georgi,") or not (children[103].tail or "").startswith("quo senior metitur, iunior et rapitur."): raise ValueError("complete second-poem opening/closing mismatch")
        if [len([c for c in children[a:b] if c.tag==T+"lb"]) for a,b in [(90,96),(97,104),(105,111)]]!=[6,6,6]: raise ValueError("three independent six-line poems mismatch")
        # Separate parser corroborates the entire retained source, not only producer findings.
        lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=True)); _same(source,lsource,outer=True)
        payload=candidate.member_bytes("content.tei.xml")
        if b"<!DOCTYPE" in payload: raise ValueError("candidate DOCTYPE forbidden")
        output=ET.fromstring(payload); body=output.find(T+"text/"+T+"body")
        if output.tag!=T+"TEI" or output.attrib!={X:WORK_ID} or body is None or len(body)!=1 or body[0].attrib!={"type":"work","n":TITLE} or len(body[0])!=1: raise ValueError("one qualified second poem required")
        actual=body[0][0]
        if actual.tag!=T+"ab" or actual.attrib!=ab.attrib or actual.text is not None or len(actual)!=8: raise ValueError("complete second poem carrier mismatch")
        for native,represented in zip(children[96:104],actual,strict=True): _same(native,represented)
        selected_ids={n.get(X) for n in actual.iter() if n.get(X)}
        for n in actual.iter():
            for attr in ("corresp","target"):
                for ref in (n.get(attr) or "").split():
                    if not ref.startswith("#") or ref[1:] not in selected_ids: raise ValueError("outside native source target")
        original=source.find(T+"teiHeader/"+T+"fileDesc"); header=output.find(T+"teiHeader/"+T+"fileDesc")
        if len(header)!=3 or header.find(T+"titleStmt/"+T+"title").text!=TITLE: raise ValueError("qualified second-poem header mismatch")
        for path in (T+"publicationStmt",T+"sourceDesc/"+T+"biblFull"): _same(original.find(path),header.find(path),outer=True)
        if not compiled_schema().validate(etree.fromstring(payload)): raise ValueError("TEI P5 schema mismatch")
        ledger=json.loads(candidate.member_bytes("source-accountability.json")); nodes=[actual]+[n for c in children[96:104] for n in c.iter()]
        expected_rows=[dict(ordinal=i,tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for i,n in enumerate(nodes)]
        if ledger["crosswalk"]!=expected_rows or ledger["assigned_census"]!=_stats(nodes) or ledger["complete_document_census"]!=_stats(source.iter()): raise ValueError("direct source accounting rows/census mismatch")
        expected_divisions=[dict(ordinal=i+1,attributes=dict(d.attrib),census=_stats(d.iter()),disposition="second ALIUD epitaph only; shared heading and other poems outside body" if i==2 else "outside assigned work") for i,d in enumerate(divisions)]
        if ledger["division_dispositions"]!=expected_divisions or ledger["selected_child_indexes"]!=[96,103] or ledger["source_sha256"]!=SHA or ledger["work_id"]!=WORK_ID: raise ValueError("source division/accounting mismatch")
        spans=[dict(first=0,last=88,disposition="other Carmina matter outside group18"),dict(first=89,last=89,disposition="shared triplex collection heading, context only"),dict(first=90,last=95,disposition="complete first epitaph outside assigned second poem"),dict(first=96,last=103,disposition="complete second ALIUD epitaph including internal page break"),dict(first=104,last=110,disposition="complete third TERTIUM epitaph outside assigned second poem"),dict(first=111,last=958,disposition="numbered19 and later Carmina outside assigned second poem")]
        if ledger["carrier_dispositions"]!=spans or ledger["declared_locator_dispositions"]!={"bsb00000720_00271_10":"shared triplex heading, context outside body","bsb00000720_00271_17":"ALIUD second poem heading included","bsb00000720_00272_4":"complete final second-poem line included"}: raise ValueError("poem versus collection locator disposition mismatch")
        if ledger["native_page_ids"]!=["bsb00000720_00272"] or ledger["native_column_count"]!=0 or ledger["verse_line_ids"]!=[children[i].get(X) for i in line_positions]: raise ValueError("six-line/page/column inventory mismatch")
        profile=manifest.authority_path("profile").read_bytes(); p=json.loads(profile)
        if p["collection_context"]!=dict(source_id="bsb00000720_00271_10",literal=children[89].tail,cardinality="Three independent complete six-line epitaphs; this candidate represents second ALIUD poem only") or p["authorship_context"]!=dict(source_ids=["bsb00000720_00267_1","bsb00000720_00267_2"],literals=[children[1].tail,children[2].tail]): raise ValueError("literal collection/author context mismatch")
        if candidate.member_bytes("provenance.json")!=profile or candidate.member_bytes("README.source.md")!=manifest.authority_path("source-readme").read_bytes() or candidate.member_bytes("unresolved.jsonl")!=b"".join(_canonical(q) for q in p["candidate_questions"]): raise ValueError("profile/notice/unresolved mismatch")
    except (ValueError,KeyError,IndexError,ET.ParseError,etree.XMLSyntaxError,TypeError) as exc: findings.append(str(exc))
    result=dict(status="fail" if findings else "pass",oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(),runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,**_validation_authority_bindings(manifest),findings=findings)
    result["result_sha256"]=sha256(_canonical(result)).hexdigest(); return result

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
