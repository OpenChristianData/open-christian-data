"""Independent retained-source/actual-TEI oracle for the one First Samuel witness.

The raw witness is parsed with stdlib ElementTree. Neither emitter nor producer
nor a private producer ledger supplies correctness expectations.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlsplit, urljoin
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--william-g-blaikie'
SCOPE='Complete retained CCEL electronic XML witness for the separately titled First Book of Samuel commentary, Toronto 1888. One complete authored work; Second Samuel and Joshua excluded; not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. This XML witness contains no image elements. Source layout is not a print or universal typography claim.'
LEGACY='The selected First Samuel member of a frozen qualified current-authority LIB036 converter replay is independently reconciled against its complete current raw source. The inaccessible September 11 package was not recovered, and historical TEI/accounting byte equality or historical oracle pass is not claimed. The historical profile has no First Samuel correction rows. All original raw readings remain in the readable body.'
CORRECTION_DISPOSITION='Original raw source readings retained unchanged in native body. The historical LIB036 profile has zero First Samuel correction rows; no sic/corr annotations or witness correction claims apply to this selected work.'
SOURCES={'blaikie-expositor8': ('blaikie_expositor8.xml', 'b46bd6cb856df0819dedc06b23a657f7763b49501248db63ce762585d67603d4', ('i',), ('xl',), 2153)}

# Exact observed fresh import inventories. These are import-time closures; all
# runtime/schema/source dependencies are separately frozen by installation.
ORACLE_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/blaikie_first_samuel_retained_native_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())
PRODUCER_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/blaikie_first_samuel_retained_native_emitter.py build/tei/blaikie_first_samuel_retained_native_prepare.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())


def import_closure(module='build.tei.blaikie_first_samuel_retained_native_oracle', *, root=ROOT, extra_import=None):
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
 if tuple(observed)!=expected:raise ValueError('First Samuel observed first-party import closure differs: '+repr(observed))
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
 source=_parse(raw);body=source.find('ThML.body');head=source.find('ThML.head')
 if body is None or head is None:raise ValueError('Complete source head/body required')
 if sum(isinstance(n.tag,str) for n in source.iter())!=full_count:raise ValueError('Whole retained source census differs')
 # Secondary parser corroborates every source tree field, before any TEI comparison.
 lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 left=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in source.iter()]
 right=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in lsource.iter()]
 if left!=right:raise ValueError('Independent source parser corroboration differs')
 path=directory/'content.tei.xml';candidate=_parse(path.read_bytes());actual=candidate.find(NS+'text')
 if actual is None or candidate.get(XML+'id')!=member_id+'--candidate' or candidate.attrib!={XML+'id':member_id+'--candidate'} or [n.tag for n in candidate]!=[NS+'teiHeader',NS+'text'] or (candidate.text or '') or (candidate.tail or ''):raise ValueError('Actual candidate identity/envelope differs')
 ts=candidate.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt')
 creators=head.findall('.//DC.Creator')
 header_values=[('title',head.findtext('.//DC.Title')),('author',next(n.text for n in creators if n.get('sub')=='Author' and n.get('scheme')=='short-form')),('editor',next(n.text for n in creators if n.get('sub')=='Editor' and n.get('scheme')=='short-form'))]
 if ts is None or [(n.tag,n.text) for n in ts] != [(NS+t,v) for t,v in header_values]:raise ValueError('Primary title/author/editor header identity differs')
 acquisition_path=Path('library/works')/WORK/'forms'/(WORK+'--'+member_id+'--retained-en')/'editions'/(WORK+'--'+member_id+'--ccel-electronic')/'acquisitions'/(WORK+'--'+member_id+'--acquired.json')
 acquisition=json.loads((ROOT/acquisition_path).read_bytes())
 if acquisition['source_path']!='raw/ccel/expositors-bible/'+filename or acquisition['source_sha256']!=pin or acquisition['source_bytes']!=len(raw):raise ValueError('Independent acquired URI authority differs')
 expected=ET.Element(NS+'text',{XML+'lang':'en'})
 regions={p:ET.SubElement(expected,NS+p,{XML+'id':member_id+'-'+p}) for p in ('front','body','back')}
 regions['front'].text=body.text
 source_ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 source_records=[];source_to_tei={};join_events=[]
 basic={'div1':'div','div2':'div','div3':'div','div4':'div','p':'p','h1':'p','h2':'p','h3':'p','h4':'p','h5':'p','h6':'p',
 'i':'hi','b':'hi','strong':'hi','small':'hi','big':'hi','em':'hi','cite':'hi','sub':'hi','sup':'hi',
 'br':'lb','pb':'pb','note':'note','scripRef':'ref','scripCom':'milestone','insertIndex':'milestone','hr':'milestone',
 'span':'seg','verse':'lg','l':'l','blockquote':'quote','div':'quote','ul':'list','li':'item','table':'table','tr':'row','td':'cell','th':'cell','img':'figure','a':'ref'}
 renders={'i':'italic','b':'bold','strong':'bold','small':'small','big':'large','em':'emphasis','cite':'source-citation','sub':'subscript','sup':'superscript'}
 rend_tags={'div','p','hi','seg','quote','lg','l','list','item','table','cell','ref','note','lb','milestone','anchor'}
 style_tags={'div','p','hi','seg','table','cell','milestone'}
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
  if node.tag in {'scripCom','insertIndex','hr'}:
   attrs['unit']='horizontal-rule' if node.tag=='hr' else node.tag
   label=node.get('passage') if node.tag=='scripCom' else node.get('type') if node.tag=='insertIndex' else None
   if label is not None:attrs['n']=label
   if node.get('osisRef') is not None:attrs['corresp']=node.get('osisRef')
  if node.tag=='br':attrs['type']='source-br'
  if node.tag=='pb' and node.get('n') is not None:attrs['n']=node.get('n')
  if node.tag=='note':
   for k in ('n','place','type'):
    if node.get(k) is not None:attrs[k]=node.get(k)
   if node.get('anchored') is not None:attrs['anchored']={'yes':'true','no':'false'}.get(node.get('anchored'),node.get('anchored'))
  if node.tag in {'td','th'}:
   for k,mapped in [('colspan','cols'),('rowspan','rows')]:
    if node.get(k) is not None:attrs[mapped]=node.get(k)
  if node.tag=='th':attrs['role']='label'
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
  if node.get('valign') and tag=='cell':attrs['rend']=(attrs.get('rend','')+' source-valign-'+node.get('valign')).strip()
  for key in ('next','prev'):
   if node.get(key) is not None:
    target=node.get(key)
    if target in source_ids:attrs[key]='#'+member_id+'-'+target
    else:attrs['ana']=(attrs.get('ana','')+' urn:ccel:source-navigation:'+key+':'+quote(target,safe='-_.')).strip()
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
 uri_rows=[]
 for source_path,expect in source_to_tei.items():
  if expect.get(XML+'base') is not None:
   real=next(n for n in actual.iter() if n.get(XML+'id')==expect.get(XML+'id'))
   if real.get('target')!=expect.get('target') or real.get(XML+'base')!=acquisition['url'] or urljoin(real.get(XML+'base'),real.get('target'))!=urljoin(acquisition['url'],expect.get('target')):raise ValueError('Actual acquired-source URI context differs')
   uri_rows.append(dict(source_path=list(source_path),tei_id=real.get(XML+'id'),target=real.get('target'),base=real.get(XML+'base'),resolved_uri=urljoin(real.get(XML+'base'),real.get('target'))))
 if len(uri_rows)!=87:raise ValueError('Complete relative URI census differs')
 account=json.loads((directory/'source-accountability.json').read_bytes())
 if account['source_sha256']!=pin or account['member_id']!=member_id or account['source_body_tag']!=body.tag or account['source_body_attributes']!=body.attrib or account['source_body_text']!=body.text or account['source_body_tail']!=body.tail or account['source_root_attributes']!=source.attrib or account['source_path']!='raw/ccel/expositors-bible/'+filename:raise ValueError('Actual source accounting envelope differs')
 if account['source_uri_acquisition_path']!=acquisition_path.as_posix() or account['source_uri_acquisition_sha256']!=sha256((ROOT/acquisition_path).read_bytes()).hexdigest():raise ValueError('Acquired URI accounting differs')
 root_ids=[n.get('id') for n in body if isinstance(n.tag,str)]
 expected_regions={p:[n.get('id') for n in body if isinstance(n.tag,str) and ('front' if n.get('id') in front else 'back' if n.get('id') in back else 'body')==p] for p in regions}
 if account['root_ids_in_order']!=root_ids or account['root_disposition']!=expected_regions:raise ValueError('Source root/region accounting differs')
 if len(account['features'])!=len(source_records):raise ValueError('Source account census differs')
 for actual_record,expect_record in zip(account['features'],source_records,strict=True):
  if actual_record!=expect_record:raise ValueError('Independent source field or actual-TEI binding accounting differs')
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
 expected_visible=[];expected_comments=[]
 for ordinal,(n,r) in enumerate(zip(lhead.iter(),records,strict=True),1):
  source_path=lsource.getroottree().getpath(n)
  if isinstance(n.tag,str):
   fields=dict(ordinal=ordinal,kind='element',tag=n.tag,attributes=dict(n.attrib),text=n.text,tail=n.tail,source_xpath=source_path)
   if any(r.get(k)!=v for k,v in fields.items()):raise ValueError('Source header accounting differs')
   if (n.text or '').strip() or n.attrib:
    value='Source field '+source_path+': '+json.dumps(dict(attributes=dict(n.attrib),text=n.text),ensure_ascii=False,sort_keys=True)
    expected_visible.append((str(ordinal),value))
  else:
   value='Retained source head comment: '+(n.text or '')
   if r.get('ordinal')!=ordinal or r.get('kind')!='comment' or r.get('source_xpath')!=source_path or r.get('text')!=n.text or r.get('tail')!=n.tail or r.get('visible_header_note_text')!=value:raise ValueError('Source head comment differs')
   expected_comments.append((str(ordinal),value))
 if [(n.get('n'),n.text) for n in visible]!=expected_visible:raise ValueError('Visible primary header fields differ')
 if [(n.get('n'),n.text) for n in candidate.findall('.//'+NS+'note[@type="retained-source-head-comment"]')]!=expected_comments:raise ValueError('Visible source header rights comment differs')
 prolog=[dict(node_kind='comment' if n.tag is etree.Comment else 'pi',target=n.target if n.tag is etree.PI else None,text=n.text,tail=n.tail) for n in reversed(list(lsource.itersiblings(preceding=True)))]
 if account['source_prolog']!=prolog:raise ValueError('Source prolog directive/rights evidence differs')
 notes=candidate.findall('.//'+NS+'note[@type="retained-source-prolog"]')
 expected_notes=[(str(i),'Retained source prolog '+str(i)+': '+json.dumps(n,ensure_ascii=False,sort_keys=True)) for i,n in enumerate(prolog,1)]
 if [(n.get('n'),n.text) for n in notes]!=expected_notes:raise ValueError('Visible source prolog rights/directives differ')
 prefix=raw[:raw.index(b'<ThML')].decode('utf-8')
 if account.get('source_root_tail')!=source.tail or account.get('source_head_xml')!=etree.tostring(lhead,encoding='unicode') or account.get('source_document_prefix')!=prefix or account.get('source_document_prefix_sha256')!=sha256(prefix.encode('utf-8')).hexdigest() or account.get('source_root_text')!=source.text:raise ValueError('Literal retained XML document envelope differs')
 prefix_notes=candidate.findall('.//'+NS+'note[@type="retained-source-document-prefix"]')
 if len(prefix_notes)!=1 or prefix_notes[0].text!='Literal retained XML document prefix: '+prefix:raise ValueError('Literal XML declaration/DOCTYPE/prefix not visible')
 missing=[]
 for record in source_records:
  if record['source_tag'].startswith('#'):continue
  for key in ('next','prev'):
   value=record['source_attributes'].get(key)
   if value is not None and value not in source_ids:missing.append(dict(source_path=record['source_path'],source_tag=record['source_tag'],source_id=record['source_attributes'].get('id'),field=key,target=value))
 if account.get('missing_source_navigation')!=missing:raise ValueError('Raw-derived missing navigation accounting differs')
 unresolved=[json.loads(line) for line in (directory/'unresolved.jsonl').read_text(encoding='utf-8').splitlines()]
 if len(unresolved)!=2 or unresolved[1]!=dict(id=member_id+'-missing-source-navigation',status='unresolved',raw_source_fields=missing,disposition='Exact source fields remain typed source annotations; destinations not invented'):raise ValueError('Missing navigation unresolved fields differ')
 historical=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
 expected_corrections=[r for r in historical['text_corrections'] if r['member_id']==member_id]
 if account.get('historical_text_corrections')!=expected_corrections:raise ValueError('Historical correction annotations differ')
 if account.get('historical_correction_disposition')!=CORRECTION_DISPOSITION:raise ValueError('Historical correction disposition differs')
 credit=(directory/'README.source.md').read_bytes().decode('utf-8')
 if json.dumps(expected_corrections,ensure_ascii=False,sort_keys=True,indent=2) not in credit or 'zero selected correction rows' not in credit:raise ValueError('Historical correction qualification not human visible')
 notice=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes().split(b'## Using ThML',1)[0].decode('utf-8')
 if not credit.endswith(notice) or prefix not in credit or 'Do not sell CCEL files or derivatives of their formatting.' not in credit or 'Sourced via CCEL.org.' not in credit:raise ValueError('Complete source-local permission/XML prefix not human visible')
 for literal in (head.findtext('.//DC.Title'),head.findtext('.//published'),head.findtext('.//DC.Rights') or '[empty in retained source]',SCOPE,LEGACY):
  if literal not in credit:raise ValueError('Primary source README literal/qualification differs')
 # Every actual header node is independently derived; no free extra metadata or text.
 expected_header=ET.Element(NS+'teiHeader');fd=ET.SubElement(expected_header,NS+'fileDesc');title_stmt=ET.SubElement(fd,NS+'titleStmt')
 for tag,value in header_values:ET.SubElement(title_stmt,NS+tag).text=value
 publication=ET.SubElement(fd,NS+'publicationStmt');ET.SubElement(publication,NS+'p').text='Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'
 desc=ET.SubElement(fd,NS+'sourceDesc');qualification=ET.SubElement(desc,NS+'bibl');ET.SubElement(qualification,NS+'note',{'type':'source-limitations'}).text=SCOPE
 bibl=ET.SubElement(desc,NS+'bibl');ET.SubElement(bibl,NS+'title').text=head.findtext('.//DC.Title')
 for ordinal,n in enumerate(lhead.iter(),1):
  if not isinstance(n.tag,str):ET.SubElement(bibl,NS+'note',{'type':'retained-source-head-comment','n':str(ordinal)}).text='Retained source head comment: '+(n.text or '')
  elif (n.text or '').strip() or n.attrib:ET.SubElement(bibl,NS+'note',{'type':'retained-source-head-field','n':str(ordinal)}).text='Source field '+lsource.getroottree().getpath(n)+': '+json.dumps(dict(attributes=dict(n.attrib),text=n.text),ensure_ascii=False,sort_keys=True)
 ET.SubElement(bibl,NS+'note',{'type':'retained-source-document-prefix'}).text='Literal retained XML document prefix: '+prefix
 for ordinal,marker in enumerate(prolog,1):ET.SubElement(bibl,NS+'note',{'type':'retained-source-prolog','n':str(ordinal)}).text='Retained source prolog '+str(ordinal)+': '+json.dumps(marker,ensure_ascii=False,sort_keys=True)
 if _fields(candidate.find(NS+'teiHeader'))!=_fields(expected_header):raise ValueError('Complete source-derived actual header envelope differs')
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
  table_count=sum(n.tag=='table' for n in body.iter()),table_header_cell_count=sum(n.tag=='th' for n in body.iter()),relative_uri_count=len(uri_rows),relative_uri_context=uri_rows,image_pointer_count=sum(n.tag=='img' for n in body.iter()),p5='pass',local_links='closed',
  limitations=['No source image elements','Human acceptance not recorded','No print collation','Rights/publication unresolved','One complete separately titled First Samuel work; Second Samuel and Joshua excluded'])
 return result


def _plain(value):
 if isinstance(value,Mapping):return {k:_plain(v) for k,v in value.items()}
 if isinstance(value,(tuple,list)):return [_plain(v) for v in value]
 return value

def expected_policy():
 return dict(contract='ocd-blaikie-first-samuel-independent-validation-policy-v1',work_id=WORK,complete_work_id='blaikie-expositor8',complete_work_count=1,source_member_count=1,checks=['exact current raw/acquisition identity','whole parsed candidate envelope and primary header','independent raw-derived native hierarchy, semantic attributes, text/tails and attachment order','actual native-backed complete source body inverse','exact administrative comment ledger and whitespace joins','literal source head/prolog/XML prefix and visible CCEL permission','exact original relative href and acquisition URL context','missing source navigation qualification','qualified existing LIB036 flat graph conservation','complete composite provenance, source profile and policy contents','strict fresh producer/oracle first-party imports','P5 and local ID closure','two fresh exact six-member replay processes'],human_acceptance='not_recorded',rights='unresolved',publication='not_ready',source_readings='unchanged; zero historical correction rows',excluded_source_members=['blaikie-expositor2sam','blaikie-expositorjosh'])

def _oracle(source:SourceManifest,candidate:CandidatePackage)->dict:
 source.verify();candidate.verify_integrity()
 if json.loads(source.authority_path('policy').read_bytes())!=expected_policy():raise ValueError('Complete independent policy contents differ')
 member=source.record['source_id'].removeprefix('ccel-blaikie-first-samuel-retained-native-').removesuffix('-v1')
 if source.record['source_id']!='ccel-blaikie-first-samuel-retained-native-'+member+'-v1' or candidate.manifest['source_id']!=source.record['source_id'] or candidate.manifest['source_manifest']['sha256']!=source.sha256:raise ValueError('Exact complete-work source/package identity binding differs')
 if member not in SOURCES or candidate.manifest['status']!='nonaccepted' or candidate.manifest['converter']!=source.record['converter']:raise ValueError('Candidate source/converter binding differs')
 result=check(member,candidate.path)
 if source.authority_path('retained-thml').read_bytes()!=(ROOT/'raw/ccel/expositors-bible'/SOURCES[member][0]).read_bytes():raise ValueError('Candidate retained authority differs')
 filename,pin,front,back,count=SOURCES[member];raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();tree=_parse(raw);body=tree.find('ThML.body');head=tree.find('ThML.head')
 form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic';acquisition_id=WORK+'--'+member+'--acquired'
 acquisition_path=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(acquisition_id+'.json');acquisition_raw=(ROOT/acquisition_path).read_bytes();acquisition=json.loads(acquisition_raw)
 log=Path('reports/_logs/blaikie-first-samuel-existing-install-20261003-v1');old=log/'qualified-current-lib036-replay'
 lineage_paths=[old/name for name in ('content.tei.xml','source-accountability.json','provenance.json','unresolved.jsonl','README.source.md','manifest.json')]+[log/name for name in ('legacy-replay-receipt.json','source-inventory.json','reconcile_legacy.py')]+[Path('sources/commentaries/expositors-bible/lib036.reconstruction-profile.json'),Path('sources/commentaries/expositors-bible/lib036.source-manifest.json')]
 lineage=[dict(path=p.as_posix(),bytes=len((ROOT/p).read_bytes()),sha256=sha256((ROOT/p).read_bytes()).hexdigest()) for p in lineage_paths]
 corrections=[r for r in json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())['text_corrections'] if r['member_id']==member]
 prefix=raw[:raw.index(b'<ThML')].decode('utf-8');account=json.loads(candidate.member_bytes('source-accountability.json'))
 expected_provenance=dict(contract='ocd-blaikie-first-samuel-composite-provenance-v1',status='nonaccepted',work_id=WORK,member_id=member,source_path='raw/ccel/expositors-bible/'+filename,source_sha256=pin,source_bytes=len(raw),scope=SCOPE,source_title=head.findtext('.//DC.Title'),source_print_statement=head.findtext('.//published'),source_url=acquisition['url'],form_id=form,edition_id=edition,acquisition_id=acquisition_id,acquisition_path=acquisition_path.as_posix(),acquisition_sha256=sha256(acquisition_raw).hexdigest(),source_document_prefix_sha256=sha256(prefix.encode()).hexdigest(),legacy_basis=LEGACY,lineage_bindings=lineage,historical_accounting_pin_exact=False,historical_tei_pin_exact=False,historical_correction_disposition=CORRECTION_DISPOSITION,historical_correction_count=len(corrections),producer_recipe_sha256=sha256((ROOT/'build/tei/blaikie_first_samuel_retained_native_prepare.py').read_bytes()).hexdigest(),emitter_sha256=sha256((ROOT/'build/tei/blaikie_first_samuel_retained_native_emitter.py').read_bytes()).hexdigest(),oracle_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),ancestor_implementation_pins=[dict(path=p,sha256=sha256((ROOT/p).read_bytes()).hexdigest()) for p in ('build/tei/dods_retained_native_emitter.py','build/tei/dods_retained_native_prepare.py','build/tei/dods_retained_native_oracle.py')],human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
 if json.loads(candidate.member_bytes('provenance.json'))!=expected_provenance:raise ValueError('Complete composite provenance differs')
 profile=json.loads(source.authority_path('profile').read_bytes());secondary=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 spec=dict(path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=sum(isinstance(n.tag,str) for n in body.iter()),comments=sum(n.tag is ET.Comment for n in body.iter()),form=form,edition=edition,acquisition=acquisition_id)
 expected_profile=dict(contract='ocd-blaikie-first-samuel-existing-readable-profile-v1',member_id=member,work_id=WORK,source=spec,source_body_c14n_sha256=sha256(etree.tostring(secondary.find('ThML.body'),method='c14n',with_comments=True)).hexdigest(),body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),front=list(front),back=list(back),root_ids_in_order=[n.get('id') for n in body if isinstance(n.tag,str)],root_disposition=account['root_disposition'],acquired_work_units=1,producer_import_closure_sha256=import_closure('build.tei.blaikie_first_samuel_retained_native_prepare'),producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',scope=SCOPE,source_uri_acquisition_path=acquisition_path.as_posix(),source_uri_acquisition_sha256=sha256(acquisition_raw).hexdigest(),source_url=acquisition['url'],source_document_prefix_sha256=sha256(prefix.encode()).hexdigest(),missing_source_navigation=account['missing_source_navigation'],historical_correction_count=len(corrections),historical_correction_disposition=CORRECTION_DISPOSITION,index_container=[],lineage_bindings=lineage,complete_work_count=1,complete_work_id=member,source_member_count=1,excluded_source_members=['blaikie-expositor2sam','blaikie-expositorjosh'])
 if profile!=expected_profile:raise ValueError('Complete independently derived source profile/roles/counts/identity/closures differs')
 expected_roles={'retained-thml':'primary-source','profile':'complete-source-feature-profile','policy':'independent-validation-policy','tei-p5-xsd':'tei-validation-schema','package-schema':'candidate-package-schema','source-local-attribution-readme':'source-rights-attribution','ccel-permission':'source-rights-evidence','source-uri-acquisition':'source-uri-context-authority'}
 if any(next((r['role'] for r in source.record['authorities'] if r['name']==name),None)!=role for name,role in expected_roles.items()):raise ValueError('Source authority role differs')
 if candidate.member_bytes('README.source.md')!=source.authority_path('source-local-attribution-readme').read_bytes():raise ValueError('Candidate complete source-local README authority differs')
 if _plain(source.record['source_order'])!=dict(order='Complete retained First Samuel source DOM including all title page, chapters I-XXXVI and indexes',members=[member]):raise ValueError('Complete source order declaration differs')
 if _plain(source.record['scope'])!=dict(kind='complete-retained-work',member_id=member,acquired_work_member_count=1,complete_work_count=1,source_member_count=1,excluded_source_members=['blaikie-expositor2sam','blaikie-expositorjosh'],no_acquisition_or_download=True):raise ValueError('Entire one-work source scope differs')
 if source.record['work_id']!=WORK or source.record['scope']['member_id']!=member or source.record['scope']['acquired_work_member_count']!=1 or source.record['scope']['no_acquisition_or_download'] is not True:raise ValueError('Current one complete First Samuel scope differs')
 record=dict(status='pass',oracle_id=_oracle.oracle_id,oracle_version=_oracle.oracle_version,
  implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=import_closure(),
  runtime=_runtime_binding(),source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,
  profile_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='complete-source-feature-profile'),
  package_schema_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='candidate-package-schema'),
  source_sha256=result['source_sha256'],xsd_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='tei-validation-schema'),
  policy_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='independent-validation-policy'),findings=[json.dumps(result,sort_keys=True)])
 record['result_sha256']=sha256(_canonical(record)).hexdigest();return record


_oracle.oracle_id='ocd-blaikie-first-samuel-retained-native-independent-oracle'
_oracle.oracle_version='1'


if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);args=p.parse_args()
 for member in SOURCES:print(json.dumps(check(member,args.directory/member),sort_keys=True),flush=True)
