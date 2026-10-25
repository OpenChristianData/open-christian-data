"""Independent retained-source/actual-TEI oracle for the two Chadwick witnesses.

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
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.contract import _canonical, _runtime_binding

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--g-a-chadwick'
SOURCES={
 'chadwick-mark':('chadwick_mark.xml','1bbe36d072f96184a6d6c46a13d0b0b4e6c395f02efd5e769dc87e2d6fcf4bf2',('i','ii'),('xix',),2453),
 'chadwick-exodus':('chadwick_expositor2.xml','aa254cd88c1d64f9e5210288079a289dc57fc634410488662e0e721da8874c61',('i','ii','iii'),('xli',),4251),
}
SPECS={m:dict(form='chadwick-expositors-retained-english',edition=WORK+'-'+m.removeprefix('chadwick-')+'-retained-electronic',acquisition=WORK+'-'+m.removeprefix('chadwick-')+'-acquired') for m in SOURCES}
OLD_PACKAGE=ROOT/'reports/_logs/chadwick-existing-install-20261003-v1/immutable-prior-mark-package'
OLD_TEI_SHA='09a167b7911389682950fb3d9676d315bb38a0fd8490158005ec26f2537693b6'
OLD_ACCOUNT_SHA='a1e46606dfa4ac4cab8a97be4f015a715ad7875c97ca93614d2daee2c1f387e9'


# Exact observed fresh import inventories. These are import-time closures; all
# runtime/schema/source dependencies are separately frozen by installation.
ORACLE_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/chadwick_retained_native_oracle.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py'''.split())
PRODUCER_IMPORTS = tuple('''build/__init__.py build/tei/__init__.py build/tei/chadwick_retained_native_emitter.py build/tei/chadwick_retained_native_prepare.py build/tei/chadwick_retained_scope.py ocd_kernel/__init__.py ocd_kernel/lib/__init__.py ocd_kernel/lib/path_io.py ocd_kernel/lib/storage_topology.py ocd_kernel/reconstruction/__init__.py ocd_kernel/reconstruction/contract.py ocd_kernel/tei/__init__.py ocd_kernel/tei/normalization.py ocd_kernel/tei/projection_profile.py ocd_kernel/tei/writer.py'''.split())


def import_closure(module='build.tei.chadwick_retained_native_oracle', *, root=ROOT, extra_import=None):
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
 if tuple(observed)!=expected:raise ValueError('Chadwick observed first-party import closure differs: '+repr(observed))
 records=[dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in observed]
 return sha256(_canonical(records)).hexdigest()


def _parse(raw:bytes)->ET.Element:
 return ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))


def _fields(node):
 return [(n.tag,dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in node.iter()]


@lru_cache(maxsize=1)
def _p5_schema():
 return etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))


def _check_mark(raw,source,lsource,actual,path,account,source_base):
 """Derive the old native structure and semantics from the primary witness.

 The immutable old TEI supplies only the formatter's whitespace envelope and
 exact byte preservation target. Every source element, role, semantic attribute,
 title carrier, direct/tail field and ownership is expected from raw ThML.
 """
 old=(OLD_PACKAGE/'content.tei.xml').read_bytes()
 if sha256(old).hexdigest()!=OLD_TEI_SHA:raise ValueError('Original Mark TEI pin differs')
 old_account=(OLD_PACKAGE/'source-accountability.json').read_bytes()
 if sha256(old_account).hexdigest()!=OLD_ACCOUNT_SHA:raise ValueError('Original Mark accounting pin differs')
 legacy=json.loads(old_account);body=source.find('ThML.body');lbody=lsource.find('ThML.body')
 old_text=_parse(old).find(NS+'text');old_body=old_text.find(NS+'body')
 if old_text.attrib!={} or old_body.attrib!={XML+'id':'mark-whole-body'} or len(old_text)!=1:raise ValueError('Original Mark whole-body envelope differs')
 expected=ET.Element(NS+'text',dict(old_text.attrib));expected.text=old_text.text;expected.tail=None
 expected_body=ET.SubElement(expected,NS+'body',dict(old_body.attrib));expected_body.text=old_body.text;expected_body.tail=old_body.tail
 if (old_text.text or '').strip() or (old_text.tail or '').strip() or (old_body.text or '').strip() or (old_body.tail or '').strip():raise ValueError('Unexpected readable legacy envelope text')
 source_ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
 mapping={'div1':'div','div2':'div','div':'div','p':'p','h1':'ab','h2':'ab','h3':'ab','h4':'ab','ul':'list','li':'item','scripRef':'ref','scripCom':'ab','i':'hi','note':'note','verse':'lg','l':'l','span':'seg','blockquote':'quote','insertIndex':'milestone','a':'ref'}
 ordinal=0;source_pairs=[];changes=[];unresolved=[]
 original_text=old[old.index(b'<text>'):old.index(b'</text>')+len(b'</text>')]
 def observe(node,parent):
  nonlocal ordinal
  if node.tag is ET.Comment:
   if (node.tail or '').strip():raise ValueError('Readable source comment tail is unsupported by legacy policy')
   return
  if not isinstance(node.tag,str) or node.tag not in mapping:raise ValueError('Unmapped primary Mark source role')
  ordinal+=1;identity=node.get('id') or f'mark-generated-{ordinal:05d}'
  tag=mapping[node.tag];attrs={XML+'id':identity};additions={}
  rend=['source-'+k+':'+node.get(k) for k in ('class','style','progress','type') if node.get(k)]
  if node.tag=='i':rend.insert(0,'italic')
  if rend:attrs['rend']='; '.join(rend)
  if node.tag=='div1':attrs['type']='title-page' if node.get('id')=='i' else 'contents' if node.get('id')=='ii' else 'indexes' if node.get('id')=='xix' else 'chapter'
  if node.tag=='div2':attrs['type']='commentary-section'
  if node.tag=='div':attrs['type']='source-division'
  if re.fullmatch('h[1-4]',node.tag):attrs['type']='heading';attrs['rend']='source-'+node.tag;additions['rend']=attrs['rend']
  if node.tag=='blockquote':attrs['type']='block'
  if node.tag=='verse':attrs['type']='verse'
  if node.tag=='note' and node.get('n') is not None:attrs['n']=node.get('n')
  if node.tag=='insertIndex':attrs['unit']='source-index'
  if node.tag in {'scripRef','scripCom'}:
   attrs['type']='scripture' if node.tag=='scripRef' else 'scripture-commentary'
   if node.get('osisRef'):attrs['corresp']='urn:osis:'+quote(node.get('osisRef'),safe=':.-')
   if node.tag=='scripRef' and node.get('osisRef'):attrs['cRef']=node.get('osisRef').replace('Bible:','')
   if node.get('passage'):attrs['n']=node.get('passage')
   if node.get('parsed'):attrs['source']='urn:ccel-thml-parsed:'+quote(node.get('parsed'),safe='')
  for key in ('prev','next'):
   value=node.get(key)
   if value is not None:
    target=value.removeprefix('#')
    if target in source_ids:attrs[key]='#'+target
    else:unresolved.append(dict(source_id=node.get('id'),attribute=key,literal=value))
  if node.tag=='a':
   attrs['type']='source-navigation';href=node.get('href')
   if href is None:raise ValueError('Unexpected Mark source anchor without href')
   attrs['target']=href
   if not href.startswith('#') and not urlsplit(href).scheme:attrs[XML+'base']=source_base;additions['xml:base']=source_base
  out=ET.SubElement(parent,NS+tag,attrs);out.text=node.text;out.tail=node.tail
  if node.get('title') is not None:ET.SubElement(out,NS+'head',{'type':'source-title'}).text=node.get('title')
  source_pairs.append((node,out,ordinal))
  if additions:
   pattern=rb'<[A-Za-z]+(?=[ >])[^>]*\bxml:id="'+re.escape(identity.encode('ascii'))+rb'"[^>]*>'
   matches=list(re.finditer(pattern,original_text))
   if len(matches)!=1:raise ValueError('Independent original Mark opening-tag identity differs')
   before=matches[0].group(0);after=before[:-1]+b''.join(b' '+key.encode('ascii')+b'="'+value.encode('ascii')+b'"' for key,value in additions.items())+b'>'
   changes.append(dict(source_ordinal=ordinal,source_tag=node.tag,tei_xml_id=identity,attributes=additions,old_start=before.decode('utf8'),new_start=after.decode('utf8')))
  for child in node:observe(child,out)
 for n in body:observe(n,expected_body)
 if ordinal!=2405:raise ValueError('Whole Mark element census differs')
 if _fields(expected)!=_fields(actual):
  for i,(a,b) in enumerate(zip(_fields(expected),_fields(actual))):
   if a!=b:raise ValueError(f'Independent Mark actual native fields/roles/ownership differ at {i}: {a[:2]} != {b[:2]}')
  raise ValueError('Independent Mark actual native node cardinality differs')
 if unresolved!=[dict(source_id='i',attribute='prev',literal='toc'),dict(source_id='xix.ii',attribute='next',literal='toc')]:raise ValueError('Mark unresolved literal toc metadata exclusions differ '+repr(unresolved))
 candidate=path.read_bytes()
 if candidate.count(b'<text>')!=1 or candidate.count(b'</text>')!=1:raise ValueError('Mark exact readable text envelope differs')
 candidate_text=candidate[candidate.index(b'<text>'):candidate.index(b'</text>')+len(b'</text>')]
 restored_native=candidate_text
 for change in changes:
  after=change['new_start'].encode('utf8');before=change['old_start'].encode('utf8')
  if restored_native.count(after)!=1:raise ValueError('Independent Mark bounded annotation inverse cardinality differs')
  restored_native=restored_native.replace(after,before,1)
 if restored_native!=original_text:raise ValueError('Independent original Mark readable native byte inverse differs')
 if account.get('annotation_changes')!=changes or len(changes)!=534:raise ValueError('Mark annotation accounting differs')
 if account.get('original_native_tei_sha256')!=OLD_TEI_SHA or account.get('original_account_sha256')!=OLD_ACCOUNT_SHA or account.get('original_native_text_sha256')!=sha256(original_text).hexdigest():raise ValueError('Mark original-byte conservation pins differ')
 for key in ('source_body_tag','source_body_attributes','source_body_text','source_body_tail','source_root_attributes'):
  value={'source_body_tag':body.tag,'source_body_attributes':body.attrib,'source_body_text':body.text,'source_body_tail':body.tail,'source_root_attributes':source.attrib}[key]
  if account.get(key)!=value:raise ValueError('Mark complete source envelope accounting differs')
 comments=[dict(path=lsource.getroottree().getpath(n),text=n.text,tail=n.tail,parent_path=lsource.getroottree().getpath(n.getparent()),child_index=list(n.getparent()).index(n)) for n in lbody.iter() if n.tag is etree.Comment]
 if len(comments)!=10 or account.get('source_body_comments')!=comments:raise ValueError('Mark administrative comment positions/fields differ')
 if len(account.get('crosswalk',[]))!=len(source_pairs):raise ValueError('Mark original source crosswalk census differs')
 for row,(n,out,index) in zip(account['crosswalk'],source_pairs,strict=True):
  if row.get('source_tag')!=n.tag or row.get('attributes')!=dict(n.attrib) or row.get('direct_text')!=(n.text or '') or row.get('tail_text')!=(n.tail or ''):raise ValueError('Mark primary source crosswalk fields differ')
 # The complete historical ledger is retained unchanged for its original native
 # fields, while new annotations and header evidence have separate typed fields.
 for key,value in legacy.items():
  if key not in {'source_prolog','source_head_records','source_root_attributes','source_head_xml','source_path'} and account.get(key)!=value:raise ValueError('Mark historical source ledger was rewritten '+key)
 native={n.get(XML+'id'):n for n in actual.iter() if n.get(XML+'id')}
 source_to_id={id(n):out.get(XML+'id') for n,out,_ in source_pairs}
 def inverse(n):
  if n.tag is ET.Comment:result=ET.Comment(n.text);result.tail=n.tail;return result
  result=ET.Element(n.tag,dict(n.attrib))
  real=native[source_to_id[id(n)]] if n is not body else None
  result.text=real.text if real is not None else n.text;result.tail=real.tail if real is not None else n.tail
  for child in n:result.append(inverse(child))
  return result
 restored=inverse(body)
 if ET.canonicalize(ET.tostring(restored,encoding='unicode'),with_comments=True)!=ET.canonicalize(ET.tostring(body,encoding='unicode'),with_comments=True):raise ValueError('Independent Mark actual-readable source body inverse differs')
 if account.get('source_body_c14n_sha256')!=sha256(etree.tostring(lbody,method='c14n',with_comments=True)).hexdigest():raise ValueError('Mark source body C14N pin differs')
 return dict(original_native_text_byte_inverse_pass=True,original_native_text_sha256=sha256(original_text).hexdigest(),bounded_additive_annotation_count=len(changes),source_elements=ordinal,source_heading_roles=sum(n.tag.startswith('h') for n,_,_ in source_pairs),source_unresolved_metadata_exclusions=unresolved,actual_native_attribute_roles_pass=True,actual_native_text_fields_order_ownership_pass=True,actual_tei_backed_source_body_inverse_pass=True)


def _metadata_check(member,directory,raw,account):
 filename,pin,front,back,full_count=SOURCES[member];spec=SPECS[member]
 relative=Path('library/works')/WORK/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
 acquired=(ROOT/relative).read_bytes();acquisition=json.loads(acquired)
 previous=None
 if member=='chadwick-mark':
  manifest_raw=(OLD_PACKAGE/'manifest.json').read_bytes()
  if sha256(manifest_raw).hexdigest()!='51397086b9b526250c45cb223df13ef329492cee8a4a9e50be2ec22993a51554':raise ValueError('Immutable Mark original package manifest differs')
  manifest=json.loads(manifest_raw)
  expected_names={'content.tei.xml','source-accountability.json','provenance.json','README.source.md','unresolved.jsonl'}
  if {m['name'] for m in manifest['members']}!=expected_names or len(manifest['members'])!=5:raise ValueError('Immutable original Mark package member envelope differs')
  for item in manifest['members']:
   value=(OLD_PACKAGE/item['name']).read_bytes()
   if len(value)!=item['bytes'] or sha256(value).hexdigest()!=item['sha256']:raise ValueError('Immutable original Mark package member differs')
  previous=dict(package_members=[dict(name=name,bytes=len((OLD_PACKAGE/name).read_bytes()),sha256=sha256((OLD_PACKAGE/name).read_bytes()).hexdigest()) for name in sorted(expected_names|{'manifest.json'})],original_native_text_sha256=account['original_native_text_sha256'],bounded_additive_annotation_count=534)
 scope=('Complete retained CCEL electronic volume, including every original title/front matter, commentary part, generated index and note; exactly one of the two already acquired Chadwick editions. Human review, print collation, rights clearance and publication remain separate. No new source or image acquisition.')
 expected=dict(contract='ocd-chadwick-existing-retained-provenance-v1',status='nonaccepted',work_id=WORK,member_id=member,
  identity=dict(work_id=WORK,textual_form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition']),
  source_path='raw/ccel/expositors-bible/'+filename,source_sha256=pin,source_bytes=len(raw),conversion_route='bounded-existing-readable-annotation-repair' if member=='chadwick-mark' else 'existing-downloaded-companion-completion',scope=scope,
  producer=dict(path='build/tei/chadwick_retained_native_prepare.py',sha256=sha256((ROOT/'build/tei/chadwick_retained_native_prepare.py').read_bytes()).hexdigest()),
  emitter=dict(ancestor_path='build/tei/ccel_retained_native_emitter.py',ancestor_sha256='a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f',derivative_path='build/tei/chadwick_retained_native_emitter.py',derivative_sha256=sha256((ROOT/'build/tei/chadwick_retained_native_emitter.py').read_bytes()).hexdigest(),used_for_this_member=member=='chadwick-exodus'),
  primary_acquisition=dict(path=relative.as_posix(),bytes=len(acquired),sha256=sha256(acquired).hexdigest(),url=acquisition['url'],source_path=acquisition['source_path'],source_sha256=acquisition['source_sha256'],source_bytes=acquisition['source_bytes']),
  original_mark=previous,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
 if json.loads((directory/'provenance.json').read_bytes())!=expected:raise ValueError('Exact composite producer/source/acquisition/original package provenance differs')
 unresolved=dict(id=member+'-human-rights-print-assets',status='unresolved',detail=scope)
 if (directory/'unresolved.jsonl').read_bytes()!=_canonical(unresolved):raise ValueError('Exact qualified unresolved record differs')


def check(member_id:str,directory:Path,*,native=False)->dict:
 filename,pin,front,back,full_count=SOURCES[member_id]
 raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes()
 if sha256(raw).hexdigest()!=pin:raise ValueError('Retained source identity differs')
 source=_parse(raw);body=source.find('ThML.body');head=source.find('ThML.head')
 if body is None or head is None:raise ValueError('Complete source head/body required')
 spec=SPECS[member_id]
 acquisition_path=ROOT/'library/works'/WORK/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
 acquisition=json.loads(acquisition_path.read_bytes())
 source_base='https://www.ccel.org/ccel/chadwick/'+('mark.html' if member_id=='chadwick-mark' else 'expositor2.html')
 if acquisition['url']!=source_base or acquisition['source_sha256']!=pin or acquisition['source_path']!='raw/ccel/expositors-bible/'+filename:raise ValueError('Primary retained source URL context differs')
 if sum(isinstance(n.tag,str) for n in source.iter())!=full_count:raise ValueError('Whole retained source census differs')
 # Secondary parser corroborates every source tree field, before any TEI comparison.
 lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 left=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in source.iter()]
 right=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in lsource.iter()]
 if left!=right:raise ValueError('Independent source parser corroboration differs')
 path=directory/'content.tei.xml';candidate=_parse(path.read_bytes());actual=candidate.find(NS+'text')
 if candidate.tag!=NS+'TEI' or dict(candidate.attrib)!={XML+'id':member_id} or candidate.text is not None or candidate.tail is not None or [n.tag for n in candidate]!=[NS+'teiHeader',NS+'text'] or candidate[0].tail is not None or len(candidate.findall(NS+'text'))!=1 or actual is None:raise ValueError('Exact TEI outer payload envelope differs')
 ts=candidate.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt')
 creators=head.findall('.//DC.Creator')
 header_values=[('title',head.findtext('.//DC.Title')),('author',next(n.text for n in creators if n.get('sub')=='Author' and n.get('scheme')=='short-form')),('editor',next(n.text for n in creators if n.get('sub')=='Editor' and n.get('scheme')=='short-form'))]
 if ts is None or [(n.tag,n.text) for n in ts] != [(NS+t,v) for t,v in header_values]:raise ValueError('Primary title/author/editor header identity differs')
 account=json.loads((directory/'source-accountability.json').read_bytes())
 if member_id=='chadwick-mark':
  mark_result=_check_mark(raw,source,lsource,actual,path,account,source_base)
  source_records=[dict(source_tag=n.tag if isinstance(n.tag,str) else '#comment') for n in body.iter() if n is not body]
  join_events=[]
 else:
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
 if account.get('source_document_prefix')!=prefix:raise ValueError('Literal source XML declaration/DOCTYPE/prolog prefix accounting differs')
 prefix_notes=candidate.findall('.//'+NS+'note[@type="retained-source-document-prefix"]')
 if len(prefix_notes)!=1 or prefix_notes[0].text!=prefix:raise ValueError('Visible literal source document prefix differs')
 if account.get('source_head_xml')!=etree.tostring(lhead,encoding='unicode'):raise ValueError('Complete source head serialization differs')
 _metadata_check(member_id,directory,raw,account)
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
  limitations=['Human acceptance not recorded','No print collation','Rights/publication unresolved','Volume XML scope only; author/series completeness open'])
 if member_id=='chadwick-mark':result.update(mark_result)
 if native:raise ValueError('Actual genre projection is a separate bounded installation-stage probe')
 return result


def _oracle(source:SourceManifest,candidate:CandidatePackage)->dict:
 source.verify();candidate.verify_integrity()
 member=source.record['source_id'].removeprefix('ccel-chadwick-retained-native-').removesuffix('-v1')
 if member not in SOURCES or candidate.manifest['status']!='nonaccepted' or candidate.manifest['converter']!=source.record['converter']:raise ValueError('Candidate source/converter binding differs')
 result=check(member,candidate.path,native=False)
 if source.authority_path('retained-thml').read_bytes()!=(ROOT/'raw/ccel/expositors-bible'/SOURCES[member][0]).read_bytes():raise ValueError('Candidate retained authority differs')
 if candidate.member_bytes('README.source.md')!=source.authority_path('source-local-attribution-readme').read_bytes():raise ValueError('Exact visible source attribution authority binding differs')
 profile=json.loads(source.authority_path('volume-profile').read_bytes());filename,pin,front,back,count=SOURCES[member]
 primary=_parse((ROOT/'raw/ccel/expositors-bible'/filename).read_bytes());body=primary.find('ThML.body')
 if profile['member_id']!=member or profile['work_id']!=WORK or profile['acquired_work_volumes']!=2 or profile['body_tags']!=dict(Counter(n.tag for n in body.iter() if isinstance(n.tag,str))) or profile['front']!=list(front) or profile['back']!=list(back) or profile['source']['sha256']!=pin or profile['source']['bytes']!=len((ROOT/'raw/ccel/expositors-bible'/filename).read_bytes()) or profile['source']['elements']!=count or profile['source']['form']!=SPECS[member]['form'] or profile['source']['edition']!=SPECS[member]['edition'] or profile['source']['acquisition']!=SPECS[member]['acquisition'] or profile['oracle_imports']!=list(ORACLE_IMPORTS) or profile['producer_imports']!=list(PRODUCER_IMPORTS) or profile['producer_import_closure_sha256']!=import_closure('build.tei.chadwick_retained_native_prepare'):raise ValueError('Exact current source scope/profile/census/import binding differs')
 raw=(ROOT/'raw/ccel/expositors-bible'/filename).read_bytes();full=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False));lbody=full.find('ThML.body')
 spec=dict(volume=1 if member=='chadwick-mark' else 2,path='raw/ccel/expositors-bible/'+filename,sha256=pin,bytes=len(raw),elements=count,body_elements=sum(isinstance(n.tag,str) for n in body.iter()),native_source_elements=sum(isinstance(n.tag,str) for n in body.iter())-1,body_comments=10,tbody_wrappers=0,front=list(front),back=list(back),edition=SPECS[member]['edition'],acquisition=SPECS[member]['acquisition'],source_base_url='https://www.ccel.org/ccel/chadwick/'+('mark.html' if member=='chadwick-mark' else 'expositor2.html'),route='bounded-existing-readable-annotation-repair' if member=='chadwick-mark' else 'existing-downloaded-companion-completion',form=SPECS[member]['form'])
 if profile['source']!=spec or profile['source_body_c14n_sha256']!=sha256(etree.tostring(lbody,method='c14n',with_comments=True)).hexdigest() or profile['genre']!='commentary' or profile['contract']!='ocd-chadwick-complete-retained-volume-profile-v1':raise ValueError('Exact complete source profile and C14N identity differs')
 acquired=Path('library/works')/WORK/'forms'/SPECS[member]['form']/'editions'/SPECS[member]['edition']/'acquisitions'/(SPECS[member]['acquisition']+'.json')
 if source.authority_path('primary-acquired-url-context').read_bytes()!=(ROOT/acquired).read_bytes():raise ValueError('Current primary acquisition authority binding differs')
 permission=source.authority_path('ccel-permission').read_bytes()
 if permission!=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes() or b'Sourced via CCEL.org.' not in candidate.member_bytes('README.source.md') or b'must not be sold' not in candidate.member_bytes('README.source.md'):raise ValueError('Current visible retained source permission evidence differs')

 record=dict(status='pass',oracle_id=_oracle.oracle_id,oracle_version=_oracle.oracle_version,
  implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=import_closure(),
  runtime=_runtime_binding(),source_manifest_sha256=source.sha256,candidate_sha256=candidate.sha256,
  profile_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='complete-source-feature-profile'),
  package_schema_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='candidate-package-schema'),
  source_sha256=result['source_sha256'],xsd_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='tei-validation-schema'),
  policy_sha256=next(a['sha256'] for a in source.record['authorities'] if a['role']=='independent-validation-policy'),findings=[json.dumps(result,sort_keys=True)])
 record['result_sha256']=sha256(_canonical(record)).hexdigest();return record


_oracle.oracle_id='ocd-chadwick-retained-native-independent-oracle'
_oracle.oracle_version='1'


if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);p.add_argument('--no-native',action='store_true');args=p.parse_args()
 for member in SOURCES:print(json.dumps(check(member,args.directory/member,native=False),sort_keys=True),flush=True)
