"""Exact Douay replay and focused challenges to source, aliases, header and context."""
import argparse,json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
from ocd_kernel.library._common import io_path
from build.tools.prepare_original_douay_current import ROOT,BASE,canonical
from build.tei.original_douay_current_oracle import check,context_check,NS,XML

def main():
 p=argparse.ArgumentParser()
 for name in ('candidate','replay','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();c=CandidatePackage.load(a.candidate/'package');r=CandidatePackage.load(a.replay/'package')
 if c.sha256!=r.sha256 or any(c.member_bytes(n)!=r.member_bytes(n) for n in c.member_names) or (a.candidate/'validation.json').read_bytes()!=(a.replay/'validation.json').read_bytes():raise ValueError('Exact fresh-process package/validation replay differs')
 m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);raw=c.member_bytes('content.tei.xml');baseline=check(m,raw)
 a.output.mkdir(parents=True,exist_ok=False);cases=[]
 names=['wording','verse-omit','verse-duplicate','verse-order','verse-label','verse-attachment','zero-intro-omit','zero-scripture-omit','zero-chapter-renumber','duplicate-address-omit','book-omit','book-order','testament-order','appendix-omit','prayer-double-render','chapter-label','source-pointer','source-attribute-alias','article-omit','article-title','article-text','article-note-omit','article-note-label','article-attachment','article-order','null-wording','null-role','null-pointer','note-target','note-attachment','inline-style','line-break','unclosed-markup','whitespace-loss','preserve-loss','foreign-alias-namespace','foreign-envelope','header-credit','header-rights','header-date','envelope-payload']
 for name in names:
  d=etree.fromstring(raw);body=d.find(NS+'text/'+NS+'body');verses=[n for n in body.iter(NS+'ab') if n.get('type')=='verse'];first=verses[0]
  books=[n for n in body.iter(NS+'div') if n.get('type')=='book'];articles=[n for n in body.iter(NS+'div') if n.get('type')=='chapter-article'];article=articles[0]
  null=next(n for n in body.iter(NS+'ab') if n.get('type')=='source-null-absence:source-language-title')
  zero=next(n for n in body.iter(NS+'div') if n.get('type')=='chapter' and n.get('n')=='0')
  if name=='wording':first.text='Invented '+(first.text or '')
  elif name=='verse-omit':first.getparent().remove(first)
  elif name=='verse-duplicate':first.addnext(deepcopy(first))
  elif name=='verse-order':parent=first.getparent().getparent();second=verses[1].getparent();pos=parent.index(first.getparent());parent.remove(second);parent.insert(pos,second)
  elif name=='verse-label':first.set('n','999')
  elif name=='verse-attachment':first.getparent().remove(first);verses[-1].getparent().append(first)
  elif name in {'zero-intro-omit','zero-scripture-omit'}:
   wanted='0' if name=='zero-intro-omit' else '1';n=next(v for v in zero.iter(NS+'ab') if v.get('type')=='verse' and v.get('n')==wanted);n.getparent().remove(n)
  elif name=='zero-chapter-renumber':zero.set('n','1')
  elif name=='duplicate-address-omit':n=next(v for v in body.iter(NS+'div') if '-occurrence-2' in v.get(XML+'id',''));n.getparent().remove(n)
  elif name=='book-omit':books[0].getparent().remove(books[0])
  elif name=='book-order':books[0].addprevious(books[1])
  elif name=='testament-order':body.insert(0,body[-1])
  elif name=='appendix-omit':n=next(v for v in books if v.get('n')=='3-esdras');n.getparent().remove(n)
  elif name=='prayer-double-render':n=next(v for v in books if v.get('n')=='prayer-of-manasses');n.addnext(deepcopy(n))
  elif name=='chapter-label':next(n for n in body.iter(NS+'div') if n.get('type')=='chapter').set('n','999')
  elif name=='source-pointer':first.set(XML+'id','odr-source-field-'+'0'*64)
  elif name=='source-attribute-alias':books[0].set('corresp','source-attributes:%7B%22source%22%3A%22invented.json%22%7D')
  elif name=='article-omit':article.getparent().remove(article)
  elif name=='article-title':article[0].text='Invented title'
  elif name=='article-text':next(n for n in article if n.tag==NS+'ab').text='Invented article wording'
  elif name=='article-note-omit':n=next(n for n in article if n.tag==NS+'note');article.remove(n)
  elif name=='article-note-label':next(n for n in article if n.tag==NS+'note').set('n','999')
  elif name=='article-attachment':article.getparent().remove(article);articles[-1].getparent().append(article)
  elif name=='article-order':article.getparent().insert(0,article)
  elif name=='null-wording':null.text='None'
  elif name=='null-role':null.set('type','source-language-title')
  elif name=='null-pointer':null.set(XML+'id','odr-source-field-'+'1'*64)
  elif name=='note-target':next(n for n in body.iter(NS+'div') if n.get('type')=='annotation').set('corresp','#odr-invented')
  elif name=='note-attachment':n=next(n for n in body.iter(NS+'note') if n.get('type')=='inline-note');n.getparent().remove(n);verses[-1].getparent().append(n)
  elif name=='inline-style':next(n for n in body.iter(NS+'hi') if n.get('rend')=='italic').set('rend','small-caps')
  elif name=='line-break':next(n for n in body.iter(NS+'lb')).set('break','no')
  elif name=='unclosed-markup':next(n for n in body.iter(NS+'hi') if n.get(XML+'id','').startswith('odr-source-unclosed-')).attrib.pop(XML+'id')
  elif name=='whitespace-loss':
   found=False
   for n in (n for v in verses for n in v.iter()):
    for attr in ('text','tail'):
     value=getattr(n,attr)
     if value and value.strip()!=value:setattr(n,attr,value.strip());found=True;break
    if found:break
   if not found:raise ValueError('No real source whitespace selected')
  elif name=='preserve-loss':first.attrib.pop(XML+'space')
  elif name=='foreign-alias-namespace':first.tag='{urn:invented}ab'
  elif name=='foreign-envelope':d.tag='{urn:invented}TEI'
  elif name in {'header-credit','header-rights','header-date'}:
   kind={'header-credit':'source-credits','header-rights':'source-rights','header-date':'source-date-qualification'}[name];next(n for n in d[0].iter() if n.get('type')==kind).text='Invented unqualified source claim'
  elif name=='envelope-payload':d.find(NS+'text').text='Invented outer content'
  changed=etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)
  if changed==raw:raise ValueError('Inert mutation '+name)
  try:check(m,changed)
  except (ValueError,etree.XMLSyntaxError,etree.DocumentInvalid) as error:
   reason=str(error)
   if not any(t in reason for t in ['Exact source-qualified header','Complete native node count','Exact reversible source alias']):raise ValueError('Unexpected mutation rejection '+name+': '+reason) from error
   cases.append(dict(name=name,status='rejected',reason=reason,mutated_sha256=sha256(changed).hexdigest()))
  else:raise ValueError('Accepted source/alias mutation '+name)
  (a.output/(name+'.tei.xml')).write_bytes(changed);print('Rejected '+name,flush=True)
 profile=json.loads(m.authority_path('reconstruction-profile').read_bytes());inventory=json.loads(m.authority_path('source-field-inventory').read_bytes())
 # Independent complete-context walker must reject a validly rebound changed
 # notice, not merely its original digest. Canonical annexes remain unchanged.
 for name in ['context-wording','context-omission','context-duplication','context-order','context-null-qualification','context-pointer']:
  bindings=deepcopy(profile['context_bindings']);part_index=0
  if name=='context-null-qualification':part_index=next(i for i,x in enumerate(bindings) if b'Absent source field:' in io_path(ROOT/x['notice_path']).read_bytes())
  value=io_path(ROOT/bindings[part_index]['notice_path']).read_bytes().decode();pieces=value.split('\n## Context event ');heading=pieces[0];blocks=pieces[1:]
  if name=='context-wording':blocks[0]=blocks[0].replace('"tag":"text"','"tag":"invented"',1)
  elif name=='context-omission':blocks.pop(0)
  elif name=='context-duplication':blocks.insert(1,blocks[0])
  elif name=='context-order':blocks[0],blocks[1]=blocks[1],blocks[0]
  elif name=='context-null-qualification':blocks=[b.replace('Absent source field: JSON null','Authored historical language title') for b in blocks]
  elif name=='context-pointer':blocks=[b.replace('source-json:original-douay-rheims-v1.0/','source-json:invented/',1) for b in blocks]
  changed=(heading+'\n## Context event '+'\n## Context event '.join(blocks)).encode();original=io_path(ROOT/bindings[part_index]['notice_path']).read_bytes()
  if changed==original:raise ValueError('Inert context mutation '+name)
  path=a.output/(name+'.md');path.write_bytes(changed);bindings[part_index]['notice_path']=path.as_posix();bindings[part_index]['notice_sha256']=sha256(changed).hexdigest()
  try:context_check(ROOT,bindings,raw,inventory)
  except ValueError as error:
   if not any(t in str(error) for t in ['Context fragment duplication/omission/order','Complete actual-TEI context']):raise
   cases.append(dict(name=name,status='rejected',reason=str(error),mutated_sha256=sha256(changed).hexdigest()))
  else:raise ValueError('Accepted complete context mutation '+name)
  print('Rejected '+name,flush=True)
 proof=dict(status='pass',baseline=baseline,cases=cases,candidate_sha256=c.sha256,replay_sha256=r.sha256,validation_equal=True,mutation_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
 (a.output/'result.json').write_bytes(canonical(proof));print(json.dumps(dict(status='pass',cases=len(cases))))
if __name__=='__main__':main()
