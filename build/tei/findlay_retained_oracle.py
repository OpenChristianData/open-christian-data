"""Check extracted existing Findlay TEI against raw source, independently."""
from copy import deepcopy
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import subprocess
import sys
import xml.etree.ElementTree as ET
from lxml import etree
from build.tei.expositors_bible_findlay_validation import validate_findlay_member
from ocd_kernel.reconstruction import SourceManifest,CandidatePackage
from ocd_kernel.reconstruction.contract import _canonical,_runtime_binding

ROOT=Path(__file__).resolve().parents[2];NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
WORK='expositors-bible--g-g-findlay'
SOURCE={
 'findlay-expositoreph':('findlay_expositoreph.xml','697b5713691c402b9d127296cf7d68c2e5aacae66fc6e8a052d6ac9206b3f771',5744,5644,14),
 'findlay-expositorgal':('findlay_expositorgal.xml','9fcb5bc51a36d49f68a94d1852a57ffcefd8896d7e7f8ae7036aae1da4a8fc6d',4504,4435,22)}
PRODUCER_IMPORTS=('build/__init__.py','build/tei/__init__.py','build/tei/findlay_retained_prepare.py','ocd_kernel/__init__.py','ocd_kernel/lib/__init__.py','ocd_kernel/lib/path_io.py','ocd_kernel/lib/storage_topology.py','ocd_kernel/reconstruction/__init__.py','ocd_kernel/reconstruction/contract.py')
ORACLE_IMPORTS=tuple(sorted(set(PRODUCER_IMPORTS)-{'build/tei/findlay_retained_prepare.py'}|{'build/tei/findlay_retained_oracle.py','build/tei/expositors_bible_findlay_validation.py'}))
def sha(raw):return sha256(raw).hexdigest()

def observed_imports(module,extra_import=None):
 script='''import importlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve(strict=True);sys.path.insert(0,str(root));before=set(sys.modules)
importlib.import_module(sys.argv[2])
if len(sys.argv)>3:importlib.import_module(sys.argv[3])
print(json.dumps(sorted({Path(m.__file__).resolve().relative_to(root).as_posix() for name,m in sys.modules.copy().items() if name not in before and getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(root)})))'''
 args=[sys.executable,'-I','-B','-c',script,str(ROOT),module]
 if extra_import:args.append(extra_import)
 return json.loads(subprocess.run(args,check=True,capture_output=True,text=True).stdout)
def import_closure(module='build.tei.findlay_retained_oracle',extra_import=None):
 observed=observed_imports(module,extra_import);expected=ORACLE_IMPORTS if module=='build.tei.findlay_retained_oracle' else PRODUCER_IMPORTS if module=='build.tei.findlay_retained_prepare' else None
 if expected is None or observed!=sorted(expected):raise ValueError('Findlay observed import closure differs: '+str(dict(unexpected=sorted(set(observed)-set(expected or [])),missing=sorted(set(expected or [])-set(observed)))))
 return sha(_canonical([dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in observed]))

@lru_cache(maxsize=1)
def schema():return etree.XMLSchema(etree.parse(str(ROOT/'ocd_kernel/tei/vendor/xsd/tei_all.xsd')))

@lru_cache(maxsize=1)
def original_tree():
 raw=(ROOT/'reports/_logs/findlay-existing-install-20261003-v1/retained-final-package/content.tei.xml').read_bytes()
 if sha(raw)!='2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134':raise ValueError('Findlay original native changed')
 return etree.fromstring(raw)

