"""Independently reconcile original Farrar feature scope to acquired XML bytes."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
from functools import lru_cache
import base64,json
import xml.etree.ElementTree as ET
from urllib.parse import quote
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage
ROOT=Path(__file__).resolve().parents[2]
LOG=ROOT/'reports/_logs/farrar-existing-install-20261003-v1'
XML='{http://www.w3.org/XML/1998/namespace}';NS='{http://www.tei-c.org/ns/1.0}'
@lru_cache(maxsize=1)
def retained():
 package=CandidatePackage.load(LOG/'retained-final-package')
 assert package.sha256=='a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2'
 assert sha256(package.member_bytes('content.tei.xml')).hexdigest()=='2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134'
 return etree.fromstring(package.member_bytes('content.tei.xml')),json.loads(package.member_bytes('source-accountability.json'))
def check(member):
 tree,account=retained();source_record=account['retained_source_bytes'][member]
 raw=(ROOT/'raw/ccel/expositors-bible'/(member.replace('farrar-','farrar_')+'.xml')).read_bytes()
 assert base64.b64decode(source_record['base64'],validate=True)==raw
 assert source_record['bytes']==len(raw) and source_record['sha256']==sha256(raw).hexdigest()
 source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)));nodes=[n for n in source.iter() if isinstance(n.tag,str)];ordinals={n:i for i,n in enumerate(nodes,1)};expected=[]
 def walk(node,parent,path,index):
  ordinal=ordinals[node]
  expected.append(dict(feature_id=member+f'-feature-{ordinal:05d}',member_id=member,source_tag=node.tag,source_selector=path,source_attributes=dict(node.attrib),source_parent_ordinal=ordinals.get(parent),source_child_ordinal=index,source_direct_text=node.text or '',source_tail_text=node.tail or ''))
  counts=Counter()
  for i,child in enumerate((c for c in node if isinstance(c.tag,str)),1):counts[child.tag]+=1;walk(child,node,path+'/'+child.tag+'['+str(counts[child.tag])+']',i)
 walk(source,None,'/ThML[1]',1)
 observed=[r for r in account['crosswalk'] if r['member_id']==member]
 assert len(observed)==len(expected)
 for actual,wanted in zip(observed,expected,strict=True):
  assert all(actual.get(k)==v for k,v in wanted.items()),('Historical source graph field drift',wanted['feature_id'],{k:(actual.get(k),v) for k,v in wanted.items() if actual.get(k)!=v})
  assert actual['source_direct_text_sha256']==sha256(wanted['source_direct_text'].encode()).hexdigest()
  assert actual['source_tail_text_sha256']==sha256(wanted['source_tail_text'].encode()).hexdigest()
  assert actual['tei_selector']=='#'+wanted['feature_id'] and actual['tei_xml_id']==wanted['feature_id']
  assert actual['work_id']=='expositors-bible--frederic-w-farrar' and actual['disposition']=='represented'
 original=[n for n in tree.iter(NS+'div') if n.get(XML+'id')==member];assert len(original)==1
 carriers=list(original[0].iter(NS+'ab'))
 assert len(carriers)==len(expected)
 for block,wanted in zip(carriers,expected,strict=True):
  assert dict(block.attrib)=={XML+'id':wanted['feature_id'],'type':'source-xml-element','subtype':wanted['source_tag'],'n':str(wanted['source_child_ordinal']),'corresp':'urn:source-xpath:'+quote(wanted['source_selector'],safe='')}
  assert not (block.text or '') and not (block.tail or '') and len(block)==2
  for seg,kind,value in zip(block,('direct-text','tail-text'),(wanted['source_direct_text'],wanted['source_tail_text']),strict=True):
   assert seg.tag==NS+'seg' and dict(seg.attrib)=={'type':kind} and (seg.text or '')==value and not (seg.tail or '') and not len(seg)
 return dict(member_id=member,status='original-source-graph-pass',source_sha256=sha256(raw).hexdigest(),source_bytes=len(raw),source_blob_exact=True,original_source_graph_fields=len(expected),old_carrier_count=len(carriers),old_actual_order_attributes_direct_and_tail_pass=True,original_member_c14n_sha256=sha256(etree.tostring(original[0],method='c14n',with_comments=True)).hexdigest(),claim='Exact acquired bytes, every original source crosswalk field, and every ordered old flat carrier checked independently. Original hierarchy and attributes are encoded by the crosswalk; old flat carriers do not prove native readable hierarchy.')
if __name__=='__main__':
 rows=[check(m) for m in ('farrar-expositor1kings','farrar-expositor2kings','farrar-expositordan')]
 (LOG/'original-source-scope-reconciliation.json').write_text(json.dumps(dict(status='pass',members=rows),sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
