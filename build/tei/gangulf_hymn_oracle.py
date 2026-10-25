"""Independent source-derived title, stanza, column and boundary oracle."""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import sys
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage
from ocd_kernel.tei.install_accepted import _io_path
TEI="{http://www.tei-c.org/ns/1.0}"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"
ORACLE_ID="ocd-gangulf-hymn-source-oracle"
ORACLE_VERSION="1"
FIRST="bsb00000754_00180_8"
LAST="bsb00000754_00180_29"
OLD_LAST="bsb00000754_00184_24"
def _sha(b):return sha256(b).hexdigest()
def _json(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
def _equal(a,b,*,outer=False):
    if a.tag!=b.tag or dict(a.attrib)!=dict(b.attrib) or a.text!=b.text or len(a)!=len(b) or (not outer and a.tail!=b.tail):return False
    return all(_equal(x,y) for x,y in zip(a,b,strict=True))
def _source(raw):
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    if root.getroottree().docinfo.doctype:raise ValueError("DOCTYPE forbidden")
    hits=root.xpath("//*[@xml:id='bsb00000754_00180_8']")
    if len(hits)!=1:raise ValueError("hymn opening is not unique")
    ab=hits[0].getparent();part=ab.getparent();parent=part.getparent();volume=parent.getparent()
    if ab.tag!=TEI+"ab" or parent.get("n")!="Vita Gangulfi" or len(volume)!=20 or volume.index(parent)!=4 or len(parent)!=2 or parent.index(part)!=1 or len(part)!=1 or len(ab)!=192:raise ValueError("independent source envelope changed")
    if ab.index(hits[0])!=0 or hits[0].tail!="II.\n":raise ValueError("source opening/attachment changed")
    titles=[e for e in ab if (e.tail or "").startswith("[HYMNUS DE GLORIOSISSIMO CHRISTI MARTIRE GENGULFO.")]
    following=[e for e in ab if (e.tail or "").startswith("INCIPIT VITA SEU ACTUS EIUSDEM VENERABILLIMI GENGULFI,")]
    if len(titles)!=1 or ab.index(titles[0])!=1 or titles[0].tail!="[HYMNUS DE GLORIOSISSIMO CHRISTI MARTIRE GENGULFO.\n" or len(following)!=1:raise ValueError("source literal title boundary changed")
    stop=ab.index(following[0]);selected=list(ab)[:stop]
    if stop!=26 or selected[-1].get(XML_ID)!=LAST or selected[-1].tail!="Aeterno moderans secula tempore. Amen.\n" or following[0].get(XML_ID)!="bsb00000754_00180_30" or ab[27].tail!="CHRISTI MARTIRIS PRECIOSI, QUAE COMMEMORATUR V. IDUS MAI.].\n":raise ValueError("hymn Amen/next-Vita/bracket context changed")
    stanzas=[]
    for node in selected[2:]:
        if node.tag==TEI+"lb":
            match=re.match(r"\((\d)\)\. (.*)\n$",node.tail or "")
            if match:stanzas.append(dict(number=int(match[1]),start_id=node.get(XML_ID),lines=[node.tail]))
            elif stanzas:stanzas[-1]["lines"].append(node.tail)
    if [s["number"] for s in stanzas]!=[1,2,3,4,5] or any(len(s["lines"])!=4 for s in stanzas):raise ValueError("whole five-stanza association changed")
    ids=[e.get(XML_ID) for e in selected if e.get(XML_ID)]
    if len(ids)!=len(set(ids)):raise ValueError("duplicate source IDs")
    spans=[]
    for node in selected:
        if node.tag==TEI+"cb":
            ref=node.get("spanTo");targets=[e for e in selected if e.get(XML_ID)==ref[1:]]
            if not ref.startswith("#") or len(targets)!=1 or targets[0].tag!=TEI+"anchor" or ab.index(targets[0])<=ab.index(node):raise ValueError("column span escaped hymn")
            spans.append(dict(number=node.get("n"),spanTo=ref,marker_position=ab.index(node),anchor_position=ab.index(targets[0])))
    if spans!=[dict(number="1",spanTo="#cb20",marker_position=2,anchor_position=11),dict(number="2",spanTo="#cb21",marker_position=12,anchor_position=21)]:raise ValueError("column association changed")
    return root,volume,part,ab,selected,stanzas,spans

def check(source_bytes,candidate_bytes,*,first_id=FIRST,last_id=LAST):
    if (first_id,last_id)!=(FIRST,LAST):raise ValueError("locator does not bound the whole hymn; historical endpoint belongs to Vita")
    source,volume,part,ab,selected,stanzas,spans=_source(source_bytes)
    candidate=etree.fromstring(candidate_bytes,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    if candidate.getroottree().docinfo.doctype:raise ValueError("DOCTYPE forbidden")
    body=candidate.find(f"{TEI}text/{TEI}body")
    if candidate.tag!=TEI+"TEI" or body is None or len(body)!=1 or body[0].get("type")!="work" or len(body[0])!=1:raise ValueError("candidate is not one separately addressable complete hymn")
    actual=body[0][0]
    if actual.tag!=part.tag or dict(actual.attrib)!=dict(part.attrib) or actual.text!=part.text or len(actual)!=1:raise ValueError("source part attachment differs")
    target=actual[0]
    if target.tag!=ab.tag or dict(target.attrib)!=dict(ab.attrib) or target.text!=ab.text or target.tail!=ab.tail or len(target)!=len(selected) or not all(_equal(s,t) for s,t in zip(selected,target,strict=True)):raise ValueError("complete mixed hymn carrier trees differ")
    return dict(status="pass",source_sha256=_sha(source_bytes),selection_c14n_sha256=_sha(b"".join(etree.tostring(e,method="c14n",with_comments=True,with_tail=True) for e in selected)),elements=sum(1 for e in actual.iter()),source_carriers=len(selected),xml_ids=len([e for e in actual.iter() if e.get(XML_ID)]),carrier_counts=dict(Counter(etree.QName(e).localname for e in actual.iter())),stanzas=stanzas,column_spans=spans,external_span_targets=0,literal_opening_bracket_preserved=True,next_Vita_excluded=True)

def _oracle(manifest:SourceManifest,candidate:CandidatePackage):
    manifest.verify();candidate.verify_integrity();profile=json.loads(manifest.authority_path("reconstruction-profile").read_bytes());policy=json.loads(manifest.authority_path("validation-policy").read_bytes());boundary=json.loads(manifest.authority_path("boundary-review").read_bytes());raw=manifest.authority_path("extracted-xml").read_bytes();work=json.loads(manifest.authority_path("work-sidecar").read_bytes());acqbytes=_io_path(manifest.repository_root/profile["acquisition_path"]).read_bytes();acquisition=json.loads(acqbytes)
    if profile["contract"]!="ocd-gangulf-hymn-profile-v1" or policy["contract"]!="ocd-gangulf-hymn-policy-v1" or profile["work_id"]!="hymnus-sancti-gangulfi" or work["work_id"]!=profile["work_id"] or work["title"]!=profile["work_title"] or _sha(acqbytes)!=profile["acquisition_sha256"] or acquisition["source_path"]!=profile["source_path"] or acquisition["source_sha256"]!=_sha(raw) or acquisition["acquisition_id"]!=profile["acquisition_id"]:raise ValueError("source/profile/acquisition/identity changed")
    edition=work["textual_forms"][0]["editions"][0]
    if acquisition["edition_id"]!=profile["edition_id"] or edition["edition_id"]!=profile["edition_id"] or edition["acquisition_ids"]!=[profile["acquisition_id"]] or any(profile.get(k)!=v for k,v in boundary.items() if k!="contract"):
        raise ValueError("profile/boundary/edition association differs")
    locator=edition["containing_source"]["locator"]
    if locator not in [f"{profile['source_path']}#{FIRST}; {profile['source_path']}#{end}" for end in (OLD_LAST,LAST)]:raise ValueError("unexpected current or historical catalog locator")
    result=check(raw,candidate.member_bytes("content.tei.xml"));source,volume,part,ab,selected,stanzas,spans=_source(raw)
    expected_volume=[dict(position=i+1,attributes=dict(e.attrib),children=len(e),c14n_sha256=_sha(etree.tostring(e,method="c14n",with_comments=True)),disposition="hymn excerpt only" if i==4 else "other work excluded") for i,e in enumerate(volume)]
    expected_carriers=[dict(position=i,tag=etree.QName(e).localname,attributes=dict(e.attrib),tail=e.tail,c14n_sha256=_sha(etree.tostring(e,method="c14n",with_comments=True,with_tail=True)),disposition="hymn included" if i<len(selected) else "following Vita excluded") for i,e in enumerate(ab)]
    if boundary["volume_inventory"]!=expected_volume or boundary["carrier_inventory"]!=expected_carriers or profile["selection_c14n_sha256"]!=result["selection_c14n_sha256"]:raise ValueError("whole source-envelope accounting differs")
    accounting=json.loads(candidate.member_bytes("source-accountability.json"))
    if any(accounting.get(k)!=v for k,v in boundary.items() if k!="contract"):raise ValueError("candidate source accounting differs")
    xml=etree.fromstring(candidate.member_bytes("content.tei.xml"),etree.XMLParser(resolve_entities=False,no_network=True))
    if xml.get(XML_ID)!="ocd-hymnus-sancti-gangulfi-bsb754-electronic-v1" or xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}titleStmt/{TEI}title").text!=work["title"] or xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{TEI}notesStmt/{TEI}note").text!=profile["source_qualification"]:raise ValueError("candidate identity/title/source qualification differs")
    for suffix in (f"{TEI}publicationStmt",f"{TEI}sourceDesc/{TEI}biblFull"):
        if not _equal(source.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}"),xml.find(f"{TEI}teiHeader/{TEI}fileDesc/{suffix}"),outer=True):raise ValueError("source publication or print bibliography differs")
    etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd")))).assertValid(xml)
    provenance=json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("status")!="nonaccepted" or provenance.get("work_id")!=profile["work_id"] or provenance.get("edition_id")!=profile["edition_id"] or provenance.get("source_sha256")!=_sha(raw) or provenance.get("canonical_ir_written") is not False:
        raise ValueError("candidate provenance differs")
    if not candidate.member_bytes("unresolved.jsonl").strip() or b"Monumenta" not in candidate.member_bytes("README.source.md"):raise ValueError("unresolved review or source credit missing")
    closure=[dict(path=p,sha256=_sha((manifest.repository_root/p).read_bytes())) for p in policy["closure_inputs"]]
    outcome=dict(status="pass",oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=_sha(Path(__file__).read_bytes()),import_closure_sha256=_sha(_json(closure)),runtime=f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=_sha(manifest.authority_path("reconstruction-profile").read_bytes()),package_schema_sha256=_sha(manifest.authority_path("candidate-package-schema").read_bytes()),source_sha256=_sha(raw),xsd_sha256=_sha(manifest.authority_path("tei-p5-xsd").read_bytes()),policy_sha256=_sha(manifest.authority_path("validation-policy").read_bytes()),findings=[]);outcome["result_sha256"]=_sha(_json(outcome));return outcome
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
