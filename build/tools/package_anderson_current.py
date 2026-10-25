"""Exact Anderson replay and focused source/alias/annotation challenges."""
import argparse,json
from hashlib import sha256
from copy import deepcopy
from pathlib import Path
from lxml import etree
from build.tools.prepare_anderson_current import ROOT,BASE,canonical
from build.tei.anderson_current_oracle import check,NS,XML
from ocd_kernel.reconstruction.contract import SourceManifest,CandidatePackage
def main():
 p=argparse.ArgumentParser()
 for n in ('candidate','replay','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();c=CandidatePackage.load(a.candidate/'package');r=CandidatePackage.load(a.replay/'package')
 if c.sha256!=r.sha256 or any(c.member_bytes(n)!=r.member_bytes(n) for n in c.member_names) or (a.candidate/'validation.json').read_bytes()!=(a.replay/'validation.json').read_bytes():raise ValueError('Exact replay differs')
 m=SourceManifest.load(ROOT/BASE/'source-manifest.json',repository_root=ROOT);raw=c.member_bytes('content.tei.xml');baseline=check(m,raw)
 a.output.mkdir(parents=True,exist_ok=False);cases=[]
 names=['wording','verse-omit','verse-duplicate','verse-order','verse-label','verse-attachment','book-omit','book-order','chapter-label','member-identity','marker-invention','marker-type','source-pointer','accounting-label','source-supplied-rend','source-key','supplied-annotation-text','key-annotation-text','annotation-attachment','annotation-omit','annotation-duplicate','italic-style','signature','whitespace-loss','preserve-loss','foreign-alias-namespace','foreign-envelope','header-credit','header-rights','envelope-payload']
 for name in names:
  d=etree.fromstring(raw);body=d.find(NS+'text/'+NS+'body');verses=[n for n in body.iter() if n.tag==NS+'ab' and n.get('type')=='verse'];first=verses[0]
  nonverses=[n for n in body.iter() if n.tag==NS+'ab' and n.get('type')!='verse']
  supplied=next(n for n in body.iter() if n.tag==NS+'hi' and n.get('rend')=='source-supplied:source-marked')
  keyword=next(n for n in body.iter() if n.tag==NS+'seg' and n.get('type','').startswith('source-glossary-keyword'))
  annotations=[n for n in body.iter() if n.tag==NS+'note' and n.get('type')=='source-feature-annotation']
  if name=='wording':first[0].tail='Invented '+(first[0].tail or '')
  elif name=='verse-omit':first.getparent().remove(first)
  elif name=='verse-duplicate':first.addnext(deepcopy(first))
  elif name=='verse-order':second=verses[1];parent=first.getparent();i=parent.index(first);parent.remove(second);parent.insert(i,second)
  elif name=='verse-label':first.set('n','999')
  elif name=='verse-attachment':first.getparent().remove(first);verses[-1].getparent().append(first)
  elif name=='book-omit':body.remove(next(n for n in body if n.get('type')=='book'))
  elif name=='book-order':body.insert(0,body[-1])
  elif name=='chapter-label':next(n for n in body.iter() if n.get('type')=='chapter').set('n','999')
  elif name=='member-identity':body[0].set(XML+'id','anderson-INVENTED')
  elif name=='marker-invention':nonverses[-1].set('n','p')
  elif name=='marker-type':nonverses[-1].set('type','usfm-invented')
  elif name=='source-pointer':first[0].set('n',first[0].get('n').replace('#line=','#line=999'))
  elif name=='accounting-label':first[0].set('n',first[0].get('n').split(': ',1)[-1])
  elif name=='source-supplied-rend':supplied.set('rend','italic')
  elif name=='source-key':keyword.set('type','source-glossary-keyword:INVENTED')
  elif name=='supplied-annotation-text':supplied[-1].text='Invented source supplied fact'
  elif name=='key-annotation-text':keyword[-1].text='Invented glossary key'
  elif name=='annotation-attachment':note=annotations[0];note.getparent().remove(note);next(n for n in body.iter() if n.tag==NS+'hi' and n.get('rend')=='italic').append(note)
  elif name=='annotation-omit':annotations[0].getparent().remove(annotations[0])
  elif name=='annotation-duplicate':annotations[0].addnext(deepcopy(annotations[0]))
  elif name=='italic-style':next(n for n in body.iter() if n.tag==NS+'hi' and n.get('rend')=='italic').set('rend','small-caps')
  elif name=='signature':next(n for n in body.iter() if n.tag==NS+'seg' and n.get('type')=='signature').set('type','ordinary')
  elif name=='whitespace-loss':
   found=False
   for n in (n for v in verses for n in v.iter()):
    if n.tag==NS+'note':continue
    for attr in ('text','tail'):
     value=getattr(n,attr)
     if value and value.strip()!=value:setattr(n,attr,value.strip());found=True;break
    if found:break
   if not found:raise ValueError('No real source whitespace mutation selected')
  elif name=='preserve-loss':first.attrib.pop(XML+'space')
  elif name=='foreign-alias-namespace':supplied.tag='{urn:invented}hi'
  elif name=='foreign-envelope':d.tag='{urn:invented}TEI'
  elif name=='header-credit':next(n for n in d[0].iter() if n.get('type')=='english-dress-credit').text='Invented reviser allocation'
  elif name=='header-rights':next(n for n in d[0].iter() if n.get('type')=='permission-evidence').text='Universal publication permission established'
  elif name=='envelope-payload':d.find(NS+'text').text='Invented outer wording'
  changed=etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)
  if changed==raw:raise ValueError('Inert mutation '+name)
  try:check(m,changed)
  except (ValueError,etree.XMLSyntaxError,etree.DocumentInvalid) as error:cases.append(dict(name=name,status='rejected',reason=str(error),mutated_sha256=sha256(changed).hexdigest()))
  else:raise ValueError('Accepted source/scaffold mutation '+name)
  (a.output/(name+'.tei.xml')).write_bytes(changed);print('Rejected '+name,flush=True)
 proof=dict(status='pass',baseline=baseline,cases=cases,candidate_sha256=c.sha256,replay_sha256=r.sha256,validation_equal=True,mutation_implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest())
 (a.output/'result.json').write_bytes(canonical(proof));print(json.dumps(dict(status='pass',cases=len(cases))))
if __name__=='__main__':main()
