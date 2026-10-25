"""Independent full raw-source/actual-TEI oracle for Blaikie's Joshua.

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
from urllib.parse import quote, urlsplit, urljoin
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--william-g-blaikie'
SCOPE = 'Complete authored Book of Joshua from its one already acquired CCEL electronic witness: title page, all Chapters I through XXXIII including authored introduction, generated indexes, notes and verse. Samuel and author/series completeness are excluded. Human review, print collation, rights clearance and publication remain separate; no new acquisition.'
LEGACY='Qualified current LIB036 converter-only replay retains the exact downloaded bytes and original-reading feature graph. September11 candidate path is access denied; historical package recovery and old oracle validation are not claimed. All historical correction alternatives remain qualified; raw readings are retained.'
SOURCES={'blaikie-expositorjosh':('blaikie_expositorjosh.xml','7a2be4c01ca4ed8ecf37aa6905a161c126ac8cc4752e00448126ae363d2139b3',('i',),('xxxv',),2352)
}

# Exact observed fresh import inventories. These are import-time closures; all
# runtime/schema/source dependencies are separately frozen by installation.
ORACLE_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/blaikie_joshua_retained_native_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())
PRODUCER_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/blaikie_joshua_retained_native_emitter.py build/tei/blaikie_joshua_retained_native_prepare.py build/tei/blaikie_joshua_retained_scope.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())


def import_closure(module='build.tei.blaikie_joshua_retained_native_oracle', *, root=ROOT, extra_import=None):
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
 if tuple(observed)!=expected:raise ValueError('Joshua observed first-party import closure differs: '+repr(observed))
 records=[dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in observed]
 return sha256(_canonical(records)).hexdigest()


def _parse(raw:bytes)->ET.Element:
 return ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))


def _fields(node):
 return [(n.tag,dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in node.iter()]

def _metadata_check(member,directory,raw):
 filename,pin,front,back,count=SOURCES[member];form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic';acquisition=WORK+'--'+member+'--acquired'
 old=Path('reports/_logs/blaikie-joshua-existing-install-20261003-v1/qualified-current-lib036-replay');log=old.parent
 def bound(path):
  value=(ROOT/path).read_bytes();return dict(path=Path(path).as_posix(),bytes=len(value),sha256=sha256(value).hexdigest())
 acq=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(acquisition+'.json')
 composite=dict(identity=dict(work_id=WORK,textual_form_id=form,edition_id=edition,acquisition_id=acquisition),primary_acquisition=bound(acq)|dict(url='https://www.ccel.org/ccel/blaikie/expositorjosh.html'),
  producer=bound('build/tei/blaikie_joshua_retained_native_prepare.py'),derivative=bound('build/tei/blaikie_joshua_retained_native_emitter.py'),ancestor=bound('build/tei/ccel_retained_native_emitter.py'),
  replay_members=[bound(old/name) for name in sorted(['README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl'])],
  replay_receipt=bound(log/'qualified-current-lib036-replay-receipt.json'),historical_profile=bound('sources/commentaries/expositors-bible/lib036.reconstruction-profile.json'),
  source_boundary='One complete authored Book of Joshua: independent title, author and imprint; Chapters I through XXXIII including authored introduction, then indexes. The Expositors Bible and inherited author catalog are containers; First and Second Samuel are separately assigned and excluded.')
 expected=dict(status='nonaccepted',work_id=WORK,member_id=member,source_path='raw/ccel/expositors-bible/'+filename,source_sha256=pin,source_bytes=len(raw),scope=SCOPE,legacy_basis=LEGACY,
  emitter_ancestor_sha256='a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f',emitter_sha256=composite['derivative']['sha256'],human_acceptance='not_recorded',rights='unresolved',publication='not_ready',composite_binding=composite)
 if json.loads((directory/'provenance.json').read_bytes())!=expected:raise ValueError('Exact current composite producer/source/acquisition/replay provenance differs')
 primary=_parse(raw);primary_head=primary.find('ThML.head');body=primary.find('ThML.body')
 unresolved=(json.dumps(dict(id=member+'-human-rights-print-assets',status='unresolved',detail=SCOPE),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
 ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 gaps=[dict(source_id=n.get('id'),attribute=k,target=n.get(k)) for n in body.iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) and n.get(k) not in ids]
 for ordinal,gap in enumerate(gaps,1):
  unresolved+=(json.dumps(dict(id=member+'-missing-source-directive-'+str(ordinal),status='unresolved',kind='source-next-prev-gap',**gap),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
 if (directory/'unresolved.jsonl').read_bytes()!=unresolved:raise ValueError('Exact source gaps and qualification differ')
 readme=(f'# Retained source: {primary_head.findtext('.//DC.Title')}\n\nSourced via CCEL.org.\n\n'
     f'Retained authority: {'raw/ccel/expositors-bible/'+filename}; SHA-256 {pin}; {len(raw)} bytes.\n\n'
     f'Primary source author: {next(n.text for n in primary_head.findall('.//DC.Creator') if n.get('sub')=='Author' and n.get('scheme')=='short-form')}. Series editor: {next(n.text for n in primary_head.findall('.//DC.Creator') if n.get('sub')=='Editor' and n.get('scheme')=='short-form')}.\n\n'
     f'Literal source printed-edition statement: {primary_head.findtext(".//published")}.\n\n'
     f'Literal DC.Rights: {primary_head.findtext(".//DC.Rights") or "[empty in retained source]"}. This source field is not rights clearance.\n\n'
     f'{LEGACY}\n\n{SCOPE}\n\n'
     'Chapter I is substantive authored introduction and remains in the body; only title page i is front, and index xxxv is back. All source readable content remains in original order. Source h1 through h6 preserve exact heading level as source-level paragraphs. Notes, verse lines, page numbers, lists, inline styles and every literal source attribute retain fields, order and attachment. The 22 administrative comments retain exact source fields/positions; their whitespace-only tails join adjacent actual TEI carriers reversibly.\n\n'
     'All 40 relative query links retain literal href readings and the exact primary acquired CCEL HTML URL as per-ref xml:base. Two absent source next/prev toc destinations remain explicit typed unresolved gaps; no destination is invented. The complete Joshua source contains no table or image elements and no historical text-correction proposals; no raw reading is replaced. Literal source header fields, CSS, XML declaration and stylesheet processing instructions remain visible and accounted.\n\n'
     'Bennett mapping and checker implementations were inspected and used as separately maintained ancestors; independence is not blind. The current checker independently derives all readable fields and hierarchy from stdlib raw XML, corroborates all raw fields with strict lxml, and inverses the whole raw body from the actual TEI. No browser/CSS visual equivalence or print collation is claimed.\n\n'
     '## Retained CCEL permission evidence\n\n'+(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_text(encoding='utf-8'))
 if (directory/'README.source.md').read_bytes()!=readme.encode('utf-8'):raise ValueError('Exact visible current source credit, scope and permission differ')



@lru_cache(maxsize=1)
def _p5_schema():
 return etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))


def check(member_id:str,directory:Path,*,native=False)->dict:
 filename,pin,front,back,full_count=SOURCES[member_id]
 raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes()
 if sha256(raw).hexdigest()!=pin:raise ValueError('Retained source identity differs')
 source=_parse(raw);body=source.find('ThML.body');head=source.find('ThML.head')
 if body is None or head is None:raise ValueError('Complete source head/body required')
 acquisition_path=ROOT/'library/works'/WORK/'forms'/(WORK+'--'+member_id+'--retained-en')/'editions'/(WORK+'--'+member_id+'--ccel-electronic')/'acquisitions'/(WORK+'--'+member_id+'--acquired.json')
 acquisition=json.loads(acquisition_path.read_bytes())
 source_base='https://www.ccel.org/ccel/blaikie/expositorjosh.html'
 if acquisition['url']!=source_base or acquisition['source_sha256']!=pin or acquisition['source_path']!='raw/ccel/expositors-bible/'+filename or acquisition['source_bytes']!=len(raw) or len(acquisition['retained_files'])!=1 or acquisition['retained_files'][0]['sha256']!=pin or acquisition['retained_files'][0]['bytes']!=len(raw) or acquisition['retained_files'][0]['path']!='raw/ccel/expositors-bible/'+filename:raise ValueError('Primary retained source URL context differs')
 if sum(isinstance(n.tag,str) for n in source.iter())!=full_count:raise ValueError('Whole retained source census differs')
 # Secondary parser corroborates every source tree field, before any TEI comparison.
 lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 left=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in source.iter()]
 right=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in lsource.iter()]
 if left!=right:raise ValueError('Independent source parser corroboration differs')
 path=directory/'content.tei.xml';candidate=_parse(path.read_bytes());actual=candidate.find(NS+'text')
 if candidate.tag!=NS+'TEI' or candidate.attrib!={XML+'id':member_id} or candidate.text is not None or candidate.tail is not None or [n.tag for n in candidate]!=[NS+'teiHeader',NS+'text'] or len(candidate.findall(NS+'text'))!=1 or candidate[0].tail is not None or actual is None or actual.tail is not None:raise ValueError('Actual candidate exact root envelope/cardinality differs')
 ts=candidate.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt')
 creators=head.findall('.//DC.Creator')
 header_values=[('title',head.findtext('.//DC.Title')),('author',next(n.text for n in creators if n.get('sub')=='Author' and n.get('scheme')=='short-form')),('editor',next(n.text for n in creators if n.get('sub')=='Editor' and n.get('scheme')=='short-form'))]
 if ts is None or [(n.tag,n.text) for n in ts] != [(NS+t,v) for t,v in header_values]:raise ValueError('Primary title/author/editor header identity differs')
 expected=ET.Element(NS+'text',{XML+'lang':'en'})
 regions={p:ET.SubElement(expected,NS+p,{XML+'id':member_id+'-'+p}) for p in ('front','body','back')}
 regions['front'].text=body.text
 source_ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 source_records=[];source_to_tei={};join_events=[]
 basic={'div1':'div','div2':'div','div3':'div','div4':'div','p':'p','h1':'p','h2':'p','h3':'p','h4':'p','h5':'p','h6':'p',
 'i':'hi','b':'hi','strong':'hi','small':'hi','big':'hi','em':'hi','cite':'hi','sub':'hi','sup':'hi',
 'br':'lb','pb':'pb','note':'note','scripRef':'ref','scripCom':'milestone','insertIndex':'milestone','hr':'milestone',
 'span':'seg','verse':'lg','l':'l','blockquote':'quote','div':'quote','ul':'list','li':'item','table':'table','tr':'row','td':'cell','th':'cell','img':'figure','a':'ref','colgroup':'milestone'}
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
  if node.tag=='verse':
   attrs['type']='source-stanza'
  if node.tag=='blockquote':attrs['type']='source-blockquote'
  if node.tag=='a':
   href=node.get('href')
   if href is None:tag='seg' if node.text or len(node) else 'anchor';attrs['type']='source-anchor'
   elif href.startswith('#'):
    if href[1:] not in source_ids:tag='seg';attrs.update(type='source-unresolved-link',n=href)
    else:attrs['target']='#'+member_id+'-'+href[1:]
   else:
    attrs['target']=href
    if href and not urlsplit(href).scheme:attrs[XML+'base']=source_base
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
  if node.tag=='colgroup':raise ValueError('No Joshua column group exists')
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
  if node.get(XML+'lang') is not None:attrs[XML+'lang']=node.get(XML+'lang')
  elif node.get('lang') is not None:attrs[XML+'lang']=node.get('lang')
  if node.get(XML+'space') is not None:attrs[XML+'space']=node.get(XML+'space')
  annotations=['urn:ccel:source-attribute:'+quote(k,safe='-_.')+':'+quote(v,safe='-_.') for k,v in sorted(node.attrib.items())]
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
 root_ids=[n.get('id') for n in body if isinstance(n.tag,str)]
 expected_regions={p:[n.get('id') for n in body if isinstance(n.tag,str) and ('front' if n.get('id') in front else 'back' if n.get('id') in back else 'body')==p] for p in regions}
 if account['root_ids_in_order']!=root_ids or account['root_disposition']!=expected_regions:raise ValueError('Source root/region accounting differs')
 if len(account['features'])!=len(source_records):raise ValueError('Source account census differs')
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
 prefix=raw[:raw.index(b'<ThML')].decode('utf8')
 if account.get('source_document_prefix')!=prefix:raise ValueError('Literal source document prefix differs')
 if account.get('source_head_xml')!=etree.tostring(lhead,encoding='unicode'):raise ValueError('Complete source head serialization differs')
 profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
 historical=[r for r in profile['text_corrections'] if r['member_id']==member_id]
 if account.get('historical_correction_alternatives')!=historical or account.get('correction_policy')!='No historical Joshua correction proposals; exact raw retained readings':raise ValueError('Historical alternatives/preservation policy differs')
 # Independently assemble the complete header from primary source fields.
 h=ET.Element(NS+'teiHeader');fd=ET.SubElement(h,NS+'fileDesc');title=ET.SubElement(fd,NS+'titleStmt')
 for tag,value in header_values:ET.SubElement(title,NS+tag).text=value
 pub=ET.SubElement(fd,NS+'publicationStmt');ET.SubElement(pub,NS+'p').text='Agent-reviewed reconstruction of an existing acquired electronic witness. Human review, print collation, CCEL formatting rights and publication remain separate gates.'
 desc=ET.SubElement(fd,NS+'sourceDesc');qualification=ET.SubElement(desc,NS+'bibl');ET.SubElement(qualification,NS+'note',{'type':'source-limitations'}).text=SCOPE
 bibliog=ET.SubElement(desc,NS+'bibl');ET.SubElement(bibliog,NS+'title').text=head.findtext('.//DC.Title')
 for ordinal,n in enumerate(lhead.iter(),1):
  if not isinstance(n.tag,str):ET.SubElement(bibliog,NS+'note',{'type':'retained-source-head-comment','n':str(ordinal)}).text='Retained source head comment: '+(n.text or '')
  elif (n.text or '').strip() or n.attrib:
   value='Source field '+lsource.getroottree().getpath(n)+': '+json.dumps(dict(attributes=dict(n.attrib),text=n.text),ensure_ascii=False,sort_keys=True)
   ET.SubElement(bibliog,NS+'note',{'type':'retained-source-head-field','n':str(ordinal)}).text=value
 ET.SubElement(bibliog,NS+'note',{'type':'retained-source-document-prefix'}).text=prefix
 for ordinal,row in enumerate(historical,1):ET.SubElement(bibliog,NS+'note',{'type':'unconfirmed-historical-correction','n':str(ordinal)}).text=json.dumps(row,ensure_ascii=False,sort_keys=True)
 for ordinal,marker in enumerate(prolog,1):ET.SubElement(bibliog,NS+'note',{'type':'retained-source-prolog','n':str(ordinal)}).text='Retained source prolog '+str(ordinal)+': '+json.dumps(marker,ensure_ascii=False,sort_keys=True)
 if _fields(h)!=_fields(candidate[0]):raise ValueError('Complete source-derived header fields/order/attachment differ')
 _metadata_check(member_id,directory,raw)
 _p5_schema().assertValid(etree.parse(str(path)))
 ids=[n.get(XML+'id') for n in candidate.iter() if n.get(XML+'id')]
 if len(ids)!=len(set(ids)):raise ValueError('Actual TEI duplicate IDs')
 for n in candidate.iter(NS+'ref'):
  target=n.get('target','')
  if target.startswith('#') and target[1:] not in ids:raise ValueError('Actual TEI local reference closure differs')
 result=dict(status='pass',member_id=member_id,source_sha256=pin,tei_sha256=sha256(path.read_bytes()).hexdigest(),whole_source_elements=full_count,
  source_body_nodes=len(source_records),source_tag_counts=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),header_cell_count=sum(n.tag=='th' for n in body.iter()),tbody_wrapper_count=sum(n.tag=='tbody' for n in body.iter()),comments_ledger_retained=sum(r['source_tag']=='#comment' for r in source_records),
  actual_native_text_fields_order_ownership_pass=True,actual_native_attribute_roles_pass=True,actual_tei_backed_source_body_inverse_pass=True,
  independently_checked_whitespace_joins=len(join_events),source_head_visible_fields=len(visible),source_prolog_visible_fields=len(notes),
  table_count=sum(n.tag=='table' for n in body.iter()),image_pointer_count=sum(n.tag=='img' for n in body.iter()),p5='pass',local_links='closed',
  limitations=['Human acceptance not recorded','No print collation','Rights/publication unresolved','Complete authored Joshua from its one retained electronic witness; Samuel and author/series completeness excluded'])
 actual_relative=[]
 for source_path,out in source_to_tei.items():
  original=body
  for index in source_path:original=original[index]
  href=original.get('href') if original.tag=='a' else None
  if href and not href.startswith('#') and not urlsplit(href).scheme:
   if out.get('target')!=href or out.get(XML+'base')!=source_base or urljoin(source_base,href)!=urljoin(out.get(XML+'base'),out.get('target')):raise ValueError('Actual relative URI source context differs')
   actual_relative.append(dict(source_path=list(source_path),tei_id=out.get(XML+'id'),href=href,base=source_base,resolved=urljoin(source_base,href)))
 if len(actual_relative)!=40:raise ValueError('Complete Joshua relative link denominator differs')
 result['relative_uri_contexts']=actual_relative
 from build.tei.blaikie_joshua_legacy_oracle import reconcile
 result['qualified_original_scope']=reconcile()
 if native:raise ValueError('Actual commentary projection is a separate installation-stage probe')
 return result


def expected_profile(member):
 filename,pin,front,back,count=SOURCES[member]
 raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();primary=_parse(raw);body=primary.find('ThML.body')
 spec=dict(volume=1,path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=sum(isinstance(n.tag,str) for n in body.iter()),body_comments=sum(n.tag is ET.Comment for n in body.iter()),tbody_wrappers=0,colgroup_wrappers=0,native_source_elements=sum(isinstance(n.tag,str) and n.tag!='ThML.body' for n in body.iter()),front=list(front),back=list(back),source_base_url='https://www.ccel.org/ccel/blaikie/expositorjosh.html',form=WORK+'--'+member+'--retained-en',edition=WORK+'--'+member+'--ccel-electronic',acquisition=WORK+'--'+member+'--acquired')
 ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 gaps=[dict(source_id=n.get('id'),attribute=k,target=n.get(k)) for n in body.iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) and n.get(k) not in ids]
 relative=[dict(href=n.get('href'),source_id=n.get('id'),source_base=spec['source_base_url']) for n in body.iter() if n.tag=='a' and n.get('href') and not n.get('href').startswith('#') and not urlsplit(n.get('href')).scheme]
 actual=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
 return dict(contract='ocd-blaikie-joshua-complete-retained-volume-profile-v1',member_id=member,work_id=WORK,source=spec,
  source_body_c14n_sha256=sha256(etree.tostring(actual.find('ThML.body'),method='c14n',with_comments=True)).hexdigest(),
  source_head_c14n_sha256=sha256(etree.tostring(actual.find('ThML.head'),method='c14n',with_comments=True)).hexdigest(),
  literal_document_prefix_sha256=sha256(raw[:raw.index(b'<ThML')]).hexdigest(),
  body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),front=list(front),back=list(back),acquired_work_volumes=1,complete_authored_works=1,
  producer_import_closure_sha256=import_closure('build.tei.blaikie_joshua_retained_native_prepare'),producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',
  scope='complete authored Joshua; inherited author catalog and series excluded',graphics='No source image elements; no pixels acquired or inferred',
  adaptations='Raw readings and source attributes; independently reversible administrative-comment whitespace joins; original query URI contexts; source-level heading paragraphs; full primary head and document prefix visible',
  relative_links=relative,missing_next_prev=gaps,historical_corrections=[],
  region_owner='Joshua owns title page, all authored chapters including introduction, and all generated indexes; no Samuel content',
  comment_classes=dict(Counter(n.text for n in body.iter() if n.tag is ET.Comment)))

def expected_policy(member):
 return dict(contract='ocd-blaikie-joshua-independent-readable-policy-v1',member_id=member,
  independent='stdlib raw traversal/mapping and actual TEI comparison; all strict lxml raw fields corroborated; no producer or emitter import supplies expectations',
  prior_exposure='Bennett producer/checker and First Samuel historical-carrier checker inspected as separate maintained ancestors; not blind review',
  required=['exact acquired bytes and URL','full actual native fields/parent/order/attachment/attributes','all administrative comments and raw-derived whitespace joins','entire actual-TEI-backed source body inverse','all raw primary header/prolog/XML prefix fields visible and accounted','all40 source relative URI contexts','complete qualified legacy graph reconciliation','P5','valid semantic mutations','two fresh six-member byte replays','strict fresh producer/oracle import closure'],
  patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],visual='not performed; no browser/CSS equivalence or print collation claimed',
  source_quality='Two exact missing source next/prev toc destinations remain typed unresolved; zero source tables, images or historical correction proposals')

def expected_authority_declarations(member):
 directory='sources/commentaries/expositors-bible/blaikie-joshua-retained-install-20261003-v1'
 log='reports/_logs/blaikie-joshua-existing-install-20261003-v1'
 form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic'
 acquisition='library/works/'+WORK+'/forms/'+form+'/editions/'+edition+'/acquisitions/'+WORK+'--'+member+'--acquired.json'
 rows=[('retained-thml','raw/ccel/expositors-bible/'+SOURCES[member][0],'primary-source'),
  ('volume-profile',directory+'/'+member+'.profile.json','complete-source-feature-profile'),
  ('volume-policy',directory+'/'+member+'.policy.json','independent-validation-policy'),
  ('tei-p5-xsd','ocd_kernel/tei/vendor/xsd/tei_all.xsd','tei-validation-schema'),
  ('candidate-package-schema','ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json','candidate-package-schema'),
  ('source-local-attribution-readme',directory+'/'+member+'.README.source.md','source-rights-attribution'),
  ('ccel-permission','sources/commentaries/expositors-bible/ccel-permission.md','source-rights-evidence'),
  ('original-source-credit','data/commentaries/expositors-bible/README.md','historical-source-credit'),
  ('scope-recovery',log+'/retained-scope-reconciliation.json','existing-candidate-recovery-evidence'),
  ('source-preflight',log+'/source-inventory-read-only-preflight.json','complete-work-boundary-evidence'),
  ('primary-acquired-url-context',acquisition,'primary-source-url-context'),
  ('frozen-emitter-ancestor','build/tei/ccel_retained_native_emitter.py','reviewed-emitter-ancestor'),
  ('legacy-actual-checker','build/tei/blaikie_joshua_legacy_oracle.py','independent-legacy-source-graph-checker')]
 rows.extend(('schema-import-'+name,'ocd_kernel/tei/vendor/xsd/'+name+'.xsd','source-validation-schema-import') for name in ('tei_all_teix','tei_all_xml'))
 rows.extend(('import-'+str(i),path,'observed-first-party-import-dependency') for i,path in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS))))
 rows.extend(('replay-'+name,log+'/qualified-current-lib036-replay/'+name,'qualified-current-aggregate-replay-lineage') for name in ('README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl'))
 rows.extend([('historical-profile','sources/commentaries/expositors-bible/lib036.reconstruction-profile.json','historical-correction-profile'),
  ('replay-receipt',log+'/qualified-current-lib036-replay-receipt.json','qualified-current-converter-replay-evidence'),
  ('replay-source-manifest',directory+'/qualified-lib036-replay.source-manifest.json','qualified-current-converter-only-execution-admission')])
 return rows


def _oracle(source:SourceManifest,candidate:CandidatePackage)->dict:
 source.verify();candidate.verify_integrity()
 member='blaikie-expositorjosh'
 if source.record['source_id']!='ccel-blaikie-joshua-retained-native-'+member+'-v1' or source.record['work_id']!=WORK:raise ValueError('Exact Joshua source/work identity differs')
 if candidate.manifest['source_id']!=source.record['source_id'] or candidate.manifest['source_manifest']['sha256']!=source.sha256:raise ValueError('Exact candidate/source-manifest identity differs')
 if dict(source.record['source_order'])!=dict(order='complete original source DOM, notes/inline and administrative comment/tail attachment'):raise ValueError('Exact source order declaration differs')
 declarations=[(a['name'],a['path'],a['role']) for a in source.record['authorities']]
 if declarations!=expected_authority_declarations(member):raise ValueError('Exact ordered source authority declarations differ')
 if candidate.manifest['status']!='nonaccepted' or candidate.manifest['converter']!=source.record['converter']:raise ValueError('Candidate source/converter binding differs')
 result=check(member,candidate.path,native=False)
 if source.authority_path('retained-thml').read_bytes()!=(ROOT/'raw/ccel/expositors-bible'/SOURCES[member][0]).read_bytes():raise ValueError('Candidate retained authority differs')
 if source.authority_path('source-local-attribution-readme').read_bytes()!=candidate.member_bytes('README.source.md'):raise ValueError('Complete visible source credit authority differs')
 profile=json.loads(source.authority_path('volume-profile').read_bytes());filename,pin,front,back,count=SOURCES[member]
 raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();primary=_parse(raw);body=primary.find('ThML.body')
 spec=dict(volume=1,path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=sum(isinstance(n.tag,str) for n in body.iter()),body_comments=sum(n.tag is ET.Comment for n in body.iter()),tbody_wrappers=sum(n.tag=='tbody' for n in body.iter()),colgroup_wrappers=sum(n.tag=='colgroup' for n in body.iter()),native_source_elements=sum(isinstance(n.tag,str) and n.tag not in {'ThML.body','tbody'} for n in body.iter()),front=list(front),back=list(back),source_base_url='https://www.ccel.org/ccel/blaikie/expositorjosh.html',form=WORK+'--'+member+'--retained-en',edition=WORK+'--'+member+'--ccel-electronic',acquisition=WORK+'--'+member+'--acquired')
 actual_source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
 if profile!=expected_profile(member):raise ValueError('Complete current source/profile/census/import/role/quality binding differs')
 if json.loads(source.authority_path('volume-policy').read_bytes())!=expected_policy(member):raise ValueError('Complete independent policy differs')
 expected_scope=dict(kind='complete-existing-retained-authored-work',member_id=member,complete_work_count=1,acquired_work_member_count=1,no_acquisition_or_download=True)
 if dict(source.record['scope'])!=expected_scope:raise ValueError('Exact source-manifest complete-work scope differs')
 acq=Path('library/works')/WORK/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
 if source.authority_path('primary-acquired-url-context').read_bytes()!=(ROOT/acq).read_bytes():raise ValueError('Current primary acquisition authority differs')
 if source.authority_path('ccel-permission').read_bytes()!=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes():raise ValueError('Current retained permission authority differs')
 record=dict(status='pass',oracle_id=_oracle.oracle_id,oracle_version=_oracle.oracle_version,
  implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=import_closure(),
  runtime=_runtime_binding(),source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,
  profile_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='complete-source-feature-profile'),
  package_schema_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='candidate-package-schema'),
  source_sha256=result['source_sha256'],xsd_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='tei-validation-schema'),
  policy_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='independent-validation-policy'),findings=[json.dumps(result,sort_keys=True)])
 record['result_sha256']=sha256(_canonical(record)).hexdigest();return record


_oracle.oracle_id='ocd-blaikie-joshua-retained-native-independent-oracle'
_oracle.oracle_version='1'


if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--no-native',action='store_true');args=p.parse_args()
 for member in SOURCES:print(json.dumps(check(member,args.directory/member,native=False),sort_keys=True),flush=True)
