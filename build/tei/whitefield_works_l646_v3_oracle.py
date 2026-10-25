"""Independent literal-field successor oracle; never imports the producer."""
from pathlib import Path
from hashlib import sha256
import json
from copy import deepcopy
from lxml import etree
from html5lib import parse
from build.tei.whitefield_works_l646_v2_oracle import _oracle as prior_oracle
ORACLE_ID='ocd-whitefield-l646-independent-semantic-envelope-oracle'
ORACLE_VERSION='3'
TEI='http://www.tei-c.org/ns/1.0';XML='{http://www.w3.org/XML/1998/namespace}';NS={'t':TEI}
def canonical(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def require(test,reason):
 if not test:raise ValueError(reason)
def text(n):
 pieces=[]
 def visit(e):
  if etree.QName(e).localname=='binaryObject':return
  if e.text:pieces.append(e.text)
  for c in e:
   visit(c)
   if c.tail:pieces.append(c.tail)
 visit(n);return ' '.join(''.join(pieces).split())
def closure(manifest):
 records=[dict(path=x['path'],sha256=x['sha256']) for x in manifest.record['authorities'] if x['role']=='validator-dependency']
 validator=manifest.record['validator'];records.append(dict(path=validator['implementation_path'],sha256=validator['implementation_sha256']))
 return sha256(canonical(sorted(records,key=lambda x:x['path']))).hexdigest()
def semantic_check(manifest,candidate):
 tree=etree.fromstring(candidate.member_bytes('content.tei.xml'));old=etree.fromstring(manifest.authority_path('previous-candidate-tei').read_bytes());account=json.loads(candidate.member_bytes('source-accountability.json'));heads=[];fields=[];notes=[];language=0;abbrcount=0;links=0;cells=0
 volumes=tree.findall('t:text/t:body/t:div',NS);oldvolumes=old.findall('t:text/t:body/t:div',NS);require(len(volumes)==3,'semantic volume count')
 for index,(ebook,volume,original) in enumerate(zip(['68976','71140','73012'],volumes,oldvolumes),1):
  doc=parse(manifest.authority_path('pg'+ebook+'-html').read_bytes(),treebuilder='lxml',namespaceHTMLElements=False);head=doc.find('head');body=doc.find('body');byid={n.get(XML+'id'):n for n in volume.iter() if n.get(XML+'id')};oldids={n.get(XML+'id') for n in original.iter() if n.get(XML+'id')}
  for ordinal,n in enumerate(head,1):
   if not isinstance(n.tag,str):continue
   heads.append(dict(ebook_id=ebook,ordinal=ordinal,tag=n.tag,attributes=dict(n.attrib),text=n.text or '',tail=n.tail or '',disposition='private-presentation' if n.tag=='style' else 'literal-source-header-note'))
   if n.tag!='style':notes.append(dict(type='source-html-head-field',n=ebook+':head:'+str(ordinal),text=json.dumps(dict(tag=n.tag,attributes=dict(n.attrib),text=n.text or ''),ensure_ascii=False,sort_keys=True)))
  source_abbr=list(body.iter('abbr'));targets=volume.xpath('.//t:hi[@rend="abbr"]',namespaces=NS);oldtargets=original.xpath('.//t:hi[@rend="abbr"]',namespaces=NS);require(len(source_abbr)==len(targets)==len(oldtargets),'abbreviation cardinality')
  for ordinal,(s,t,o) in enumerate(zip(source_abbr,targets,oldtargets),1):
   identifier=o.get(XML+'id') or 'wf-v'+str(index)+'-abbr-'+str(ordinal).zfill(4)
   require(t.get(XML+'id')==identifier and text(s)==text(t),'abbreviation target or text differs')
   notes.append(dict(type='source-abbreviation-title',target='#'+identifier,n=ebook+':abbr:'+str(ordinal),text=s.get('title')));abbrcount+=1
  source_i=list(body.iter('i'));target_i=volume.xpath('.//t:hi[@rend="i"]',namespaces=NS);require(len(source_i)==len(target_i),'italic cardinality')
  expected_lang={}
  for ordinal,(s,t) in enumerate(zip(source_i,target_i)):
   require(text(s)==text(t),'italic source attachment differs')
   if s.get('lang') is not None:require(t.get(XML+'lang')==s.get('lang'),'source italic language differs');expected_lang[id(t)]=s.get('lang');language+=1
  for s in body.iter():
   if not isinstance(s.tag,str):continue
   if s.get('lang') is not None and s.tag!='i':
    t=byid['v'+str(index)+'-'+s.get('id')];require(t.get(XML+'lang')==s.get('lang'),'source element language differs');expected_lang[id(t)]=s.get('lang');language+=1
   if s.get('title') is not None and s.tag!='abbr':notes.append(dict(type='source-title-attribute',target='#v'+str(index)+'-'+s.get('id'),n=ebook+':'+s.tag,text=s.get('title')))
   if s.attrib:fields.append(dict(ebook_id=ebook,tag=s.tag,source_id=s.get('id'),attributes=dict(s.attrib),dispositions={k:('private-source-presentation' if k in {'class','style'} else 'literal-source-semantic-carrier') for k in s.attrib}))
  source_links=[s for s in body.iter('a') if s.get('href')];target_links=volume.findall('.//t:ref',NS);require(len(source_links)==len(target_links),'literal hyperlink count differs')
  images={s.get('src'):'#v'+str(index)+'-'+s.get('id') for s in body.iter('img')}
  for s,t in zip(source_links,target_links):
   href=s.get('href');expected='#v'+str(index)+'-'+href[1:] if href.startswith('#') else images.get(href,href)
   require(t.get('target')==expected and text(s)==text(t),'literal hyperlink target, label or order differs');links+=1
  stables=list(body.iter('table'));ttables=volume.findall('.//t:table',NS);require(len(stables)==len(ttables),'table count differs')
  for s,t in zip(stables,ttables):
   srows=list(s.iter('tr'));trows=t.findall('t:row',NS);require(len(srows)==len(trows),'table row count differs')
   for sr,tr in zip(srows,trows):
    sc=[c for c in sr if c.tag in {'th','td'}];tc=tr.findall('t:cell',NS);require(len(sc)==len(tc),'table cell count differs')
    for a,b in zip(sc,tc):
     require(b.get('role','data')==('label' if a.tag=='th' else 'data') and b.get('cols','1')==a.get('colspan','1') and b.get('rows','1')==a.get('rowspan','1') and text(a)==text(b),'table cell role, span, wording or order differs');cells+=1
  # Undo only the declared additions and prove all inherited structure/attributes remain.
  conserved=deepcopy(volume);footer=conserved.xpath('.//t:div[@xml:id=$x]/t:ab',namespaces=NS,x='v'+str(index)+'-pg-footer')[0]
  for ref in list(footer.findall('t:ref',NS)):
   value=(ref.text or '')+(ref.tail or '');previous=ref.getprevious()
   if previous is None:footer.text=(footer.text or '')+value
   else:previous.tail=(previous.tail or '')+value
   footer.remove(ref)
  for n in conserved.iter():
   if n.get(XML+'id') not in oldids and (n.get(XML+'id') or '').startswith('wf-v'):del n.attrib[XML+'id']
   if XML+'lang' in n.attrib:del n.attrib[XML+'lang']
  for repaired_table,old_table in zip(conserved.findall('.//t:table',NS),original.findall('.//t:table',NS)):
   for repaired_cell,old_cell in zip(repaired_table.findall('.//t:cell',NS),old_table.findall('.//t:cell',NS)):
    if old_cell.get('rows') is None:repaired_cell.attrib.pop('rows',None)
    else:repaired_cell.set('rows',old_cell.get('rows'))
  require(etree.tostring(conserved,method='c14n')==etree.tostring(original,method='c14n'),'undeclared inherited structure or attribute change')
 observed=[]
 for n in tree.findall('t:teiHeader/t:fileDesc/t:notesStmt/t:note',NS):observed.append(dict(n.attrib,text=n.text or ''))
 require(observed==notes,'literal source metadata or abbreviation expansion differs')
 require(account.get('source_head_envelope')==heads,'complete source head envelope differs')
 require(account.get('source_body_attribute_inventory')==fields,'complete source attribute inventory differs')
 require(candidate.member_bytes('unresolved.jsonl')==manifest.authority_path('previous-unresolved').read_bytes(),'historical uncertainty changed')
 require(abbrcount==6506 and language==105 and links==235 and cells==233,'semantic aggregate source counts differ')
 return dict(abbreviations=abbrcount,languages=language,links=links,table_cells=cells,head_fields=len(heads))
def _oracle(manifest,candidate):
 manifest.verify();candidate.verify_integrity();require(closure(manifest)==manifest.record['validator']['import_closure_sha256'],'validator import closure differs')
 counts=semantic_check(manifest,candidate);result=dict(prior_oracle(manifest,candidate));result.update(oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION)
 result['findings']=list(result['findings'])+['Independent source semantic envelope passed: '+json.dumps(counts,sort_keys=True)+'. All original volume trees conserved after undoing declared literal-field additions; no producer import.']
 result.pop('result_sha256');result['result_sha256']=sha256(canonical(result)).hexdigest();return result
_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
