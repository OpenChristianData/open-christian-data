"""Finite source-semantic challenges of three complete Dods candidate documents."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from lxml import etree
from build.tei.dods_complete_prepare import ROOT,LOG,WORKS,canonical,sha
from build.tei.dods_complete_oracle import check,_p5_schema
from build.tools.prepare_dods_complete_candidates import CANDIDATES
from ocd_kernel.reconstruction import CandidatePackage

NS={'t':'http://www.tei-c.org/ns/1.0','xml':'http://www.w3.org/XML/1998/namespace'}
T='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}'
COMMON=[('paragraph-text','.//t:body//t:p','text'),('source-tail','.//t:ref','tail'),('heading-role','.//t:p[starts-with(@rend,"source-h")]','rend'),('literal-fragment-target','.//t:ref[starts-with(@target,"#")]','target'),('relative-uri-base','.//t:ref[@xml:base]',X+'base'),('literal-relative-source-target','.//t:ref[@xml:base]','target'),('index-directive','.//t:milestone[@unit="insertIndex"]','n'),('scripture-directive','.//t:milestone[@unit="scripCom"]','corresp'),('verse-line','.//t:l','text'),('page-marker','.//t:pb','n'),('source-navigation','.//t:div[@next]','next'),('missing-source-toc','.//t:div[@ana]','ana'),('inline-style','.//t:hi[@rend]','rend'),('source-span-role','.//t:seg[@type]','type'),('note-label','.//t:note[@n]','n')]
EXTRA={
 'dods-expositor1':[('gutenberg-information','.//t:back/t:div[contains(@xml:id,"xxxiii")]//t:p','text')],
 'dods-expositor1cor':[('list-role','.//t:list','rend'),('item-text','.//t:item','text'),('bold-style','.//t:hi[@rend="bold"]','rend'),('small-style','.//t:hi[@rend="small"]','rend'),('citation-style','.//t:hi[@rend="source-citation"]','rend'),('horizontal-rule','.//t:milestone[@unit="horizontal-rule"]','unit')],
 'dods-expositorjohn1':[('quotation-role','.//t:quote','type'),('literal-line-break','.//t:lb','type'),('horizontal-rule','.//t:milestone[@unit="horizontal-rule"]','unit')],
 'dods-expositorjohn2':[('quotation-role','.//t:quote','type'),('list-role','.//t:list','rend'),('item-text','.//t:item','text'),('horizontal-rule','.//t:milestone[@unit="horizontal-rule"]','unit'),('bounded-index-container-role','.//t:div[@type="source-index-container"]','type')]
}
EXPECTED={'dods-genesis':33,'dods-first-corinthians':38,'dods-gospel-john':69}

def volume(tree,key,member):
 return tree.find(T+'text') if len(WORKS[key])==1 else tree.find(T+'text/'+T+'group')[WORKS[key].index(member)]

def challenges(key,package):
 payload={name:package.member_bytes(name) for name in package.member_names if name!='manifest.json'};raw=payload['content.tei.xml'];results=[]
 with TemporaryDirectory(prefix='dods-semantic-challenge-') as temporary:
  scratch=Path(temporary)
  def reject(label,changed):
   files=dict(payload);files.update(changed);tree=etree.fromstring(files['content.tei.xml']);_p5_schema().assertValid(tree)
   for name,data in files.items():(scratch/name).write_bytes(data)
   try:check(key,scratch)
   except ValueError as error:results.append(dict(challenge=label,schema_valid=True,rejected=True,reason=str(error),changed_files=[dict(name=n,bytes=len(v),sha256=sha(v)) for n,v in changed.items()]))
   else:raise ValueError('Dods semantic challenge admitted '+label)
  def xml_reject(label,tree):reject(label,{'content.tei.xml':etree.tostring(tree,encoding='UTF-8',xml_declaration=True)})
  for member in WORKS[key]:
   for label,selector,field in COMMON+EXTRA[member]:
    tree=etree.fromstring(raw);nodes=volume(tree,key,member).xpath(selector,namespaces=NS)
    if not nodes:raise ValueError('Declared retained feature missing '+member+' '+label)
    n=next((n for n in nodes if getattr(n,field,None)),nodes[0]) if field in {'text','tail'} else nodes[0]
    if field in {'text','tail'}:setattr(n,field,(getattr(n,field) or '')+'CHALLENGE')
    else:n.set(field,(n.get(field) or '')+'CHALLENGE')
    xml_reject(member+'/'+label,tree)
   for role in ('retained-source-head-field','retained-source-document-prefix'):
    tree=etree.fromstring(raw);header=tree.find(T+'teiHeader')
    scope=header if len(WORKS[key])==1 else header.xpath('.//t:bibl[@xml:id="'+member+'-source"]',namespaces=NS)[0]
    note=scope.xpath('.//t:note[@type="'+role+'"]',namespaces=NS)[0];note.text=(note.text or '')+'CHALLENGE';xml_reject(member+'/'+role,tree)
   tree=etree.fromstring(raw);v=volume(tree,key,member);paras=v.xpath('.//t:body//t:p',namespaces=NS);p=next(n for n in paras if n.getparent().tag==T+'div');target=next(n for n in paras if n.getparent() is not p.getparent() and p not in n.iterancestors());p.getparent().remove(p);target.getparent().append(p);xml_reject(member+'/same-text-paragraph-wrong-attachment',tree)
   tree=etree.fromstring(raw);v=volume(tree,key,member);note=v.xpath('.//t:note',namespaces=NS)[0];target=next(n for n in v.xpath('.//t:p',namespaces=NS) if n is not note.getparent() and note not in n.iterancestors());note.getparent().remove(note);target.append(note);xml_reject(member+'/same-text-note-wrong-attachment',tree)
   tree=etree.fromstring(raw);v=volume(tree,key,member);groups=v.xpath('.//t:lg',namespaces=NS);origin=next(n for n in groups if len(n.findall(T+'l'))>1);line=origin.find(T+'l');target=next(n for n in groups if n is not origin);origin.remove(line);target.append(line);xml_reject(member+'/same-text-verse-wrong-attachment',tree)
   for label,field in [('administrative-comment-payload','source_text'),('source-original-attributes','source_attributes')]:
    account=json.loads(payload['source-accountability.json']);rows=account['components'][member]['features'];r=next(r for r in rows if r['source_tag']==('#comment' if field=='source_text' else 'p'))
    if field=='source_text':r[field]+='CHALLENGE'
    else:r[field]['class']='CHALLENGE'
    reject(member+'/'+label,{'source-accountability.json':canonical(account)})
  tree=etree.fromstring(raw);v=volume(tree,key,WORKS[key][0]);extra=etree.SubElement(v.find(T+'body'),T+'div');etree.SubElement(extra,T+'p').text='CHALLENGE';xml_reject('outer-body-added-payload',tree)
  tree=etree.fromstring(raw);etree.SubElement(tree.find(T+'teiHeader/'+T+'fileDesc/'+T+'sourceDesc')[0],T+'note').text='CHALLENGE';xml_reject('outer-header-added-payload',tree)
  for label,name in [('visible-permission','README.source.md'),('unresolved-extra-row','unresolved.jsonl')]:reject(label,{name:payload[name]+(b'\nCHALLENGE\n' if name.endswith('.md') else canonical({'challenge':'unrecorded'}))})
  for label,name,field in [('complete-work-count','source-accountability.json','complete_work_count'),('source-count','source-accountability.json','acquired_source_count'),('complete-source-order','source-accountability.json','source_members'),('composite-work-identity','provenance.json','complete_work_id'),('composite-source-order','provenance.json','source_members'),('composite-source-acquisition','provenance.json','component_provenance')]:
   record=json.loads(payload[name])
   if field=='component_provenance':record[field][WORKS[key][-1]]['acquisition_id']+='CHALLENGE'
   elif isinstance(record[field],int):record[field]+=1
   elif isinstance(record[field],list):record[field]=list(reversed(record[field]))+['CHALLENGE']
   else:record[field]+='CHALLENGE'
   reject(label,{name:canonical(record)})
  if key=='dods-gospel-john':
   tree=etree.fromstring(raw);g=tree.find(T+'text/'+T+'group');first=g[0];g.remove(first);g.append(first);xml_reject('complete-volume-order',tree)
   tree=etree.fromstring(raw);g=tree.find(T+'text/'+T+'group');g.remove(g[1]);xml_reject('second-volume-missing',tree)
   tree=etree.fromstring(raw);g=tree.find(T+'text/'+T+'group');third=deepcopy(g[1]);
   for n in third.iter():
    if n.get(X+'id'):n.set(X+'id',n.get(X+'id')+'-challenge')
   g.append(third);xml_reject('third-volume-added-payload',tree)
   tree=etree.fromstring(raw);g=tree.find(T+'text/'+T+'group');g[1].set(X+'id','wrong-volume-identity');xml_reject('second-volume-identity',tree)
   tree=etree.fromstring(raw);g=tree.find(T+'text/'+T+'group');note=g[0].xpath('.//t:note',namespaces=NS)[0];target=g[1].xpath('.//t:body//t:p',namespaces=NS)[0];note.getparent().remove(note);target.append(note);xml_reject('cross-volume-same-text-note-attachment',tree)
   tree=etree.fromstring(raw);bs=tree.xpath('.//t:bibl[@type="retained-source-volume"]',namespaces=NS);a=bs[0].xpath('.//t:note[@type="retained-source-head-field"]',namespaces=NS)[0];b=bs[1].xpath('.//t:note[@type="retained-source-head-field"]',namespaces=NS)[0];a.text,b.text=b.text,a.text;xml_reject('per-volume-header-source-attachment',tree)
   tree=etree.fromstring(raw);g=tree.find(T+'text/'+T+'group');g.set(X+'id','wrong-complete-group');xml_reject('complete-group-identity',tree)
 if len(results)!=EXPECTED[key]:raise ValueError('Finite Dods semantic denominator differs '+key+' '+str(len(results)))
 return results

def main():
 results=[]
 for key in WORKS:
  p=CandidatePackage.load(CANDIDATES/key/'package');rows=challenges(key,p);results.append(dict(complete_work_id=key,package_sha256=p.sha256,expected_challenges=EXPECTED[key],all_schema_valid=True,all_rejected=True,challenges=rows));print(json.dumps(dict(complete_work_id=key,rejected=len(rows),schema_valid=True)),flush=True)
 record=dict(status='pass',complete_work_count=3,acquired_source_count=4,expected_challenges=sum(EXPECTED.values()),implementation_sha256=sha(Path(__file__).read_bytes()),oracle_sha256=sha((ROOT/'build/tei/dods_complete_oracle.py').read_bytes()),members=results)
 (ROOT/LOG/'complete-semantic-challenges-v2.json').write_bytes(canonical(record))
if __name__=='__main__':main()
