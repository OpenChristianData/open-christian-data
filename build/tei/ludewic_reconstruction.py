"""Reconstruct the complete quoted Ludewic reply from its retained electronic carrier."""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from lxml import etree
from ocd_kernel.reconstruction.contract import reconstruct

WORK_ID="ludewic-reply-to-walram"
TITLE="Count Ludewic's Reply to Walram of Naumburg"
CONVERTER_ID="ocd-ludewic-retained-letter-to-tei"
CONVERTER_VERSION="1"
SOURCE="raw/openmgh/bsb00000829/tei/bsb00000829.xml"
SOURCE_SHA="cb35385e4e4ba87f80a002452a527527866322af7ccea7f23f366735e46df989"
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
    divisions=list(root.find(TEI+"text/"+TEI+"body")[0]); ab=divisions[3][0]
    if len(divisions)!=21 or len(ab)!=483 or ab[107].get(XML_ID)!="bsb00000829_00295_29" or ab[482].get(XML_ID)!="bsb00000829_00299_46":
        raise ValueError("literal Ludewic boundary drift")
    selected=etree.Element(TEI+"ab",attrib=dict(ab.attrib))
    for child in list(ab)[107:483]: selected.append(deepcopy(child))
    output=etree.Element(TEI+"TEI",nsmap={None:TEI[1:-1]}); output.set(XML_ID,WORK_ID)
    desc=etree.SubElement(etree.SubElement(output,TEI+"teiHeader"),TEI+"fileDesc")
    etree.SubElement(etree.SubElement(desc,TEI+"titleStmt"),TEI+"title").text=TITLE
    original=root.find(TEI+"teiHeader/"+TEI+"fileDesc")
    desc.append(deepcopy(original.find(TEI+"publicationStmt")))
    etree.SubElement(desc,TEI+"sourceDesc").append(deepcopy(original.find(TEI+"sourceDesc/"+TEI+"biblFull")))
    body=etree.SubElement(etree.SubElement(output,TEI+"text"),TEI+"body")
    etree.SubElement(body,TEI+"div",type="work",n=TITLE).append(selected)
    rows=[dict(ordinal=i,tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail,children=len(n)) for i,n in enumerate(selected.iter())]
    accounting=dict(contract="ocd-ludewic-accountability-v1",work_id=WORK_ID,source_sha256=SOURCE_SHA,
        source_selector="/tei:TEI/tei:text/tei:body/tei:div/tei:div[4]/tei:ab/*[position()>=108 and position()<=483]",
        selected_child_indexes=[107,482],assigned_census=census(selected.iter()),complete_document_census=census(root.iter()),crosswalk=rows,
        division_dispositions=[dict(ordinal=i+1,attributes=dict(d.attrib),census=census(d.iter()),disposition="selected literal letter only; surrounding narrative/reply excluded" if i==3 else "outside assigned work") for i,d in enumerate(divisions)],
        carrier_dispositions=[dict(first=0,last=14,disposition="narrative introduction outside Walram letter"),dict(first=15,last=89,disposition="separate quoted Walram letter excluded"),dict(first=90,last=106,disposition="narrative introduction and attribution outside Ludewic reply"),dict(first=107,last=482,disposition="complete quoted Ludewic reply")],
        source_metadata_disposition="Original publication/license and complete biblFull preserved in header; original volume title/editor and outer envelope retained as source context in notice/profile. Source narrative attributes sender Ludewic and dictator Herrand without assigning it as letter text.",
        declared_locator_dispositions={"bsb00000829_00295_16":"receipt narrative outside body","bsb00000829_00295_23":"dictation narrative outside body","bsb00000829_00295_29":"quoted response opening included","bsb00000829_00299_46":"complete closing line included"},
        empty_native_words=[dict(xml_id=n.get(XML_ID),attributes=dict(n.attrib),text=n.text) for n in selected.iter(TEI+"w") if n.text is None])
    profile=manifest.authority_path("profile").read_bytes()
    return {"content.tei.xml":etree.tostring(output,encoding="UTF-8",xml_declaration=True),"source-accountability.json":canonical(accounting),"provenance.json":profile,
            "README.source.md":manifest.authority_path("source-readme").read_bytes(),"unresolved.jsonl":b"".join(canonical(q) for q in json.loads(profile)["candidate_questions"])}

_convert.converter_id=CONVERTER_ID
_convert.converter_version=CONVERTER_VERSION

def build_candidate(manifest,destination):
    return reconstruct(manifest,destination,_convert)
