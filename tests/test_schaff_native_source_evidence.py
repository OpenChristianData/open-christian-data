"""Closed generic ThML evidence handoff and independent private-receipt checks."""
from copy import deepcopy
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document,verify_document
from ocd_kernel.projection.source_projection_evidence import project_evidence,observe_evidence
from ocd_kernel.projection.native_content import project_content,readable_content
from ocd_kernel.projection.native_content_check import verify_content
NS="{http://www.tei-c.org/ns/1.0}"
XML="{http://www.w3.org/XML/1998/namespace}"
CONTEXT=dict(identity=dict(work_id="fixture",textual_form_id="fixture-en",edition_id="fixture-edition"),language="en",representation_revision="fixture-v1",edition_title="Fixture",category="prose",_allow_acceptance_metadata=True)
def fixture():
    root=etree.fromstring(('<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="r"><teiHeader><fileDesc><titleStmt><title>Fixture</title></titleStmt><publicationStmt><p>Private</p></publicationStmt><notesStmt><note type="retained-ThML-header"><p><seg xml:id="h" type="retained-ThML-header"><seg xml:id="d" type="ThML-description">Header <hi xml:id="italic" rend="italic">credit</hi><lb xml:id="br"/></seg></seg></p></note></notesStmt><sourceDesc><p>Source</p></sourceDesc></fileDesc></teiHeader><text><body xml:id="b"><div xml:id="w" type="ThML-div1" n="Volume"><head xml:id="head" type="source-h2">Volume</head><p xml:id="p" rend="PFirst">Wording<index xml:id="x" indexName="globalSubject" n="Judaism"/></p></div></body></text></TEI>').encode())
    rows=[("r","ThML",[],"",1),("h","ThML.head",[],"r",1),("d","description",[],"h",1),("italic","i",[],"d",1),("br","br",[],"d",2),("b","ThML.body",[],"r",2),("w","div1",[["id","w"],["title","Volume"]],"b",1),("head","h2",[["id","head"]],"w",1),("p","p",[["id","p"],["class","PFirst"]],"w",2),("x","index",[["id","x"],["type","globalSubject"],["subject1","Judaism"]],"p",1)]
    stand=etree.SubElement(root,NS+"standOff");listing=etree.SubElement(stand,NS+"list",type="source-projection")
    for identifier,tag,attrs,parent,ordinal in rows:
        item=etree.SubElement(listing,NS+"item",n=identifier,corresp="#"+identifier)
        item.text=json.dumps(dict(source_key=identifier,source_element=tag,source_attributes=attrs,source_parent_key=parent,source_ordinal=ordinal))
    return root
def raw(root):return etree.tostring(root,encoding="utf-8",xml_declaration=True)
def verify(path,result):return verify_document(path,result["rows"],result["receipt"],**CONTEXT)
def test_complete_evidence_keeps_private_header_and_ledger_out_of_public_text(tmp_path,monkeypatch):
    path=tmp_path/"master.xml";path.write_bytes(raw(fixture()));result=project_document(path,**CONTEXT)
    assert len(result["rows"])==1 and result["rows"][0]["text"]=="Volume\n\nWording"
    assert sum(n["role"]=="machine-source-evidence" for n in result["receipt"]["inventory"])==16
    import ocd_kernel.projection.native_content as producer
    monkeypatch.setattr(producer,"project_content",lambda *a,**k:pytest.fail("producer called"));monkeypatch.setattr(producer,"readable_content",lambda *a:pytest.fail("renderer called"))
    assert verify(path,result)==[]
@pytest.mark.parametrize("mutation",["omit","order","parent","ordinal","target","duplicate-key","extra-field","nested-item","orphan-header","second-ledger"])
def test_unknown_or_corrupted_evidence_fails_both_independent_routes(mutation):
    doc=fixture();ledger=doc.find(NS+"standOff/"+NS+"list");item=ledger[-1]
    if mutation=="omit":ledger.remove(item)
    elif mutation=="order":ledger.insert(0,item)
    elif mutation in ("parent","ordinal","extra-field"):
        record=json.loads(item.text)
        if mutation=="parent":record["source_parent_key"]="w"
        elif mutation=="ordinal":record["source_ordinal"]=99
        else:record["extra"]="unknown"
        item.text=json.dumps(record)
    elif mutation=="target":item.set("corresp","#missing")
    elif mutation=="duplicate-key":item.text=item.text[:-1]+',"source_ordinal":99}'
    elif mutation=="nested-item":etree.SubElement(item,NS+"seg")
    elif mutation=="orphan-header":etree.SubElement(doc.find('.//'+NS+'seg'),NS+"seg")
    else:doc.find(NS+"standOff").append(deepcopy(ledger))
    with pytest.raises(PipelineError):project_evidence(ET.fromstring(raw(doc)))
    with pytest.raises(ValueError):observe_evidence(doc)
