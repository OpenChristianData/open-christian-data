"""Independent retained-source/actual-TEI oracle for the single complete Second Samuel work.

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
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--william-g-blaikie'
SCOPE='Complete already acquired CCEL electronic Second Samuel authored commentary: title page, all 33 substantive chapters, final indexes, notes, verse lines, page markers and full source metadata. Exactly one complete authored work and one retained source; no First Samuel or Joshua content. Human review, print collation, rights clearance and publication remain separate. No source or image acquisition.'
BOUNDARY='One complete authored commentary on The Second Book of Samuel by W.G. Blaikie, within The Expositors Bible series edited by W. Robertson Nicoll. Its own titled New York A.C. Armstrong and Son 1898 title page, chapters I-XXXIII, concluding chapter and final generated indexes define this complete book. First Samuel and Joshua are distinct titled works outside this candidate; author-catalog and series completeness are not claimed.'
LEGACY='Qualified current LIB036 converter-only replay retains the exact downloaded bytes and original-reading feature graph. September11 candidate path is access denied; historical package recovery and old oracle validation are not claimed. All historical correction alternatives remain qualified; raw readings are retained.'
SOURCES={'blaikie-expositor2sam':('blaikie_expositor2sam.xml','e3397acdd20cbc7ea8ef6c81eb10407263fe1276b40973c07cd908cf4902c379',('i',),('xxxv',),1908)}

# Exact observed fresh import inventories. These are import-time closures; all
# runtime/schema/source dependencies are separately frozen by installation.
ORACLE_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/blaikie_second_samuel_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())
PRODUCER_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/blaikie_second_samuel_emitter.py build/tei/blaikie_second_samuel_prepare.py build/tei/blaikie_second_samuel_scope.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())


def import_closure(module='build.tei.blaikie_second_samuel_oracle', *, root=ROOT, extra_import=None):
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
 if tuple(observed)!=expected:raise ValueError('Blaikie Second Samuel observed first-party import closure differs: '+repr(observed))
 records=[dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in observed]
 return sha256(_canonical(records)).hexdigest()


def _parse(raw:bytes)->ET.Element:
 return ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))


def _fields(node):
 return [(n.tag,dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in node.iter()]

def _metadata_check(member,directory,raw):
 filename,pin,front,back,count=SOURCES[member];form=WORK+'--'+member+'--retained-en';edition=WORK+'--'+member+'--ccel-electronic';acquisition=WORK+'--'+member+'--acquired'
 old=Path('reports/_logs/bennett-existing-install-20261003-v1/qualified-current-lib036-replay');log=old.parent
 def bound(path):
  value=(ROOT/path).read_bytes();return dict(path=Path(path).as_posix(),bytes=len(value),sha256=sha256(value).hexdigest())
 acq=Path('library/works')/WORK/'forms'/form/'editions'/edition/'acquisitions'/(acquisition+'.json')
 composite=dict(identity=dict(work_id=WORK,textual_form_id=form,edition_id=edition,acquisition_id=acquisition),primary_acquisition=bound(acq)|dict(url='https://www.ccel.org/ccel/blaikie/expositor2sam.html'),
  producer=bound('build/tei/blaikie_second_samuel_prepare.py'),derivative=bound('build/tei/blaikie_second_samuel_emitter.py'),ancestor=bound('build/tei/ccel_retained_native_emitter.py'),
  replay_members=[bound(old/name) for name in sorted(['README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl'])],
  replay_receipt=bound(log/'qualified-current-lib036-replay-receipt.json'),historical_profile=bound('sources/commentaries/expositors-bible/lib036.reconstruction-profile.json'),
  source_boundary=BOUNDARY)
 expected=dict(status='nonaccepted',work_id=WORK,member_id=member,source_path='raw/ccel/expositors-bible/'+filename,source_sha256=pin,source_bytes=len(raw),scope=SCOPE,legacy_basis=LEGACY,
  emitter_ancestor_sha256='a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f',emitter_sha256=composite['derivative']['sha256'],human_acceptance='not_recorded',rights='unresolved',publication='not_ready',composite_binding=composite)
 if json.loads((directory/'provenance.json').read_bytes())!=expected:raise ValueError('Exact current composite producer/source/acquisition/replay provenance differs')
 unresolved=(json.dumps(dict(id=member+'-human-rights-print-assets',status='unresolved',detail=SCOPE),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
 if (directory/'unresolved.jsonl').read_bytes()!=unresolved:raise ValueError('Exact unresolved qualification differs')
 readme=(directory/'README.source.md').read_bytes()
 for value in [b'Sourced via CCEL.org.',b'must not be sold',LEGACY.encode(),SCOPE.encode(),pin.encode(),str(len(raw)).encode(),b'no raw reading is replaced']:
  if value not in readme:raise ValueError('Visible permission/source/correction qualification differs')


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
 source_base='https://www.ccel.org/ccel/blaikie/expositor2sam.html'
 if acquisition['url']!=source_base or acquisition['source_sha256']!=pin or acquisition['source_path']!='raw/ccel/expositors-bible/'+filename:raise ValueError('Primary retained source URL context differs')
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
  if node.tag=='colgroup':raise ValueError('Second Samuel source contains no column groups')
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
 if account.get('historical_correction_alternatives')!=historical or account.get('correction_policy')!='Raw retained reading; no Second Samuel correction proposals in the retained profile':raise ValueError('Historical alternatives/preservation policy differs')
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
 complete_root=dict(tag=lsource.tag,attributes=dict(lsource.attrib),text=lsource.text,tail=lsource.tail)
 if account.get('complete_source_root')!=complete_root:raise ValueError('Complete original source root envelope differs')
 ET.SubElement(bibliog,NS+'note',{'type':'complete-source-root'}).text=json.dumps(complete_root,ensure_ascii=False,sort_keys=True)
 for ordinal,node in enumerate(lhead.iter(),1):
  value=dict(xpath=lsource.getroottree().getpath(node),kind='element' if isinstance(node.tag,str) else 'comment' if node.tag is etree.Comment else 'pi',tag=node.tag if isinstance(node.tag,str) else None,attributes=dict(node.attrib),text=node.text,tail=node.tail)
  ET.SubElement(bibliog,NS+'note',{'type':'complete-source-head-field','n':str(ordinal)}).text=json.dumps(value,ensure_ascii=False,sort_keys=True)
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
  limitations=['Human acceptance not recorded','No print collation','Rights/publication unresolved','Complete acquired Second Samuel authored work only; author/series completeness not claimed'])
 if native:raise ValueError('Actual commentary projection is a separate installation-stage probe')
 return result


def _plain(value):
 if isinstance(value,Mapping):return {key:_plain(item) for key,item in value.items()}
 if isinstance(value,(tuple,list)):return [_plain(item) for item in value]
 return value


def _expected_policy(member):
 return dict(contract='ocd-blaikie-second-samuel-independent-readable-policy-v1',member_id=member,
  independence='Declared prior exposure to the reviewed Bennett oracle. Source-specific stdlib raw parser and actual serialized TEI comparisons derive all fields/roles/order/ownership/URI bases; no producer or emitter imported. lxml separately corroborates all raw fields.',
  required=['whole actual source envelope','complete15-field raw-derived retained crosswalk including XPath selectors ordinal identity and text hashes','complete authored work boundary','exact direct and tail text roles attributes parent order','actual native source-body inverse with all10 comments','whole source header root prefix and permission','P5-valid semantic mutations','two fresh process exact six-member replays'],
  patterns=['RP-03','RP-04','RP-06','RP-11','RP-13','RP-14','RP-15'],visual='Not performed; no source images')


def _expected_profile(member,raw,spec,front,back):
 primary=_parse(raw);body=primary.find('ThML.body');comments=sum(n.tag is ET.Comment for n in body.iter())
 relative=sum(n.tag=='a' and n.get('href') and not n.get('href').startswith('#') and not urlsplit(n.get('href')).scheme for n in body.iter() if isinstance(n.tag,str))
 secondary=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
 return dict(contract='ocd-blaikie-second-samuel-complete-retained-work-profile-v1',member_id=member,work_id=WORK,source=spec,
  source_body_c14n_sha256=sha256(etree.tostring(secondary.find('ThML.body'),method='c14n',with_comments=True)).hexdigest(),
  body_tags=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))),front=list(front),back=list(back),retained_work_sources=1,complete_works=1,retained_crosswalk_field_count=15,
  source_boundary=BOUNDARY,excluded_works=['First Samuel','Joshua'],producer_import_closure_sha256=import_closure('build.tei.blaikie_second_samuel_prepare'),
  producer_imports=list(PRODUCER_IMPORTS),oracle_imports=list(ORACLE_IMPORTS),genre='commentary',
  scope='Complete acquired Second Samuel authored work; not entire author catalog or series',graphics='Source contains no images',
  adaptations=f'Exact{comments} administrative comment fields/positions; whitespace-only joins;{relative} per-reference acquired URL bases; complete native source attributes; readable original source fields and actual source-body inverse')


def _expected_authority_roles():
 roles=[('retained-thml','primary-source'),('volume-profile','complete-source-feature-profile'),('volume-policy','independent-validation-policy'),
  ('source-local-attribution-readme','source-rights-attribution'),('primary-acquired-url-context','primary-source-url-context'),('ccel-permission','source-rights-evidence'),
  ('original-source-credit','historical-source-credit'),('scope-recovery','qualified-existing-lineage-source-boundary'),('raw-preflight','whole-source-inventory'),
  ('lineage-field-negative-proof','complete-retained-crosswalk-selector-ordinal-hash-negatives'),('tei-p5-xsd','tei-validation-schema'),('candidate-package-schema','candidate-package-schema'),('frozen-emitter-ancestor','reviewed-frozen-ancestor')]
 roles.extend(('import-'+str(i),'observed-first-party-import-dependency') for i,_ in enumerate(sorted(set(ORACLE_IMPORTS+PRODUCER_IMPORTS))))
 roles.extend(('qualified-replay-'+name,'qualified-current-LIB036-converter-only-replay') for name in ('README.source.md','content.tei.xml','manifest.json','provenance.json','source-accountability.json','unresolved.jsonl'))
 roles.extend([('replay-receipt','qualified-converter-replay-receipt'),('replay-source-manifest','converter-only-execution-admission-no-oracle-pass'),('historical-profile','historical-source-profile-zero-second-samuel-corrections')])
 return roles


def _oracle(source:SourceManifest,candidate:CandidatePackage)->dict:
 source.verify();candidate.verify_integrity();record=_plain(source.record);metadata=_plain(candidate.manifest)
 member='blaikie-expositor2sam';source_id='ccel-blaikie-second-samuel-retained-native-'+member+'-v1'
 if set(record)!={'contract','source_id','work_id','ticket_id','authorities','converter','validator','package_schema','scope','source_order'}:raise ValueError('Complete source contract field set differs')
 if record['contract']!='ocd-source-manifest-v1' or record['source_id']!=source_id or record['work_id']!=WORK or record['ticket_id']!='LIB036-existing-Blaikie-Second-Samuel-only':raise ValueError('Exact retained source contract legacy identity differs')
 expected_scope=dict(kind='one-complete-existing-authored-work',member_id=member,complete_works=1,retained_sources=1,no_acquisition_or_download=True,excluded_works=['First Samuel','Joshua'])
 expected_order=dict(order='Complete original Second Samuel DOM; title page i, chapters ii through xxxiv, indexes xxxv; all comment and tail attachment')
 if record['scope']!=expected_scope or record['source_order']!=expected_order:raise ValueError('Complete source contract scope/order differs')
 if [(row['name'],row['role']) for row in record['authorities']]!=_expected_authority_roles():raise ValueError('Complete source contract authority-role census differs')
 expected_converter=dict(id='ocd-blaikie-second-samuel-retained-native-to-tei',version='1',callable='_convert',implementation_path='build/tei/blaikie_second_samuel_prepare.py',implementation_sha256=sha256((ROOT/'build/tei/blaikie_second_samuel_prepare.py').read_bytes()).hexdigest())
 expected_validator=dict(id='ocd-blaikie-second-samuel-retained-native-independent-oracle',version='1',callable='_oracle',implementation_path='build/tei/blaikie_second_samuel_oracle.py',implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=import_closure())
 expected_schema=dict(path='ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json',sha256=sha256((ROOT/'ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json').read_bytes()).hexdigest())
 if record['converter']!=expected_converter or record['validator']!=expected_validator or record['package_schema']!=expected_schema:raise ValueError('Exact source contract implementation/schema binding differs')
 if metadata['source_id']!=source_id or metadata['source_manifest']!=dict(path=source.path.relative_to(source.repository_root).as_posix(),sha256=source.sha256) or metadata['status']!='nonaccepted' or metadata['converter']!=expected_converter or metadata['package_schema']!=expected_schema:raise ValueError('Exact candidate source contract/package identity binding differs')
 result=check(member,candidate.path,native=False)
 if source.authority_path('retained-thml').read_bytes()!=(ROOT/'raw/ccel/expositors-bible'/SOURCES[member][0]).read_bytes():raise ValueError('Candidate retained authority differs')
 if source.authority_path('source-local-attribution-readme').read_bytes()!=candidate.member_bytes('README.source.md'):raise ValueError('Complete visible source credit authority differs')
 profile=json.loads(source.authority_path('volume-profile').read_bytes());filename,pin,front,back,count=SOURCES[member]
 raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();primary=_parse(raw);body=primary.find('ThML.body')
 spec=dict(volume=1,path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=sum(isinstance(n.tag,str) for n in body.iter()),body_comments=sum(n.tag is ET.Comment for n in body.iter()),tbody_wrappers=sum(n.tag=='tbody' for n in body.iter()),colgroup_wrappers=sum(n.tag=='colgroup' for n in body.iter()),native_source_elements=sum(isinstance(n.tag,str) and n.tag not in {'ThML.body','tbody'} for n in body.iter()),front=list(front),back=list(back),source_base_url='https://www.ccel.org/ccel/blaikie/expositor2sam.html',form=WORK+'--'+member+'--retained-en',edition=WORK+'--'+member+'--ccel-electronic',acquisition=WORK+'--'+member+'--acquired')
 if profile!=_expected_profile(member,raw,spec,front,back):raise ValueError('Entire independently derived source profile differs')
 policy=json.loads(source.authority_path('volume-policy').read_bytes())
 if policy!=_expected_policy(member):raise ValueError('Entire independent source policy differs')
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


_oracle.oracle_id='ocd-blaikie-second-samuel-retained-native-independent-oracle'
_oracle.oracle_version='1'


if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--no-native',action='store_true');args=p.parse_args()
 for member in SOURCES:print(json.dumps(check(member,args.directory/member,native=False),sort_keys=True),flush=True)
