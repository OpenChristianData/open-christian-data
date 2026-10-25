"""Exact fresh replay and meaningful whole-source BCP1559 challenges."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction.contract import CandidatePackage
from build.tei.bcp1559_current_oracle import check_profile
from build.tools.prepare_bcp1559_current import ROOT,BASE,canonical

NS='{http://www.tei-c.org/ns/1.0}'


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ('candidate','replay','output'):p.add_argument('--'+key,type=Path,required=True)
 a=p.parse_args(); first=CandidatePackage.load(a.candidate/'package'); second=CandidatePackage.load(a.replay/'package')
 if first.sha256!=second.sha256 or any(first.member_bytes(n)!=second.member_bytes(n) for n in first.member_names) or (a.candidate/'validation.json').read_bytes()!=(a.replay/'validation.json').read_bytes():
  raise ValueError('Fresh full-package replay or independent validation differs')
 profile=json.loads((ROOT/BASE/'profile.json').read_bytes());raw=first.member_bytes('content.tei.xml');ledger=json.loads(first.member_bytes('source-accountability.json'))
 facts=check_profile(profile,raw,ledger);a.output.mkdir(parents=True,exist_ok=False);cases=[]
 names=['wording','source-space','member-omission','member-order','member-duplication','literal-title','table-omission','row-omission','row-order','cell-omission','cell-order','colspan-loss','colspan-change','rowspan-loss','rowspan-change','inline-attachment','italic-style','bold-style','original-font','source-color','source-anchor','link-target','image-url','image-alt','line-break','dagger-decoding','bullet-decoding','header-credit','ledger-omission','ledger-order','ledger-source-path','ledger-source-attribute','entity-lexeme','entity-location','outside-source-whitespace']
 for name in names:
  doc=etree.fromstring(raw);body=doc.find(NS+'text/'+NS+'body');accounting=deepcopy(ledger)
  textnode=next(n for n in body.iter() if n.text and n.text.strip() and n.tag!=NS+'head')
  if name=='wording':textnode.text='Invented wording'
  elif name=='source-space':
   node=next(n for n in body.iter() if n.text and '\u00a0' in n.text);node.text=node.text.replace('\u00a0',' ',1)
  elif name=='member-omission':body.remove(body[11])
  elif name=='member-order':body.insert(0,body[-1])
  elif name=='member-duplication':body.append(deepcopy(body[0]))
  elif name=='literal-title':body[0][0].text='Invented source title'
  elif name=='table-omission':node=next(body[11].iter(NS+'table'));node.getparent().remove(node)
  elif name in ('row-omission','row-order'):
   table=next(n for n in body[11].iter(NS+'table') if len(n)>2)
   if name=='row-omission':table.remove(table[1])
   else:table.insert(0,table[-1])
  elif name in ('cell-omission','cell-order'):
   row=next(n for n in body[11].iter(NS+'row') if len(n)>2)
   if name=='cell-omission':row.remove(row[1])
   else:row.insert(0,row[-1])
  elif name.startswith('colspan'):
   node=next(n for n in body.iter(NS+'cell') if n.get('cols'))
   if name.endswith('loss'):node.attrib.pop('cols')
   else:node.set('cols','999')
  elif name.startswith('rowspan'):
   node=next(n for n in body.iter(NS+'cell') if n.get('rows'))
   if name.endswith('loss'):node.attrib.pop('rows')
   else:node.set('rows','999')
  elif name=='inline-attachment':
   node=next(body.iter(NS+'hi'));next(n for n in body.iter(NS+'ab') if n is not node.getparent()).append(node)
  elif name in ('italic-style','bold-style'):
   style=name.split('-')[0];next(n for n in body.iter(NS+'hi') if n.get('rend')==style).set('rend','invented')
  elif name in ('original-font','source-color','source-anchor'):
   needle={'original-font':'%22face%22','source-color':'%22color%22','source-anchor':'%22name%22'}[name]
   node=next(n for n in body.iter() if needle in (n.get('ana') or ''));node.set('ana',node.get('ana').replace(needle,'%22invented%22',1))
  elif name=='link-target':next(body.iter(NS+'ref')).set('target','https://example.invalid/invented')
  elif name=='image-url':next(body.iter(NS+'graphic')).set('url','images/invented.gif')
  elif name=='image-alt':next(n for n in body.iter(NS+'graphic') if n.get('n') is not None).set('n','Invented alt text')
  elif name=='line-break':node=next(body.iter(NS+'lb'));node.getparent().remove(node)
  elif name in ('dagger-decoding','bullet-decoding'):
   correct='\u2020' if name.startswith('dagger') else '\u2022';wrong=chr(134) if name.startswith('dagger') else chr(149)
   node=next(n for n in body.iter() if n.text and correct in n.text);node.text=node.text.replace(correct,wrong,1)
  elif name=='header-credit':next(n for n in doc[0].iter(NS+'note') if n.get('type')=='source-credit').text='Invented transcriber attribution'
  elif name=='ledger-omission':accounting['nodes'].pop()
  elif name=='ledger-order':accounting['nodes'][1],accounting['nodes'][2]=accounting['nodes'][2],accounting['nodes'][1]
  elif name=='ledger-source-path':accounting['nodes'][100]['source_path']='/invented-parent'
  elif name=='ledger-source-attribute':accounting['nodes'][100]['source_attributes'].append(['invented','yes'])
  elif name=='entity-lexeme':accounting['members'][0]['numeric_character_references'][0]['lexeme']='&#8226;'
  elif name=='entity-location':accounting['members'][0]['numeric_character_references'][0]['byte_start']+=1
  elif name=='outside-source-whitespace':accounting['members'][0]['post_html_whitespace']=''
  altered=etree.tostring(doc,encoding='UTF-8',xml_declaration=True)
  if altered==raw and accounting==ledger:raise ValueError('Inert mutation '+name)
  (a.output/(name+'.tei.xml')).write_bytes(altered)
  if accounting!=ledger:(a.output/(name+'.accountability.json')).write_bytes(canonical(accounting))
  try:check_profile(profile,altered,accounting)
  except (ValueError,etree.DocumentInvalid,etree.XMLSyntaxError) as exc:
   cases.append(dict(name=name,status='rejected',reason=str(exc),mutated_sha256=sha256(altered).hexdigest(),accountability_sha256=sha256(canonical(accounting)).hexdigest()))
   print('Rejected '+name+': '+str(exc),flush=True)
  else:raise ValueError('Accepted source mutation '+name)
  (a.output/'partial-result.json').write_bytes(canonical(dict(candidate_sha256=first.sha256,replay_sha256=second.sha256,cases=cases)))
 result=dict(status='pass',candidate_sha256=first.sha256,replay_sha256=second.sha256,baseline=facts,cases=cases,mutations=len(cases),validation_equal=True)
 (a.output/'result.json').write_bytes(canonical(result));print(json.dumps(dict(status='pass',mutations=len(cases),candidate_sha256=first.sha256)))


if __name__=='__main__':main()