@pytest.mark.parametrize("mutation",["body-source-attribute","mapped-header-text","mapped-header-tail","comment-text","extra-comment","ledger-text-tail"])
def test_saved_receipt_rejects_shape_valid_private_evidence_changes(tmp_path,mutation,monkeypatch):
    doc=fixture();doc.addprevious(etree.Comment("retained prolog"));path=tmp_path/"master.xml";path.write_bytes(etree.tostring(doc.getroottree(),encoding="utf8",xml_declaration=True));result=project_document(path,**CONTEXT)
    if mutation=="body-source-attribute":
        item=doc.find(NS+"standOff/"+NS+"list")[-2];record=json.loads(item.text);record["source_attributes"][1][1]="OtherClass";item.text=json.dumps(record)
    elif mutation=="mapped-header-text":doc.find('.//'+NS+'seg').text="Changed"
    elif mutation=="mapped-header-tail":doc.find('.//'+NS+'hi').tail="Changed tail"
    elif mutation=="comment-text":doc.getprevious().text="Changed comment"
    elif mutation=="extra-comment":doc.addprevious(etree.Comment("extra"))
    else:doc.find(NS+"standOff/"+NS+"list")[-1].tail="\n"
    path.write_bytes(etree.tostring(doc.getroottree(),encoding="utf8",xml_declaration=True))
    monkeypatch.setattr("ocd_kernel.projection.native_content.project_content",lambda *a,**k:pytest.fail("producer called"))
    assert verify(path,result)
def test_inert_stylesheet_pi_comment_is_preserved(tmp_path):
    doc=fixture();doc.addprevious(etree.Comment('<?xml-stylesheet href="retained.xsl"?>'));path=tmp_path/"master.xml";path.write_bytes(etree.tostring(doc.getroottree(),encoding="utf8",xml_declaration=True));result=project_document(path,**CONTEXT)
    assert result["receipt"]["source_comments"][0]["text"]=='<?xml-stylesheet href="retained.xsl"?>'
    assert verify(path,result)==[]
@pytest.mark.parametrize("declaration",["<?xml-stylesheet href='active.xsl'?>","<!DOCTYPE TEI>","<!DOCTYPE TEI [<!ENTITY invented 'bad'>]>"])
def test_active_pi_and_dtd_fail_in_both_routes(tmp_path,declaration):
    path=tmp_path/"master.xml";path.write_bytes((declaration+etree.tostring(fixture(),encoding="unicode")).encode())
    with pytest.raises(PipelineError):project_document(path,**CONTEXT)
    assert verify_document(path,[],{},**CONTEXT)
def test_heading_classes_and_empty_subject_marker_are_literal_and_independently_checked():
    fragment=('<div xmlns="'+NS[1:-1]+'"><ab type="source-h4" rend="c21">Literal</ab><ab type="source-h6" rend="c33">Later</ab><index indexName="globalSubject" n="Judaism"/></div>').encode()
    content=project_content(ET.fromstring(fragment));text=readable_content(content)
    assert text=="Literal\n\nLater" and content["content"][0]["attributes"]["style"]=="c21"
    assert content["content"][2]["attributes"]=={"index_name":"globalSubject","number":"Judaism"}
    assert verify_content(fragment,content,text)==[]
    changed=deepcopy(content);changed["content"][2]["attributes"]["number"]="Changed";assert verify_content(fragment,changed,text)
    with pytest.raises(PipelineError):project_content(ET.fromstring(fragment.replace(b'globalSubject',b'invented')))

@pytest.mark.parametrize("mutation",["active-inroot-pi","ordinary-header-child"])
def test_active_pi_and_unknown_ordinary_header_still_fail(tmp_path,mutation):
    doc=fixture()
    if mutation=="active-inroot-pi":doc.find(NS+"teiHeader").append(etree.ProcessingInstruction("xml-stylesheet",'href="active.xsl"'))
    else:etree.SubElement(doc.find(NS+"teiHeader/"+NS+"fileDesc/"+NS+"titleStmt"),NS+"unknown")
    path=tmp_path/"master.xml";path.write_bytes(raw(doc))
    with pytest.raises(PipelineError):project_document(path,**CONTEXT)
    assert verify_document(path,[],{},**CONTEXT)