def check(member,directory):
 file,pin,count,body_count,comments=SOURCE[member];raw=(ROOT/'raw/ccel/expositors-bible'/file).read_bytes()
 if sha(raw)!=pin:raise ValueError('Findlay retained source changed')
 source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
 lsource=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True))
 stdfields=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in source.iter()]
 lfields=[(n.tag if isinstance(n.tag,str) else '#comment',dict(n.attrib),n.text or '',n.tail or '',len(n)) for n in lsource.iter()]
 if stdfields!=lfields:raise ValueError('Independent raw source parser corroboration failed')
 nodes=[n for n in source.iter() if isinstance(n.tag,str)];ordinals={n:i for i,n in enumerate(nodes,1)}
 if len(nodes)!=count:raise ValueError('Full Findlay source census changed')
 head=source.find('ThML.head');body=source.find('ThML.body');title=head.findtext('.//DC.Title')
 path=directory/'content.tei.xml';tree=etree.parse(str(path));actual=tree.xpath('//*[@xml:id="'+member+'"]')
 if len(actual)!=1 or tree.getroot().get(XML+'id')!=member+'--candidate':raise ValueError('Findlay edition/member envelope differs')
 native=next(n for n in actual if n.tag==NS+'div');normalized=deepcopy(native)
 root=tree.getroot();text=root.find(NS+'text');container=text.find(NS+'body') if text is not None else None
 if dict(root.attrib)!={XML+'id':member+'--candidate'} or [n.tag for n in root]!=[NS+'teiHeader',NS+'text'] or text is None or dict(text.attrib)!={XML+'lang':'en'} or len(text)!=1 or container is None or dict(container.attrib) or len(container)!=1 or container[0] is not native or any((n.text or '') or (n.tail or '') for n in [root,text,container]):raise ValueError('Findlay exact outer readable body wrapper differs')
 account=json.loads((directory/'source-accountability.json').read_bytes())
 if account['member_id']!=member or account['source_sha256']!=pin or account['source_bytes']!=len(raw) or account['source_path']!='raw/ccel/expositors-bible/'+file or account['source_root_attributes']!=source.attrib:raise ValueError('Findlay source accounting envelope differs')
 paths={};expected_rows=[]
 def walk(n,parent,xpath,index):
  ordinal=ordinals[n];identity=member+f'-feature-{ordinal:05d}';paths[n]=xpath
  expected_rows.append(dict(feature_id=identity,member_id=member,source_tag=n.tag,source_selector=xpath,source_attributes=dict(n.attrib),source_parent_ordinal=ordinals.get(parent),source_child_ordinal=index,source_direct_text=n.text or '',source_tail_text=n.tail or ''))
  counts=Counter()
  for i,c in enumerate((c for c in n if isinstance(c.tag,str)),1):counts[c.tag]+=1;walk(c,n,xpath+'/'+c.tag+'['+str(counts[c.tag])+']',i)
 walk(source,None,'/ThML[1]',1)
 if len(account['crosswalk'])!=len(expected_rows):raise ValueError('Findlay complete original crosswalk census differs')
 for row,expected in zip(account['crosswalk'],expected_rows,strict=True):
  if any(row.get(k)!=v for k,v in expected.items()):raise ValueError('Findlay original complete crosswalk differs at '+expected['feature_id'])
 summaries=[]
 for n in body.iter('table'):
  if n.get('summary') is not None:
   identity=member+f'-feature-{ordinals[n]:05d}';target=normalized.xpath('//*[@xml:id="'+identity+'"]')[0]
   if target.get('n')!=n.get('summary'):raise ValueError('Actual native table summary differs')
   del target.attrib['n'];ln=lsource.xpath('//*[@id="'+n.get('id')+'"]')[0]
   summaries.append(dict(tei_id=identity,attribute='n',before=None,after=n.get('summary'),source_xpath=lsource.getroottree().getpath(ln)))
 if account['summary_changes']!=summaries:raise ValueError('Findlay bounded table summary accounting differs')
 acquisition_path=Path('library/works')/WORK/'forms'/(WORK+'--'+member+'--retained-en')/'editions'/(WORK+'--'+member+'--ccel-electronic')/'acquisitions'/(WORK+'--'+member+'--acquired.json')
 acquisition=json.loads((ROOT/acquisition_path).read_bytes());bases=[]
 if acquisition['source_path']!='raw/ccel/expositors-bible/'+file or acquisition['source_sha256']!=pin:raise ValueError('Findlay independent source URI authority differs')
 for n in nodes:
  href=n.get('href')
  if href is not None and not href.startswith('#') and not urlsplit(href).scheme:
   identity=member+f'-feature-{ordinals[n]:05d}';actualref=native.xpath('//*[@xml:id="'+identity+'"]')[0];target=normalized.xpath('//*[@xml:id="'+identity+'"]')[0]
   if actualref.get('target')!=href or actualref.get(XML+'base')!=acquisition['url'] or urljoin(actualref.get(XML+'base'),actualref.get('target'))!=urljoin(acquisition['url'],href):raise ValueError('Findlay actual relative URI context differs')
   del target.attrib[XML+'base'];ln=lsource.xpath(paths[n].replace('/ThML[1]','/ThML',1))[0]
   bases.append(dict(tei_id=identity,attribute=XML+'base',before=None,after=acquisition['url'],source_href=href,source_xpath=lsource.getroottree().getpath(ln)))
 if account['relative_uri_bases']!=bases or len(bases)!=(32 if member=='findlay-expositoreph' else 31) or account['source_uri_acquisition_path']!=acquisition_path.as_posix() or account['source_uri_acquisition_sha256']!=sha((ROOT/acquisition_path).read_bytes()):raise ValueError('Findlay complete relative URI accounting differs')
 measure=validate_findlay_member(normalized,raw,member,title)
 if measure['text_corrections']!=0:raise ValueError('Unassessed Findlay corrections')
 original=original_tree().xpath('//*[@xml:id="'+member+'"]')[0]
 if etree.tostring(normalized,method='c14n',with_comments=True)!=etree.tostring(original,method='c14n',with_comments=True) or account['original_native_member_c14n_sha256']!=sha(etree.tostring(original,method='c14n',with_comments=True)):raise ValueError('Actual bounded native inverse differs from original readable member')
 byid={n.get(XML+'id'):n for n in native.iter() if n.get(XML+'id')};rows={r['feature_id']:r for r in account['crosswalk']};expected_comments=[];counter=0
 lcomments=list(lsource.find('ThML.body').iter(etree.Comment))
 for i,n in enumerate(lcomments,1):
  expected_comments.append(dict(ordinal=i,kind='comment',text=n.text,tail=n.tail,source_xpath=lsource.getroottree().getpath(n),anchor_id=member+f'-comment-{i:05d}'))
 if account['body_auxiliaries']!=expected_comments or len(expected_comments)!=comments:raise ValueError('Findlay exact administrative comment payload/positions differs')
 def restore(n):
  nonlocal counter
  if not isinstance(n.tag,str):
   if n.tag is not ET.Comment:raise ValueError('Unsupported body PI requires separate scope')
   counter+=1;identity=member+f'-comment-{counter:05d}';anchor=byid[identity]
   row=account['body_auxiliaries'][counter-1]
   if anchor.get('ana')!='urn:source-comment-sha256:'+sha((n.text or '').encode()) or (anchor.tail or '')!=(n.tail or ''):raise ValueError('Findlay exact comment digest/tail attachment differs')
   result=ET.Comment(row['text']);result.tail=anchor.tail;return result
  identity=member+f'-feature-{ordinals[n]:05d}';observed=byid[identity];row=rows[identity]
  result=ET.Element(row['source_tag'],row['source_attributes']);result.text=observed.text;result.tail=observed.tail
  for child in n:result.append(restore(child))
  return result
 restored=restore(body)
 if account['body_auxiliaries']!=expected_comments or counter!=comments:raise ValueError('Findlay exact administrative comment payload/positions differs')
 if ET.canonicalize(ET.tostring(restored,encoding='unicode'),with_comments=True)!=ET.canonicalize(ET.tostring(body,encoding='unicode'),with_comments=True):raise ValueError('Findlay inverse whole source body from actual native payload differs')
 if account['source_body_c14n_sha256']!=sha(etree.tostring(lsource.find('ThML.body'),method='c14n',with_comments=True)):raise ValueError('Findlay source body C14N binding differs')
 lhead=lsource.find('ThML.head');visible=[];head_records=[]
 for ordinal,n in enumerate(lhead.iter(),1):
  xpath=lsource.getroottree().getpath(n);r=dict(ordinal=ordinal,kind='element' if isinstance(n.tag,str) else 'comment',source_xpath=xpath,tag=n.tag if isinstance(n.tag,str) else '#comment',attributes=dict(n.attrib),text=n.text,tail=n.tail)
  if not isinstance(n.tag,str):value='Retained source head comment: '+(n.text or '')
  elif (n.text or '').strip() or n.attrib:value='Source field '+xpath+': '+json.dumps(dict(attributes=dict(n.attrib),text=n.text),ensure_ascii=False,sort_keys=True)
  else:value=None
  if value is not None:r['visible_note']=value;visible.append((str(ordinal),value))
  head_records.append(r)
 if account['source_head_records']!=head_records or [(n.get('n'),n.text) for n in tree.findall('.//'+NS+'note[@type="retained-source-head-field"]')]!=visible:raise ValueError('Findlay complete head fields/rights/CSS visible evidence differs')
 prolog=[dict(node_kind='comment' if n.tag is etree.Comment else 'pi',target=n.target if n.tag is etree.PI else None,text=n.text,tail=n.tail) for n in reversed(list(lsource.itersiblings(preceding=True)))]
 if account['source_prolog']!=prolog or [(n.get('n'),n.text) for n in tree.findall('.//'+NS+'note[@type="retained-source-prolog"]')]!=[(str(i),'Retained source prolog '+str(i)+': '+json.dumps(r,ensure_ascii=False,sort_keys=True)) for i,r in enumerate(prolog,1)]:raise ValueError('Findlay literal prolog visible evidence differs')
 expected_metadata=[('title',title),('author',head.findtext('.//DC.Creator[@sub="Author"][@scheme="short-form"]')),('editor',head.findtext('.//DC.Creator[@sub="Editor"][@scheme="short-form"]'))]
 if [(n.tag,n.text) for n in tree.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt')]!=[(NS+t,v) for t,v in expected_metadata]:raise ValueError('Findlay literal primary metadata differs')
 schema().assertValid(tree)
 ids={n.get(XML+'id') for n in tree.iter() if n.get(XML+'id')}
 for ref in tree.iter(NS+'ref'):
  target=ref.get('target','')
  if target.startswith('#') and target[1:] not in ids:raise ValueError('Findlay native local target closure differs')
 return dict(status='pass',member_id=member,tei_sha256=sha(path.read_bytes()),source_sha256=pin,whole_source_elements=count,source_body_elements=body_count,comments=comments,measure=measure,source_inverse='pass',original_native_inverse='pass',table_summary_changes=summaries,relative_uri_bases=bases,p5='pass',graphic_count=0,literal_replacement_character_count=raw.decode('utf-8').count('\ufffd'),native_projection='not measured by source checker; separate actual category gate')

def _oracle(manifest,candidate):
 manifest.verify();candidate.verify_integrity();member=manifest.record['scope']['member_id'];result=check(member,candidate.path)
 authorities={a['role']:a['sha256'] for a in manifest.record['authorities']}
 record=dict(status='pass',oracle_id=_oracle.oracle_id,oracle_version=_oracle.oracle_version,implementation_sha256=sha(Path(__file__).read_bytes()),import_closure_sha256=import_closure(),runtime=_runtime_binding(),source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,profile_sha256=authorities['complete-source-feature-profile'],package_schema_sha256=authorities['candidate-package-schema'],source_sha256=result['source_sha256'],xsd_sha256=authorities['tei-validation-schema'],policy_sha256=authorities['independent-validation-policy'],findings=[json.dumps(result,sort_keys=True)])
 record['result_sha256']=sha(_canonical(record));return record
_oracle.oracle_id='ocd-findlay-existing-readable-independent-source-oracle';_oracle.oracle_version='1'
