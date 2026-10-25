"""Repair five source-located heading positions in the preexisting engwebpb TEI."""
from __future__ import annotations
from hashlib import sha256
import json,re
from zipfile import ZipFile
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage,SourceManifest
TEI='{http://www.tei-c.org/ns/1.0}'
NS={'t':'http://www.tei-c.org/ns/1.0'}
ORIGINAL_SHA='bc62d97cfcb51f8b3041e81ab7d3c17afb9c49f5b0fbd81092c9a0809ad82322'
EXPECTED=[(10,'1'),(2137,'42'),(3775,'73'),(4960,'90'),(6025,'107')]
def repair_body(raw:bytes,archive)->bytes:
    if sha256(raw).hexdigest()!=ORIGINAL_SHA:raise ValueError('engwebpb immutable input TEI differs')
    with ZipFile(archive) as z:lines=z.read('20-PSAengwebpb.usfm').decode('utf-8').splitlines()
    chapter=None;found=[]
    for number,line in enumerate(lines,1):
        if line.startswith('\\c '):chapter=line[3:].split(' ',1)[0]
        if line.startswith('\\ms1 '):found.append((number,chapter))
    if found!=EXPECTED:raise ValueError('engwebpb exact source heading/chapter intervals differ')
    document=etree.fromstring(raw,etree.XMLParser(huge_tree=True,load_dtd=False,resolve_entities=False,no_network=True))
    psalms=document.xpath('./t:text/t:body/t:div[@type="book"][@n="PSA"]',namespaces=NS)
    if len(psalms)!=1:raise ValueError('engwebpb one Psalms book required')
    book=psalms[0]
    for line,number in found:
        pointer=f'source-usfm:engwebpb/20-PSAengwebpb.usfm#line={line}'
        heads=book.xpath('.//t:head[@type="usfm-ms1"][@corresp=$p]',namespaces=NS,p=pointer)
        chapters=book.xpath('./t:div[@type="chapter"][@n=$n]',namespaces=NS,n=number)
        if len(heads)!=1 or len(chapters)!=1:raise ValueError('engwebpb exact source heading/chapter missing')
        wrapper=heads[0].getparent();chapter=chapters[0]
        if wrapper.tag!=TEI+'div' or wrapper.get('type')!='usfm-heading' or wrapper.getparent() is not book or book.index(wrapper)!=book.index(chapter)+1:raise ValueError('engwebpb original displaced-wrapper preimage differs')
        if not len(chapter) or chapter[0].tag!=TEI+'p' or len(chapter[0])!=1 or chapter[0][0].get('type')!='usfm-c-content':raise ValueError('engwebpb source chapter suffix preimage differs')
        if dict(wrapper.attrib)!={"type":"usfm-heading","n":f"ms1-{line}"} or len(wrapper)!=1 or wrapper.text is not None or wrapper.tail is not None or heads[0].tail is not None:raise ValueError("engwebpb empty wrapper preimage differs")
        chapter.insert(0,heads[0])
        book.remove(wrapper)
    return etree.tostring(document,encoding='UTF-8',xml_declaration=True,pretty_print=False)
def _convert(manifest:SourceManifest)->dict[str,bytes]:
    manifest.verify()
    original=CandidatePackage.load(manifest.authority_path('preexisting-v18-tei').parent)
    original.verify_integrity()
    result={name:original.member_bytes(name) for name in original.member_names if name!='manifest.json'}
    result['content.tei.xml']=repair_body(result['content.tei.xml'],manifest.authority_path('source-archive'))
    provenance=json.loads(result['provenance.json']);provenance['manifest_sha256']=manifest.sha256
    result['provenance.json']=(json.dumps(provenance,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
    return result
_convert.converter_id='ocd-engwebpb-existing-tei-five-heading-order-repair'
_convert.converter_version='1'
