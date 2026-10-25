"""Independent Watson reconciliation of raw XML and qualified LIB035 replay."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
from functools import lru_cache
from urllib.parse import quote
import base64,json
import xml.etree.ElementTree as ET
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage
ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'reports/_logs/watson-existing-install-20261003-v1'
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--r-a-watson'
MEMBERS=('watson-ra-expositor7','watson-ra-expositorjob','watson-ra-expositornum')
FILES=('watson_ra_expositor7.xml','watson_ra_expositorjob.xml','watson_ra_expositornum.xml')
@lru_cache(maxsize=1)
def retained():
 package=CandidatePackage.load(LOG/'retained-final-package')
 assert package.sha256=='685517f52f9be603117e42c1afe9d6bf2d20a95145c855b7cbb5b37971042605'
 assert sha256(package.member_bytes('content.tei.xml')).hexdigest()=='94c7f5a9b7c393dca2fd53e07d5f3a21f39c995cbe0266b776b6914d8c919f75'
 assert sha256(package.member_bytes('source-accountability.json')).hexdigest()=='33f458376acb0f0fa8c8bf6514d3ae46d2ae2dc9e26a13a269cb28abe0cbfb82'
 profile_bytes=(ROOT/'sources/commentaries/expositors-bible/lib035.reconstruction-profile.json').read_bytes()
 assert sha256(profile_bytes).hexdigest()=='3853db08494f46184368556bebdac41d1f65c17f51935da3d1d2d3f0b934b710'
 return etree.fromstring(package.member_bytes('content.tei.xml')),json.loads(package.member_bytes('source-accountability.json')),json.loads(profile_bytes)
def check(member):
 assert member in MEMBERS
 tree,account,profile=retained()
 raw=(ROOT/'raw/ccel/expositors-bible'/FILES[MEMBERS.index(member)]).read_bytes()
 source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
 nodes=[n for n in source.iter() if isinstance(n.tag,str)];ordinals={n:i for i,n in enumerate(nodes,1)};expected=[]
 def walk(node,parent,path,index):
  identity=member+f'-feature-{ordinals[node]:05d}'
  text=node.text or '';tail=node.tail or ''
  expected.append(dict(feature_id=identity,member_id=member,work_id=WORK,disposition='represented',tei_selector='#'+identity,tei_xml_id=identity,source_tag=node.tag,source_selector=path,source_attributes=dict(node.attrib),source_parent_ordinal=ordinals.get(parent),source_child_ordinal=index,source_direct_text=text,source_tail_text=tail,source_direct_text_sha256=sha256(text.encode()).hexdigest(),source_tail_text_sha256=sha256(tail.encode()).hexdigest()))
  counts=Counter()
  for i,child in enumerate((c for c in node if isinstance(c.tag,str)),1):
   counts[child.tag]+=1;walk(child,node,path+'/'+child.tag+'['+str(counts[child.tag])+']',i)
 walk(source,None,'/ThML[1]',1)
 rows=[r for r in account['crosswalk'] if r['member_id']==member]
 assert rows==expected,('Original full source crosswalk differs',member)
 divisions=[n for n in tree.iter(NS+'div') if n.get(XML+'id')==member];assert len(divisions)==1
 division=divisions[0];assert [n.tag for n in division]==[NS+'head',NS+'note',NS+'div']
 note=division[1]
 assert dict(note.attrib)=={'type':'exact-retained-source-bytes','subtype':'base64','n':sha256(raw).hexdigest()}
 assert base64.b64decode(note.text,validate=True)==raw and not len(note)
 carriers=list(division[2]);assert len(carriers)==len(expected)
 corrections=[r for r in profile['text_corrections'] if r['member_id']==member];observed=[]
 for block,wanted in zip(carriers,expected,strict=True):
  assert block.tag==NS+'ab' and dict(block.attrib)=={XML+'id':wanted['feature_id'],'type':'source-xml-element','subtype':wanted['source_tag'],'n':str(wanted['source_child_ordinal']),'corresp':'urn:source-xpath:'+quote(wanted['source_selector'],safe='')}
  assert not (block.text or '') and not (block.tail or '') and len(block)==2
  for segment,field,label in zip(block,('text','tail'),('direct-text','tail-text'),strict=True):
   literal=wanted['source_direct_text' if field=='text' else 'source_tail_text']
   assert segment.tag==NS+'seg' and dict(segment.attrib)=={'type':label} and not (segment.tail or '')
   recovered=segment.text or ''
   for choice in segment:
    selected=[r for r in corrections if r['source_selector']==wanted['source_selector'] and r['source_field']==field and r['start']==len(recovered)];assert len(selected)==1
    row=selected[0];fields=('member_id','source_selector','source_field','source_value_sha256','start','end','sic','corr','witness_url')
    correction_id=sha256('\\0'.join(str(row[k]) for k in fields).encode()).hexdigest()
    assert choice.tag==NS+'choice' and dict(choice.attrib)=={'corresp':'urn:ocd:source-text-correction:'+correction_id,'resp':row['witness_url']} and not (choice.text or '') and len(choice)==2
    sic,corr=choice
    assert (sic.tag,dict(sic.attrib),sic.text or '',sic.tail or '',len(sic))==(NS+'sic',{},row['sic'],'',0)
    assert (corr.tag,dict(corr.attrib),corr.text or '',corr.tail or '',len(corr))==(NS+'corr',{},row['corr'],'',0)
    assert row['source_value_sha256']==sha256(literal.encode()).hexdigest() and literal[row['start']:row['end']]==row['sic'] and row['end']-row['start']==len(row['sic'])
    recovered+=row['sic']+(choice.tail or '');observed.append(row)
   assert recovered==literal,('Old actual literal-reading inverse differs',wanted['feature_id'],field)
 assert sorted(json.dumps(r,sort_keys=True) for r in observed)==sorted(json.dumps(r,sort_keys=True) for r in corrections)
 return dict(status='original-source-graph-pass',member_id=member,source_sha256=sha256(raw).hexdigest(),source_bytes=len(raw),source_blob_exact=True,original_source_graph_fields=len(expected),old_carrier_count=len(carriers),old_actual_order_attributes_direct_and_tail_pass=True,original_sic_reading_inverse_equal=True,legacy_correction_count=len(observed),legacy_correction_rows=observed,original_member_c14n_sha256=sha256(etree.tostring(division,method='c14n',with_comments=True)).hexdigest(),historical_accounting_bytes_exact=True,historical_tei_bytes_exact=False,claim='Every raw source field, old flat carrier and correction source-field position independently reconciled; embedded raw bytes exact. Current historical producer replay is not dated historical TEI byte recovery. Flat old graph does not prove readable hierarchy. External correction witness bytes unavailable; no download or witness confirmation.')
if __name__=='__main__':
 rows=[check(m) for m in MEMBERS]
 (LOG/'original-source-scope-reconciliation.json').write_text(json.dumps(dict(status='pass',members=rows),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
 print(json.dumps(dict(status='pass',features=sum(r['original_source_graph_fields'] for r in rows),corrections=sum(r['legacy_correction_count'] for r in rows))))
