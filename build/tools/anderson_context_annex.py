"""Deterministically expose every Anderson nonverse carrier from actual TEI."""
from pathlib import Path
from urllib.parse import unquote
import re
from lxml import etree
NS='{http://www.tei-c.org/ns/1.0}'
ACCOUNT_LABEL='Generated source accounting (not an authored footnote): '

def records(raw):
 d=etree.fromstring(raw);result=[]
 for n in d.find(NS+'text/'+NS+'body').iter():
  note=next((c for c in n if c.tag==NS+'note' and c.get('type')=='source-usfm-raw'),None)
  if note is None or n.get('type')=='verse':continue
  pointer=n.get('corresp') or (note.get('n') or '').removeprefix(ACCOUNT_LABEL)
  match=re.fullmatch(r'source-usfm:anderson1864/(.+)#line=(\d+)',pointer)
  if not match:raise ValueError('Exact source locator absent')
  member=next((p.get('n') for p in [n,*n.iterancestors()] if p.tag==NS+'div' and p.get('type') in {'book','paratext'}),None)
  chapter=next((p.get('n') for p in [n,*n.iterancestors()] if p.tag==NS+'div' and p.get('type')=='chapter'),None)
  rawline=note.text
  if not isinstance(rawline,str) or not rawline.startswith('\\'):raise ValueError('Retained source context absent')
  def plain(e):return (e.text or '')+''.join((plain(c) if c.tag!=NS+'note' else '')+(c.tail or '') for c in e)
  visible=plain(n) if n.tag==NS+'ab' else ''
  features=[]
  for index,c in enumerate(n.iter()):
   if c.tag in {NS+'hi',NS+'seg'}:features.append(dict(ordinal=index,tag=c.tag.rsplit('}',1)[-1],attributes=dict(c.attrib),wording=plain(c)))
  result.append(dict(member=member,chapter=chapter,file=unquote(match[1]),line=int(match[2]),type=n.get('type'),pointer=pointer,raw=rawline,visible=visible,features=features))
 if len(result)!=2489:raise ValueError('All2489 nonverse source carriers required')
 return result

def block(r,index):
 feature_text='\n'.join('Inline '+str(f['ordinal'])+': '+f['tag']+' '+', '.join(k+'='+v for k,v in f['attributes'].items())+'; exact wording '+repr(f['wording']) for f in r['features'])
 return ('\n## Context '+str(index).zfill(4)+' — '+r['member']+', source line '+str(r['line'])+(', chapter '+r['chapter'] if r['chapter'] else '')+'\n\n'
         'Source member: `'+r['file']+'`; literal source locator: `'+r['pointer']+'`. Carrier: '+r['type']+'.\n\n'
         'Exact retained source record (USFM markers retain their source structure):\n\n```text\n'+r['raw']+'\n```\n\n'
         'Exact readable wording, including literal spaces (empty for structural member/chapter carriers):\n\n```text\n'+r['visible']+'\n```\n'+(('\n'+feature_text+'\n') if feature_text else ''))

def parts(raw):
 chunks=[];current=[];size=0
 for i,r in enumerate(records(raw),1):
  b=block(r,i);length=len(b.encode())
  if current and size+length>48000:chunks.append(''.join(current));current=[];size=0
  current.append(b);size+=length
 if current:chunks.append(''.join(current))
 output=[]
 for i,c in enumerate(chunks,1):
  text=('# Anderson context annex '+str(i).zfill(3)+' of '+str(len(chunks)).zfill(3)+'\n\n'
        'This deterministic companion is generated from the actual complete accepted TEI. It preserves source order across all 2,489 nonverse carriers: front matter, introduction, glossary, book headings, chapter labels and other context. These are context records, not additional Bible verses. Literal USFM records and readable wording are separate. Generated accounting and feature annotations are not authored footnotes. No source text is modernized or guessed.\n'+c).rstrip()+'\n'
  if len(text.encode())>65536:raise ValueError('Maintained notice part exceeds64KiB')
  output.append(text.encode())
 return output
