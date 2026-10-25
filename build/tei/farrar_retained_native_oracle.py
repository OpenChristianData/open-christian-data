"""Independent retained-source/actual-TEI oracle for the three Farrar witnesses.

The raw witness is parsed with stdlib ElementTree. Neither emitter nor producer
nor a private producer ledger supplies correctness expectations.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote,urlsplit,urljoin
import xml.etree.ElementTree as ET

from lxml import etree

from build.tei.farrar_original_scope import check as check_original_scope
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--frederic-w-farrar'
SCOPE=('Complete retained CCEL electronic XML witness for this separately acquired volume; '
 'not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. '
 'External image pixels were not acquired, inferred or visually reviewed.')
SOURCES={
 'farrar-expositor1kings':('farrar_expositor1kings.xml','b5bb6a2200528b3d3573aa373eaec2f7a827c1057b462c5d473eb231e812ca8d',('i','ii'),('vii','viii'),7024),
 'farrar-expositor2kings':('farrar_expositor2kings.xml','1827452772153d95bb8f5c8c56782b4b038b51f335e6339b2ac8e241dc7267fa',('i','ii'),('xliii','xliv','xlv','xlvi','xlvii'),9002),
 'farrar-expositordan':('farrar_expositordan.xml','6a851a9f4c0bf941745ce28b8a0c0da9b15f3a6568c089511b66d8bc10d1a67b',('i','ii'),('vi','vii'),7579),
}

# Exact observed fresh import inventories. These are import-time closures; all
# runtime/schema/source dependencies are separately frozen by installation.
ORACLE_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/farrar_original_scope.py build/tei/farrar_retained_native_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())
PRODUCER_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/farrar_retained_native_emitter.py build/tei/farrar_retained_native_prepare.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())


def import_closure(module='build.tei.farrar_retained_native_oracle', *, root=ROOT, extra_import=None):
 script = '''import importlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True);sys.path.insert(0,str(root));before=set(sys.modules)
importlib.import_module(sys.argv[2])
if len(sys.argv)>3:importlib.import_module(sys.argv[3])
paths=sorted({Path(m.__file__).resolve().relative_to(root).as_posix() for name,m in sys.modules.copy().items() if name not in before and getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(root)})
print(json.dumps(paths))'''
 arguments=[sys.executable,'-I','-B','-c',script,str(root),module]
 if extra_import:arguments.append(extra_import)
 observed=json.loads(subprocess.run(arguments,check=True,capture_output=True,text=True).stdout)
 expected=ORACLE_IMPORTS if module.endswith('_oracle') else PRODUCER_IMPORTS
 if tuple(observed)!=expected:raise ValueError('Farrar observed first-party import closure differs: '+repr(observed))
 records=[dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in observed]
 return sha256(_canonical(records)).hexdigest()


def _parse(raw:bytes)->ET.Element:
 return ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))


def _fields(node):
 return [(n.tag,dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in node.iter()]


@lru_cache(maxsize=1)
def _p5_schema():
 return etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))


def check(member_id:str,directory:Path)->dict:
 filename,pin,front,back,full_count=SOURCES[member_id]
 raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes()
 if sha256(raw).hexdigest()!=pin:raise ValueError('Retained source identity differs')
 original_scope=check_original_scope(member_id)
 form=WORK+'--'+member_id+'--retained-en';edition=WORK+'--'+member_id+'--ccel-electronic';acquisition_id=WORK+'--'+member_id+'--acquired'
 acquisition_path=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(acquisition_id+'.json')
 acquisition=json.loads((ROOT/acquisition_path).read_bytes())
 expected_url='https://www.ccel.org/ccel/farrar/'+member_id.removeprefix('farrar-')+'.html'
 if acquisition['acquisition_id']!=acquisition_id or acquisition['edition_id']!=edition or acquisition['route']!='born-digital' or acquisition['url']!=expected_url or acquisition['source_path']!='raw/ccel/expositors-bible/'+filename or acquisition['source_sha256']!=pin or acquisition['source_bytes']!=len(raw):raise ValueError('Independent acquired URI/source identity differs')
 if acquisition['retained_files'][0]['path']!=acquisition['source_path'] or acquisition['retained_files'][0]['sha256']!=pin or acquisition['retained_files'][0]['bytes']!=len(raw):raise ValueError('Independent retained acquisition file binding differs')
 source=_parse(raw);body=source.find('ThML.body');head=source.find('ThML.head')
 if body is None or head is None:raise ValueError('Complete source head/body required')
 if sum(isinstance(n.tag,str) for n in source.iter())!=full_count:raise ValueError('Whole retained source census differs')
 # Secondary parser corroborates every source tree field, before any TEI comparison.
 lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 left=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in source.iter()]
 right=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in lsource.iter()]
 if left!=right:raise ValueError('Independent source parser corroboration differs')
 path=directory/'content.tei.xml';candidate=_parse(path.read_bytes());actual=candidate.find(NS+'text')
 if candidate.tag!=NS+'TEI' or dict(candidate.attrib)!={XML+'id':member_id} or [n.tag for n in candidate]!=[NS+'teiHeader',NS+'text'] or (candidate.text or '') or (candidate.tail or '') or any(n.tail for n in candidate):raise ValueError('Actual complete outer TEI readable envelope differs')
 if actual is None:raise ValueError('Actual candidate text absent')
 ts=candidate.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt')
 creators=head.findall('.//DC.Creator')
 header_values=[('title',head.findtext('.//DC.Title')),('author',next(n.text for n in creators if n.get('sub')=='Author' and n.get('scheme')=='short-form')),('editor',next(n.text for n in creators if n.get('sub')=='Editor' and n.get('scheme')=='short-form'))]
 if ts is None or [(n.tag,n.text) for n in ts] != [(NS+t,v) for t,v in header_values]:raise ValueError('Primary title/author/editor header identity differs')
 expected=ET.Element(NS+'text',{XML+'lang':'en'})
 expected.set(XML+'space',body.get(XML+'space'))
 regions={p:ET.SubElement(expected,NS+p,{XML+'id':member_id+'-'+p}) for p in ('front','body','back')}
 regions['front'].text=body.text
 source_ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 source_records=[];source_to_tei={};join_events=[]
 basic={'div1':'div','div2':'div','div3':'div','div4':'div','p':'p','h1':'p','h2':'p','h3':'p','h4':'p','h5':'p','h6':'p',
 'i':'hi','b':'hi','strong':'hi','small':'hi','big':'hi','em':'hi','cite':'hi','sub':'hi','sup':'hi',
 'br':'lb','pb':'pb','note':'note','scripRef':'ref','scripCom':'milestone','insertIndex':'milestone','hr':'milestone',
 'span':'seg','verse':'lg','l':'l','blockquote':'quote','div':'quote','ul':'list','li':'item','table':'table','tr':'row','td':'cell','img':'figure','a':'ref','pre':'ab'}
 renders={'i':'italic','b':'bold','strong':'bold','small':'small','big':'large','em':'emphasis','cite':'source-citation','sub':'subscript','sup':'superscript'}
 rend_tags={'div','p','hi','seg','quote','lg','l','list','item','table','cell','ref','note','lb','milestone','anchor','ab'}
 style_tags={'div','p','hi','seg','table','cell','milestone','ab'}
 def join(parent,value,source_path,reason):
  if value is not None:
   carrier=parent[-1] if len(parent) else parent
   field='tail' if len(parent) else 'text'
   setattr(carrier,field,(getattr(carrier,field) or '')+value)
   join_events.append(dict(source_path=source_path,reason=reason,carrier_id=carrier.get(XML+'id'),field=field,value=value))
 def observe(node,parent,source_path):
  ordinal=len(source_records)+1
  source_records.append(dict(ordinal=ordinal,source_path=source_path,source_parent_path=source_path[:-1],source_child_index=source_path[-1],
   source_tag=node.tag if isinstance(node.tag,str) else '#comment',source_attributes=dict(node.attrib),source_text=node.text,source_tail=node.tail))
  record=source_records[-1]
  if node.tag is ET.Comment:
   if (node.tail or '').strip():raise ValueError('Unexpected visible comment tail')
   record.update(disposition='source-comment-ledger-exact-whitespace-join',tei_parent_id=parent.get(XML+'id'),tei_preceding_child_index=len(parent)-1)
   join(parent,node.tail,source_path,'administrative-comment');return
  if not isinstance(node.tag,str):raise ValueError('Unexpected source body PI')
  if node.tag=='tbody':
   if parent.tag!=NS+'table' or (node.text or '').strip() or (node.tail or '').strip():raise ValueError('Textual tbody adaptation not admitted')
   record.update(disposition='source-tbody-row-flattening',tei_parent_id=parent.get(XML+'id'),tei_start_child_index=len(parent))
   join(parent,node.text,source_path,'tbody-direct')
   for i,c in enumerate(node):observe(c,parent,source_path+[i])
   join(parent,node.tail,source_path,'tbody-tail');return
  if node.tag not in basic:raise ValueError('Unmapped primary source role')
  tag=basic[node.tag];identity=member_id+'-'+node.get('id') if node.get('id') else f'{member_id}-feature-{ordinal:06d}'
  attrs={XML+'id':identity}
  if node.tag in {'div1','div2','div3','div4'}:
   attrs['type']='source-'+node.tag
   if node.get('title'):attrs['n']=node.get('title')
  if node.tag=='div':
   if node.get('class')=='Index':tag='div';attrs['type']='source-index'
   else:
    attrs['type']='source-div'
    if node.get('title'):attrs['n']=node.get('title')
  if re.fullmatch('h[1-6]',node.tag):attrs['rend']='source-'+node.tag
  if node.tag=='pre':attrs['rend']='source-preformatted';attrs[XML+'space']=node.get(XML+'space')
  if node.tag in renders:attrs['rend']=renders[node.tag]
  if node.tag=='span':attrs['type']='thml-span'
  if node.tag=='verse':attrs['type']='source-stanza'
  if node.tag=='blockquote':attrs['type']='source-blockquote'
  if node.tag=='a':
   href=node.get('href')
   if href is None:tag='seg' if node.text or len(node) else 'anchor';attrs['type']='source-anchor'
   elif href.startswith('#'):
    if href[1:] not in source_ids:tag='seg';attrs.update(type='source-unresolved-link',n=href)
    else:attrs['target']='#'+member_id+'-'+href[1:]
   else:
    attrs['target']=href
    if not urlsplit(href).scheme:attrs[XML+'base']=acquisition['url']
  if node.tag=='scripRef' and node.get('osisRef'):attrs['target']=node.get('osisRef')
  if node.tag=='scripRef' and node.get('passage') is not None:attrs['n']=node.get('passage')
  if node.tag in {'scripCom','insertIndex','hr'}:
   attrs['unit']='horizontal-rule' if node.tag=='hr' else node.tag
   label=node.get('passage') if node.tag=='scripCom' else node.get('type') if node.tag=='insertIndex' else None
   if label is not None:attrs['n']=label
   if node.get('osisRef') is not None:attrs['corresp']=node.get('osisRef')
   if node.tag=='scripCom' and node.get('type') is not None:attrs['type']=node.get('type')
  if node.tag=='br':attrs['type']='source-br'
  if node.tag=='pb' and node.get('n') is not None:attrs['n']=node.get('n')
  if node.tag=='note':
   for k in ('n','place','type'):
    if node.get(k) is not None:attrs[k]=node.get(k)
   if node.get('anchored') is not None:attrs['anchored']={'yes':'true','no':'false'}.get(node.get('anchored'),node.get('anchored'))
  if node.tag=='td':
   for k,mapped in [('colspan','cols'),('rowspan','rows')]:
    if node.get(k) is not None:attrs[mapped]=node.get(k)
  if node.tag=='table':
   for k in ('rows','cols'):
    if node.get(k) is not None:attrs[k]=node.get(k)
   if node.get('summary'):attrs['n']=node.get('summary')
  rend=[attrs['rend']] if 'rend' in attrs else []
  if node.get('class') and tag in rend_tags:rend.append('source-class-'+quote(node.get('class'),safe='-_.'))
  if node.get('dir') and tag in rend_tags:rend.append('source-dir-'+node.get('dir'))
  if node.get('style'):
   if tag in style_tags:attrs['style']=node.get('style')
   elif tag in rend_tags:rend.append('source-style-'+quote(node.get('style'),safe='-_.'))
  if rend:attrs['rend']=' '.join(rend)
  if node.tag=='img':
   annotations=[f'urn:ccel:source-img:{k}:{quote(node.get(k),safe="-_.")}' for k in ('width','height','align','class','style','border') if node.get(k) is not None]
   if annotations:attrs['ana']=' '.join(annotations)
  out=ET.SubElement(parent,NS+tag,attrs);out.text=node.text;out.tail=node.tail;source_to_tei[tuple(source_path)]=out
  record.update(disposition='native-element',tei_id=identity,tei_tag=tag,tei_attributes=attrs,
   tei_parent_id=parent.get(XML+'id'),tei_child_index=len(parent)-1,
   attribute_disposition='semantic native attributes plus complete original attributes in reversible source ledger')
  if node.tag=='img':
   ET.SubElement(out,NS+'graphic',{'url':node.get('src')})
   for k,t in [('alt','figDesc'),('title','label')]:
    if node.get(k) is not None:ET.SubElement(out,NS+t).text=node.get(k)
  for i,c in enumerate(node):observe(c,out,source_path+[i])
 current='front'
 for i,node in enumerate(body):
  if isinstance(node.tag,str):current='front' if node.get('id') in front else 'back' if node.get('id') in back else 'body'
  observe(node,regions[current],[i])
 if _fields(expected)!=_fields(actual):
  for i,(a,b) in enumerate(zip(_fields(expected),_fields(actual))):
   if a!=b:raise ValueError(f'Actual TEI/source node fields or attachment differ at ordered node {i}: {a[:2]} != {b[:2]}')
  raise ValueError('Actual TEI/source node census differs')
 account=json.loads((directory/'source-accountability.json').read_bytes())
 if account['source_sha256']!=pin or account['member_id']!=member_id or account['source_body_tag']!=body.tag or account['source_body_attributes']!=body.attrib or account['source_body_text']!=body.text or account['source_body_tail']!=body.tail or account['source_root_attributes']!=source.attrib or account['source_path']!='raw/ccel/expositors-bible/'+filename:raise ValueError('Actual source accounting envelope differs')
 if account['source_root_text']!=source.text or account['source_head_tail']!=head.tail or account['source_uri_acquisition_path']!=acquisition_path.as_posix() or account['source_uri_acquisition_sha256']!=sha256((ROOT/acquisition_path).read_bytes()).hexdigest() or account['source_uri_base']!=expected_url or account['original_package_sha256']!='a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2' or account['original_member_c14n_sha256']!=original_scope['original_member_c14n_sha256']:raise ValueError('Original package/acquired context/source outer field accounting differs')
 restored_head=_parse(account['source_head_xml'].encode());restored_head.tail=head.tail
 if _fields(restored_head)!=_fields(head):raise ValueError('Exact complete source head inverse differs')
 relative_links=0;query_links=0
 for record in source_records:
  if record['source_tag']=='a' and (href:=record['source_attributes'].get('href')) is not None and not href.startswith('#') and not urlsplit(href).scheme:
   real=source_to_tei[tuple(record['source_path'])]
   if urljoin(expected_url,href)!=urljoin(real.get(XML+'base',''),real.get('target','')):raise ValueError('Actual native reference resolution differs from acquired source context')
   relative_links+=1;query_links+=bool(urlsplit(href).query)
 root_ids=[n.get('id') for n in body if isinstance(n.tag,str)]
 expected_regions={p:[n.get('id') for n in body if isinstance(n.tag,str) and ('front' if n.get('id') in front else 'back' if n.get('id') in back else 'body')==p] for p in regions}
 if account['root_ids_in_order']!=root_ids or account['root_disposition']!=expected_regions:raise ValueError('Source root/region accounting differs')
 if len(account['features'])!=len(source_records):raise ValueError('Source account census differs')
 if account['feature_count']!=len(source_records) or account['administrative_comment_count']!=sum(r['source_tag']=='#comment' for r in source_records):raise ValueError('Declared feature/administration count differs')
 for actual_record,expect_record in zip(account['features'],source_records,strict=True):
  if any(actual_record.get(k)!=v for k,v in expect_record.items()):raise ValueError('Independent source field or actual-TEI binding accounting differs')
 # Actual native fields were checked above; restore original source direct/tail
 # by removing ONLY the independently derived whitespace joins, then restore
 # independently verified omitted administrative comments and tbody wrappers.
 native_by_id={n.get(XML+'id'):n for n in actual.iter() if n.get(XML+'id')}
 extra={}
 for event in join_events:extra[(event['carrier_id'],event['field'])]=extra.get((event['carrier_id'],event['field']),'')+event['value']
 restored=ET.Element(body.tag,body.attrib);restored.text=body.text;restored.tail=body.tail;nodes={():restored}
 for record in source_records:
  key=tuple(record['source_path']);tag=record['source_tag']
  n=ET.Comment(record['source_text']) if tag=='#comment' else ET.Element(tag,record['source_attributes'])
  if key in source_to_tei:
   real=native_by_id[source_to_tei[key].get(XML+'id')]
   for field in ('text','tail'):
    value=getattr(real,field) or '';suffix=extra.get((real.get(XML+'id'),field),'')
    if suffix:
     if not value.endswith(suffix):raise ValueError('Actual whitespace join inverse differs')
     value=value[:-len(suffix)]
    original=record['source_'+field]
    if value!=(original or ''):raise ValueError('Actual native source direct/tail inverse differs')
    setattr(n,field,None if original is None else value)
  else:n.text=record['source_text'];n.tail=record['source_tail']
  nodes[key[:-1]].append(n);nodes[key]=n
 if ET.canonicalize(ET.tostring(restored,encoding='unicode'),with_comments=True)!=ET.canonicalize(ET.tostring(body,encoding='unicode'),with_comments=True):raise ValueError('Actual-TEI-backed full source body inverse differs')
 # Verify source head fields and visible primary metadata from raw, separately.
 lhead=lsource.find('ThML.head');records=account['source_head_records']
 if len(records)!=len(list(lhead.iter())):raise ValueError('Source head census differs')
 visible=candidate.findall('.//'+NS+'note[@type="retained-source-head-field"]')
 expected_visible=[];expected_comments=[];ordered_head_notes=[]
 for ordinal,(n,r) in enumerate(zip(lhead.iter(),records,strict=True),1):
  source_path=lsource.getroottree().getpath(n)
  if isinstance(n.tag,str):
   fields=dict(ordinal=ordinal,kind='element',tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail,source_xpath=source_path)
   if any(r.get(k)!=v for k,v in fields.items()):raise ValueError('Source header accounting differs')
   if (n.text or '').strip() or n.attrib:
    value='Source field '+source_path+': '+json.dumps(dict(attributes=dict(n.attrib),text=n.text),ensure_ascii=False,sort_keys=True)
    expected_visible.append((str(ordinal),value))
    ordered_head_notes.append(('retained-source-head-field',str(ordinal),value))
  else:
   value='Retained source head comment: '+(n.text or '')
   if r.get('ordinal')!=ordinal or r.get('kind')!='comment' or r.get('source_xpath')!=source_path or r.get('text')!=n.text or r.get('tail')!=n.tail or r.get('visible_header_note_text')!=value:raise ValueError('Source head comment differs')
   expected_comments.append((str(ordinal),value))
   ordered_head_notes.append(('retained-source-head-comment',str(ordinal),value))
 if [(n.get('n'),n.text) for n in visible]!=expected_visible:raise ValueError('Visible primary header fields differ')
 if [(n.get('n'),n.text) for n in candidate.findall('.//'+NS+'note[@type="retained-source-head-comment"]')]!=expected_comments:raise ValueError('Visible source header rights comment differs')
 prolog=[dict(node_kind='comment' if n.tag is etree.Comment else 'pi',target=n.target if n.tag is etree.PI else None,text=n.text,tail=n.tail) for n in reversed(list(lsource.itersiblings(preceding=True)))]
 if account['source_prolog']!=prolog:raise ValueError('Source prolog directive/rights evidence differs')
 notes=candidate.findall('.//'+NS+'note[@type="retained-source-prolog"]')
 expected_notes=[(str(i),'Retained source prolog '+str(i)+': '+json.dumps(n,ensure_ascii=False,sort_keys=True)) for i,n in enumerate(prolog,1)]
 if [(n.get('n'),n.text) for n in notes]!=expected_notes:raise ValueError('Visible source prolog rights/directives differ')
 raw_prolog=raw[:raw.index(b'<ThML>')].decode('utf-8')
 if account['raw_source_prolog']!=raw_prolog:raise ValueError('Exact literal raw source prolog differs')
 expected_header=ET.Element(NS+'teiHeader');fd=ET.SubElement(expected_header,NS+'fileDesc');ts_expected=ET.SubElement(fd,NS+'titleStmt')
 for tag,value in header_values:ET.SubElement(ts_expected,NS+tag).text=value
 pub=ET.SubElement(fd,NS+'publicationStmt');ET.SubElement(pub,NS+'p').text='Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
 desc=ET.SubElement(fd,NS+'sourceDesc');qualification=ET.SubElement(desc,NS+'bibl');ET.SubElement(qualification,NS+'note',{'type':'source-limitations'}).text=SCOPE
 bibliography=ET.SubElement(desc,NS+'bibl');ET.SubElement(bibliography,NS+'title').text=header_values[0][1]
 for kind,ordinal,value in ordered_head_notes:ET.SubElement(bibliography,NS+'note',{'type':kind,'n':ordinal}).text=value
 ET.SubElement(bibliography,NS+'note',{'type':'retained-exact-source-prolog'}).text=raw_prolog
 for r in source_records:
  if r['source_tag']=='#comment':
   value='Retained source body administrative comment '+str(r['source_path'])+': '+json.dumps(dict(text=r['source_text'],tail=r['source_tail']),ensure_ascii=False,sort_keys=True)
   ET.SubElement(bibliography,NS+'note',{'type':'retained-source-body-comment','n':str(r['ordinal'])}).text=value
 for ordinal,value in expected_notes:ET.SubElement(bibliography,NS+'note',{'type':'retained-source-prolog','n':ordinal}).text=value
 if _fields(expected_header)!=_fields(candidate.find(NS+'teiHeader')):raise ValueError('Complete actual header fields/order/readable envelope differs')
 _p5_schema().assertValid(etree.parse(str(path)))
 ids=[n.get(XML+'id') for n in candidate.iter() if n.get(XML+'id')]
 if len(ids)!=len(set(ids)):raise ValueError('Actual TEI duplicate IDs')
 for n in candidate.iter(NS+'ref'):
  target=n.get('target','')
  if target.startswith('#') and target[1:] not in ids:raise ValueError('Actual TEI local reference closure differs')
 result=dict(status='pass',member_id=member_id,source_sha256=pin,tei_sha256=sha256(path.read_bytes()).hexdigest(),whole_source_elements=full_count,
  source_body_nodes=len(source_records),comments_ledger_retained=sum(r['source_tag']=='#comment' for r in source_records),
  actual_native_text_fields_order_ownership_pass=True,actual_native_attribute_roles_pass=True,actual_tei_backed_source_body_inverse_pass=True,
  independently_checked_whitespace_joins=len(join_events),source_head_visible_fields=len(visible),source_prolog_visible_fields=len(notes),
  table_count=sum(n.tag=='table' for n in body.iter()),preformatted_count=sum(n.tag=='pre' for n in body.iter()),note_count=sum(n.tag=='note' for n in body.iter()),relative_nonfragment_links=relative_links,relative_query_links=query_links,source_context_resolved_links='pass',original_scope=original_scope,p5='pass',local_links='closed',
  limitations=['External image pixels not retained or visually reviewed','Human acceptance not recorded','No print collation','Rights/publication unresolved','Volume XML scope only; author/series completeness open'])
 return result


def _oracle(source:SourceManifest,candidate:CandidatePackage)->dict:
 source.verify();candidate.verify_integrity()
 member=source.record['source_id'].removeprefix('ccel-farrar-retained-native-').removesuffix('-v1')
 if member not in SOURCES or candidate.manifest['status']!='nonaccepted' or candidate.manifest['converter']!=source.record['converter']:raise ValueError('Candidate source/converter binding differs')
 result=check(member,candidate.path)
 if source.authority_path('retained-thml').read_bytes()!=(ROOT/'raw/ccel/expositors-bible'/SOURCES[member][0]).read_bytes():raise ValueError('Candidate retained authority differs')
 profile=json.loads(source.authority_path('member-profile').read_bytes());policy=json.loads(source.authority_path('member-policy').read_bytes())
 if profile['contract']!='ocd-farrar-existing-native-profile-v1' or profile['work_id']!=WORK or profile['member_id']!=member or profile['source']['sha256']!=result['source_sha256'] or profile['original_member_c14n_sha256']!=result['original_scope']['original_member_c14n_sha256'] or profile['source_census']!={k:result[k] for k in ('whole_source_elements','source_body_nodes','note_count','table_count','preformatted_count','relative_nonfragment_links','relative_query_links')} or policy['contract']!='ocd-farrar-independent-native-policy-v1' or policy['member_id']!=member:raise ValueError('Declared member profile/policy differs from actual complete source proof')
 account=json.loads(candidate.member_bytes('source-accountability.json'))
 provenance=json.loads(candidate.member_bytes('provenance.json'));converter=source.record['converter']
 permission=source.authority_path('permission').read_bytes();emitter=source.authority_path('local-native-emitter').read_bytes()
 legacy='All three existing Farrar members are recovered from the exact historical LIB-033 package. Their flat feature representation requires the present source-backed readable hierarchy repair; original package and raw witness bytes remain exact.'
 expected_provenance=dict(status='nonaccepted',work_id=WORK,member_id=member,source_path=account['source_path'],source_sha256=result['source_sha256'],source_bytes=result['original_scope']['source_bytes'],scope=SCOPE,legacy_basis=legacy,original_package_sha256='a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2',original_member_c14n_sha256=result['original_scope']['original_member_c14n_sha256'],source_uri_acquisition_path=account['source_uri_acquisition_path'],source_uri_acquisition_sha256=account['source_uri_acquisition_sha256'],source_uri_base=account['source_uri_base'],producer=dict(id=converter['id'],version=converter['version'],implementation_path=converter['implementation_path'],implementation_sha256=converter['implementation_sha256'],emitter_path='build/tei/farrar_retained_native_emitter.py',emitter_sha256=sha256(emitter).hexdigest(),recipe='Exact acquired raw XML plus preserved historical six-member package; bounded existing-source native hierarchy reconstruction using declared member region and attribute policies'),permission_path='sources/commentaries/expositors-bible/ccel-permission.md',permission_sha256=sha256(permission).hexdigest(),emitter_sha256=sha256(emitter).hexdigest(),human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
 if provenance!=expected_provenance:raise ValueError('Exact current producer/source/original-package/permission provenance differs')
 if candidate.member_bytes('README.source.md')!=source.authority_path('source-local-attribution-readme').read_bytes() or 'must not be sold' not in candidate.member_bytes('README.source.md').decode('utf-8'):raise ValueError('Bound human-visible credit/restriction notice differs')
 if json.loads(candidate.member_bytes('unresolved.jsonl'))!=dict(id=member+'-human-rights-print-assets',status='unresolved',detail=SCOPE):raise ValueError('Exact unresolved stronger-claim record differs')
 record=dict(status='pass',oracle_id=_oracle.oracle_id,oracle_version=_oracle.oracle_version,
  implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=import_closure(),
  runtime=_runtime_binding(),source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,
  profile_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='complete-source-feature-profile'),
  package_schema_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='candidate-package-schema'),
  source_sha256=result['source_sha256'],xsd_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='tei-validation-schema'),
  policy_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='independent-validation-policy'),findings=[json.dumps(result,sort_keys=True)])
 record['result_sha256']=sha256(_canonical(record)).hexdigest();return record


_oracle.oracle_id='ocd-farrar-retained-native-independent-oracle'
_oracle.oracle_version='1'


if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);args=p.parse_args()
 for member in SOURCES:print(json.dumps(check(member,args.directory/member),sort_keys=True),flush=True)
