"""Independent stdlib XML source selection and direct tree/attribute oracle."""
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

ORACLE_ID="ocd-ludewic-independent-source-check"
ORACLE_VERSION="1"
ROOT=Path(__file__).resolve().parents[2]
TEI="http://www.tei-c.org/ns/1.0"
T="{"+TEI+"}"
X="{http://www.w3.org/XML/1998/namespace}id"
SHA="cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
TITLE="Count Ludewic's Reply to Walram of Naumburg"

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
        if sha256(raw).hexdigest()!=SHA or len(raw)!=3985065 or b"<!DOCTYPE" in raw: raise ValueError("exact retained source mismatch")
        source=ET.fromstring(raw); volume=source.find(T+"text/"+T+"body")[0]
        divisions=list(volume)
        if volume.get("type")!="volume" or len(divisions)!=21 or divisions[3].attrib!={"n":"Walrami et Herrandi epistolae de causa Heinrici regis","type":"work"} or len(divisions[3])!=1: raise ValueError("source envelope/boundary mismatch")
        ab=divisions[3][0]; children=list(ab)
        counts=Counter(n.get(X) for n in source.iter() if n.get(X))
        ids=["bsb00000829_00295_16","bsb00000829_00295_23","bsb00000829_00295_29","bsb00000829_00299_46"]
        if any(counts[i]!=1 for i in ids) or len(children)!=483: raise ValueError("source marker uniqueness mismatch")
        index={n.get(X):i for i,n in enumerate(children) if n.get(X)}
        if [index[i] for i in ids]!=[90,97,107,482]: raise ValueError("source literal boundary position mismatch")
        if not (children[106].tail or "").strip().endswith("agnoscatur:") or not (children[107].tail or "").startswith("'Comes Ludewicus domino Waltramo") or (children[482].tail or "").strip()!="silentium.'" or not (children[90].tail or "").startswith("Has sanc litteras") or "Stephano, qui et Herrandus" not in (children[91].tail or "") or "epistolam dictavit" not in (children[97].tail or ""): raise ValueError("response quotation/attribution boundaries mismatch")
        # Parser-independent source and candidate corroboration, with direct original attrs.
        lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=True))
        _same(source,lsource,outer=True)
        payload=candidate.member_bytes("content.tei.xml")
        if b"<!DOCTYPE" in payload: raise ValueError("candidate DOCTYPE forbidden")
        output=ET.fromstring(payload); body=output.find(T+"text/"+T+"body")
        if output.tag!=T+"TEI" or output.attrib!={X:"ludewic-reply-to-walram"} or body is None or len(body)!=1 or body[0].attrib!={"type":"work","n":TITLE} or len(body[0])!=1: raise ValueError("one source-defined letter required")
        actual=body[0][0]
        if actual.tag!=T+"ab" or actual.attrib!=ab.attrib or actual.text is not None or len(actual)!=376: raise ValueError("complete letter carrier mismatch")
        for native,represented in zip(children[107:483],actual,strict=True): _same(native,represented)
        selected_ids={n.get(X) for c in children[107:483] for n in c.iter() if n.get(X)}
        for c in children[107:483]:
            for n in c.iter():
                for attr in ("corresp","target"):
                    for ref in (n.get(attr) or "").split():
                        if not ref.startswith("#") or ref[1:] not in selected_ids: raise ValueError("outside native word/reference target")
        original=source.find(T+"teiHeader/"+T+"fileDesc"); header=output.find(T+"teiHeader/"+T+"fileDesc")
        if len(header)!=3 or header.find(T+"titleStmt/"+T+"title").text!=TITLE: raise ValueError("header work identity mismatch")
        for path in (T+"publicationStmt",T+"sourceDesc/"+T+"biblFull"):
            _same(original.find(path),header.find(path),outer=True)
        candidate_lxml=etree.fromstring(payload)
        if not compiled_schema().validate(candidate_lxml): raise ValueError("TEI P5 schema mismatch")
        ledger=json.loads(candidate.member_bytes("source-accountability.json"))
        all_selected=[actual]+[n for c in children[107:483] for n in c.iter()]
        rows=[dict(ordinal=i,tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for i,n in enumerate(all_selected)]
        # The synthetic ab copies source attrs but has no carrier text or tail.
        if ledger["crosswalk"]!=rows or ledger["assigned_census"]!=_stats(all_selected) or ledger["complete_document_census"]!=_stats(source.iter()): raise ValueError("source accounting rows/census mismatch")
        expected_divisions=[dict(ordinal=i+1,attributes=dict(d.attrib),census=_stats(d.iter()),disposition="selected literal letter only; surrounding narrative/reply excluded" if i==3 else "outside assigned work") for i,d in enumerate(divisions)]
        if ledger["division_dispositions"]!=expected_divisions or ledger["selected_child_indexes"]!=[107,482] or ledger["source_sha256"]!=SHA or ledger["work_id"]!="ludewic-reply-to-walram": raise ValueError("source scope disposition mismatch")
        expected_spans=[dict(first=0,last=14,disposition="narrative introduction outside Walram letter"),dict(first=15,last=89,disposition="separate quoted Walram letter excluded"),dict(first=90,last=106,disposition="narrative introduction and attribution outside Ludewic reply"),dict(first=107,last=482,disposition="complete quoted Ludewic reply")]
        if ledger["carrier_dispositions"]!=expected_spans or ledger["declared_locator_dispositions"]!={ids[0]:"receipt narrative outside body",ids[1]:"dictation narrative outside body",ids[2]:"quoted response opening included",ids[3]:"complete closing line included"}: raise ValueError("declared locator accounting mismatch")
        empty=[dict(xml_id=n.get(X),attributes=dict(n.attrib),text=n.text) for n in actual.iter(T+"w") if n.text is None]
        if [n["xml_id"] for n in empty]!=["w5041","w5042","w5051","w5052","w5077","w5078","w5090","w5093","w5094"] or ledger["empty_native_words"]!=empty: raise ValueError("native empty word fidelity mismatch")
        profile=manifest.authority_path("profile").read_bytes()
        context=json.loads(profile)["creator_context"]
        if context!={"sender":dict(name="Count Ludewic",role="sender",source_id=ids[2],literal=children[107].tail),"dictator":dict(name="Herrand of Halberstadt",role="dictator",source_ids=["bsb00000829_00295_17",ids[1]],literals=[children[91].tail,children[97].tail])}: raise ValueError("sender/dictator source context mismatch")
        if candidate.member_bytes("provenance.json")!=profile or candidate.member_bytes("README.source.md")!=manifest.authority_path("source-readme").read_bytes() or candidate.member_bytes("unresolved.jsonl")!=b"".join(_canonical(q) for q in json.loads(profile)["candidate_questions"]): raise ValueError("profile/notice/unresolved mismatch")
    except (ValueError,KeyError,IndexError,ET.ParseError,etree.XMLSyntaxError,TypeError) as exc:
        findings.append(str(exc))
    result=dict(status="fail" if findings else "pass",oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(),runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,**_validation_authority_bindings(manifest),findings=findings)
    result["result_sha256"]=sha256(_canonical(result)).hexdigest()
    return result

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
