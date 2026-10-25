"""Reconstruct the complete second Georgius epitaph from its retained electronic carrier."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from lxml import etree
from ocd_kernel.reconstruction.contract import reconstruct

WORK_ID="lambertus-epitaphium-georgii-aliud"
TITLE="Second Epitaph for Georgius (from Epitaphium senioris Georgii triplex)"
CONVERTER_ID="ocd-georgii-aliud-retained-poem-to-tei"
CONVERTER_VERSION="1"
SOURCE="raw/openmgh/bsb00000720/tei/bsb00000720.xml"
SOURCE_SHA="2a096d80ae17e4f701fdce91585d77afb5d69e385167a46f45173e887dc38ce5"
TEI="{http://www.tei-c.org/ns/1.0}"
XML_ID="{http://www.w3.org/XML/1998/namespace}id"

def canonical(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()

def census(nodes):
    nodes=list(nodes)
    return dict(elements=len(nodes),attributes=sum(len(n.attrib) for n in nodes),
                tags=dict(sorted(Counter(n.tag.rsplit("}",1)[-1] for n in nodes).items())),
                text_characters=sum(len(n.text or "")+len(n.tail or "") for n in nodes))

def _convert(manifest):
    manifest.verify()
    raw=manifest.authority_path("retained-source").read_bytes()
    if sha256(raw).hexdigest()!=SOURCE_SHA: raise ValueError("retained XML drift")
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True,huge_tree=True))
    if root.getroottree().docinfo.doctype: raise ValueError("DOCTYPE forbidden")
    divisions=list(root.find(TEI+"text/"+TEI+"body")[0]); ab=divisions[2][0]
    if len(divisions)!=3 or len(ab)!=959 or ab[96].get(XML_ID)!="bsb00000720_00271_17" or ab[103].get(XML_ID)!="bsb00000720_00272_4":
        raise ValueError("literal second epitaph boundary drift")
    selected=etree.Element(TEI+"ab",attrib=dict(ab.attrib))
    for child in list(ab)[96:104]: selected.append(deepcopy(child))
    output=etree.Element(TEI+"TEI",nsmap={None:TEI[1:-1]}); output.set(XML_ID,WORK_ID)
    desc=etree.SubElement(etree.SubElement(output,TEI+"teiHeader"),TEI+"fileDesc")
    etree.SubElement(etree.SubElement(desc,TEI+"titleStmt"),TEI+"title").text=TITLE
    original=root.find(TEI+"teiHeader/"+TEI+"fileDesc")
    desc.append(deepcopy(original.find(TEI+"publicationStmt")))
    etree.SubElement(desc,TEI+"sourceDesc").append(deepcopy(original.find(TEI+"sourceDesc/"+TEI+"biblFull")))
    body=etree.SubElement(etree.SubElement(output,TEI+"text"),TEI+"body")
    etree.SubElement(body,TEI+"div",type="work",n=TITLE).append(selected)
    rows=[dict(ordinal=i,tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for i,n in enumerate(selected.iter())]
    accounting=dict(contract="ocd-georgii-aliud-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,
        source_selector="/tei:TEI/tei:text/tei:body/tei:div/tei:div[3]/tei:ab/*[position()>=97 and position()<=104]",
        selected_child_indexes=[96,103],assigned_census=census(selected.iter()),complete_document_census=census(root.iter()),crosswalk=rows,
        division_dispositions=[dict(ordinal=i+1,attributes=dict(d.attrib),census=census(d.iter()),disposition="second ALIUD epitaph only; shared heading and other poems outside body" if i==2 else "outside assigned work") for i,d in enumerate(divisions)],
        carrier_dispositions=[dict(first=0,last=88,disposition="other Carmina matter outside group18"),dict(first=89,last=89,disposition="shared triplex collection heading, context only"),dict(first=90,last=95,disposition="complete first epitaph outside assigned second poem"),dict(first=96,last=103,disposition="complete second ALIUD epitaph including internal page break"),dict(first=104,last=110,disposition="complete third TERTIUM epitaph outside assigned second poem"),dict(first=111,last=958,disposition="numbered19 and later Carmina outside assigned second poem")],
        source_metadata_disposition="Original publication/license and complete biblFull preserved in header; qualified second-poem title identifies membership without claiming whole triplex; original collection and author headings retained as source context in notice/profile.",
        declared_locator_dispositions={"bsb00000720_00271_10":"shared triplex heading, context outside body","bsb00000720_00271_17":"ALIUD second poem heading included","bsb00000720_00272_4":"complete final second-poem line included"},
        native_page_ids=[n.get(XML_ID) for n in selected.iter(TEI+"pb")],native_column_count=sum(1 for n in selected.iter(TEI+"cb")),
        verse_line_ids=[n.get(XML_ID) for n in selected if n.tag==TEI+"lb" and n.get(XML_ID)!="bsb00000720_00271_17"])
    profile=manifest.authority_path("profile").read_bytes()
    return {"content.tei.xml":etree.tostring(output,encoding="UTF-8",xml_declaration=True),"source-accountability.json":canonical(accounting),"provenance.json":profile,
            "README.source.md":manifest.authority_path("source-readme").read_bytes(),"unresolved.jsonl":b"".join(canonical(q) for q in json.loads(profile)["candidate_questions"])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION

def build_candidate(manifest,destination):
    return reconstruct(manifest,destination,_convert)
