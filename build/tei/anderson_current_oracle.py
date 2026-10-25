"""Independent literal USFM relationships and reversible Anderson TEI checks."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote
import platform,re,sys
from lxml import etree

NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
PAIRS={'add':('supplied',{'reason':'source-marked'}),'it':('hi',{'rend':'italic'}),'sc':('hi',{'rend':'small-caps'}),'sig':('seg',{'type':'signature'}),'w':('term',{'type':'glossary-keyword'})}
PREFIX='source-usfm:anderson1864/'
ORACLE_ID='ocd-anderson-independent-source-native-current-v1'
ORACLE_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def closure_sha(root):
 paths=['build/tei/anderson_current_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/reconstruction/__init__.py','ocd_kernel/tei/validate.py']
 return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in sorted(paths)])).hexdigest()

def fingerprint(n):
 return n.tag,dict(n.attrib),n.text,n.tail,tuple(fingerprint(c) for c in n)

def split_line(line):
 if not line.startswith('\\'):raise ValueError('Source line lacks marker')
 stop=1
 while stop<len(line) and line[stop].isalnum():stop+=1
 if stop==1 or (stop<len(line) and not line[stop].isspace()):raise ValueError('Source line marker grammar')
 return line[1:stop],line[stop:].lstrip()

def expected_inline(payload):
 # This source scanner is independent of the historical TOKEN regexp/stack.
 # A mixed-content vector holds literal text before/between/after children.
 root={'tag':None,'attributes':{},'parts':['']};stack=[(None,root)];i=0;counts=Counter()
 while i<len(payload):
  if payload[i]!='\\':stack[-1][1]['parts'][-1]+=payload[i];i+=1;continue
  j=i+1
  while j<len(payload) and payload[j].isalnum():j+=1
  marker=payload[i+1:j];closing=j<len(payload) and payload[j]=='*'
  if marker not in PAIRS:raise ValueError('Unexpected source inline marker '+marker)
  if closing:
   if len(stack)==1 or stack[-1][0]!=marker:raise ValueError('Crossed or unmatched source inline close')
   item=stack.pop()[1]
   if marker=='w' and '|' in item['parts'][0]:
    if len(item['parts'])!=1:raise ValueError('Unsupported source nested keyed keyword')
    word,key=item['parts'][0].rsplit('|',1);item['parts'][0]=word;item['attributes']['key']=key
   i=j+1
  else:
   tag,attrs=PAIRS[marker];item={'tag':NS+tag,'attributes':dict(attrs),'parts':['']}
   stack[-1][1]['parts'] += [item,''];stack.append((marker,item));counts[marker]+=1;i=j
 if len(stack)!=1:raise ValueError('Unclosed source inline pair')
 return root,counts

def actual_parts(node,skip_first=False):
 children=list(node);parts=[node.text or '']
 if skip_first:
  if not children or children[0].tag!=NS+'note' or children[0].get('type')!='source-usfm-raw' or node.text not in (None,''):raise ValueError('Source raw note must be first, with no leading invention')
  parts=[children[0].tail or ''];children=children[1:]
 for c in children:parts.extend([{'tag':c.tag,'attributes':dict(c.attrib),'parts':actual_parts(c)},c.tail or ''])
 return parts

def source_relationships(member_set,read_member,raw):
 d=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 if d.tag!=NS+'TEI' or [c.tag for c in d]!=[NS+'teiHeader',NS+'text']:raise ValueError('Source TEI envelope namespace/order')
 body=d.find(NS+'text/'+NS+'body')
 if body is None or len(body)!=len(member_set['members']):raise ValueError('Complete ordered source member scope')
 parents={c:p for p in body.iter() for c in p};nodes={};counts=Counter();inline_counts=Counter();verse_rows=[];context=[];all_lines=[]
 for n in body.iter():
  pointer=n.get('corresp')
  if pointer:
   if pointer in nodes:raise ValueError('Duplicated source carrier pointer')
   nodes[pointer]=n
 seen=set();members=[]
 for ordinal,(binding,member) in enumerate(zip(member_set['members'],body,strict=True),1):
  if binding['position']!=ordinal:raise ValueError('Member source ordinal differs')
  content=read_member(binding['path'])
  if len(content)!=binding['bytes'] or sha256(content).hexdigest()!=binding['sha256']:raise ValueError('Literal extracted source binding differs')
  lines=content.decode('utf-8-sig').splitlines();name=Path(binding['path']).name;mid=None;chapter=None;member_pointer=None;chapter_pointer=None
  for number,line in enumerate(lines,1):
   marker,payload=split_line(line);pointer=PREFIX+quote(name,safe='')+'#line='+str(number);counts[marker]+=1;all_lines.append((name,number,line))
   if pointer not in nodes:raise ValueError('Omitted source carrier '+pointer)
   n=nodes[pointer];seen.add(pointer)
   if marker=='id':
    if number!=1 or mid is not None:raise ValueError('Source member ID location')
    mid=payload.split()[0];member_pointer=pointer;members.append(mid)
    expected={'type':'paratext' if mid in {'FRT','INT','GLO'} else 'book','n':mid,'corresp':pointer,XML+'id':'anderson-'+mid}
    if n is not member or n.tag!=NS+'div' or dict(n.attrib)!=expected or parents[n] is not body:raise ValueError('Member identity/role/order/ownership '+pointer)
   elif marker=='c':
    chapter=payload.split()[0];chapter_pointer=pointer
    if n.tag!=NS+'div' or dict(n.attrib)!={'type':'chapter','n':chapter,'corresp':pointer} or parents[n] is not member:raise ValueError('Source chapter identity/ownership '+pointer)
   else:
    expected_parent=nodes[chapter_pointer] if chapter_pointer is not None else member
    if n.tag!=NS+'ab' or parents[n] is not expected_parent:raise ValueError('Source line/verse attachment '+pointer)
    if marker=='v':
     if chapter is None:raise ValueError('Source verse precedes chapter')
     fields=payload.split(maxsplit=1);label=fields[0];visible=fields[1] if len(fields)>1 else ''
     expected={'type':'verse','n':label,'corresp':pointer}
    else:visible=payload;expected={'type':'usfm-'+marker,'n':marker,'corresp':pointer}
    if dict(n.attrib)!=expected:raise ValueError('Source carrier marker/label '+pointer)
    parsed,found=expected_inline(visible);inline_counts.update(found)
    if actual_parts(n,True)!=parsed['parts']:raise ValueError('Literal source mixed-content feature/wording/attachment '+pointer)
    if marker=='v':
     def flatten(parts):return ''.join(flatten(p['parts']) if isinstance(p,dict) else p for p in parts)
     verse_rows.append((mid,int(chapter),int(label) if label.isdecimal() else label,flatten(parsed['parts'])))
    else:context.append(dict(member=mid,chapter=chapter,line=number,marker=marker,pointer=pointer,source=line,parts=parsed['parts']))
   notes=[c for c in n if c.tag==NS+'note']
   if len(notes)!=1 or dict(notes[0].attrib)!={'type':'source-usfm-raw'} or notes[0].text!=line or len(notes[0]):raise ValueError('Exact unique raw source line '+pointer)
   if marker in {'id','c'} and (n.text not in (None,'') or notes[0].tail not in (None,'')):raise ValueError('Invented structural source payload')
  # Explicit source sequence for every scoped carrier, including chapter/member carriers.
  actual=[n.get('corresp') for n in member.iter() if n.get('corresp')]
  expected=[PREFIX+quote(name,safe='')+'#line='+str(i) for i in range(1,len(lines)+1)]
  if actual!=expected:raise ValueError('Complete source line ordering/duplication '+name)
 if set(nodes)!=seen or len(seen)!=10435 or len(verse_rows)!=7946 or len(members)!=30 or len([m for m in members if m not in {'FRT','INT','GLO'}])!=27:raise ValueError('Complete source carrier cardinality')
 if inline_counts!=Counter(add=98,it=10,sc=6,sig=1,w=23) or counts['c']!=260:raise ValueError('Complete source feature cardinality')
 # No unaccounted readable element or loose container text may coexist with the lines.
 owned=set()
 for n in nodes.values():
  owned.add(n)
  for c in n:
   if c.tag!=NS+'div' and not c.get('corresp'):owned.update(c.iter())
 if set(body.iter())-{body}-owned:raise ValueError('Unaccounted source body element')
 return dict(status='pass',members=members,source_lines=10435,verses=7946,chapters=260,inline_counts=dict(inline_counts),all_text_and_feature_attachments=True),verse_rows,context

def inverse(raw,original,expected_header):
 d=etree.fromstring(raw);old=etree.fromstring(original)
 if d.tag!=NS+'TEI' or dict(d.attrib)!={XML+'id':'anderson-1864-new-testament'} or [c.tag for c in d]!=[NS+'teiHeader',NS+'text'] or d.text!=old.text or d.tail!=old.tail:raise ValueError('Exact renewed namespace/envelope differs')
 h=etree.fromstring(expected_header)
 if fingerprint(d[0])!=fingerprint(h):raise ValueError('Exact source-qualified fresh header differs')
 if d[1].tag!=NS+'text' or dict(d[1].attrib)!=dict(old[1].attrib) or d[1].text!=old[1].text or d[1].tail!=old[1].tail:raise ValueError('Exact text envelope differs')
 old_features=[n for n in old[1].iter() if n.tag in {NS+'supplied',NS+'term'}]
 annotations=[n for n in d[1].iter() if n.tag==NS+'note' and n.get('type')=='source-feature-annotation']
 if len(annotations)!=121 or len(old_features)!=121:raise ValueError('Complete public source-feature annotation count differs')
 if any(len(n) for n in annotations):raise ValueError('Generated annotation has invented descendants')
 paired=dict(zip(list(old[1].iter()),[n for n in d[1].iter() if n not in set(annotations)],strict=True))
 def wording(n):return (n.text or '')+''.join(wording(c)+(c.tail or '') for c in n)
 for note,feature in zip(annotations,old_features,strict=True):
  supplied=feature.tag==NS+'supplied'
  label='Generated annotation: source-supplied span (not an authored footnote)' if supplied else 'Generated annotation: source glossary keyword (not an authored footnote)'
  text='Source USFM \\add marks this exact span as supplied: '+wording(feature) if supplied else 'Source USFM \\w glossary key: '+feature.get('key','(no key supplied)')
  if dict(note.attrib)!={'type':'source-feature-annotation','n':label} or note.text!=text or note.tail is not None or note.getparent() is not paired[feature] or note.getparent()[-1] is not note:raise ValueError('Exact explicitly generated public feature annotation/attachment differs')
  note.getparent().remove(note)
 new_nodes=list(d[1].iter());old_nodes=list(old[1].iter())
 if len(new_nodes)!=len(old_nodes):raise ValueError('Complete native node cardinality differs')
 for n,b in zip(new_nodes,old_nodes,strict=True):
  expected_tag=b.tag;expected=dict(b.attrib)
  if b.tag==NS+'ab':
   pointer=expected.pop('corresp');
   if b.get('type')!='verse':expected.pop('n')
   else:expected[XML+'space']='preserve'
  elif b.tag==NS+'note' and b.getparent().tag==NS+'ab':expected['n']='Generated source accounting (not an authored footnote): '+b.getparent().get('corresp')
  elif b.tag==NS+'supplied':expected_tag=NS+'hi';expected={'rend':'source-supplied:source-marked'}
  elif b.tag==NS+'term':expected_tag=NS+'seg';key=b.get('key');expected={'type':'source-glossary-keyword'+(':'+quote(key,safe='') if key is not None else '')}
  if n.tag!=expected_tag or dict(n.attrib)!=expected or n.text!=b.text or n.tail!=b.tail or len(n)!=len(b):raise ValueError('Reversible source alias/namespace/text/attachment differs')
  n.tag=b.tag;n.attrib.clear();n.attrib.update(b.attrib)
 d.replace(d[0],old[0]);d.attrib.clear();d.attrib.update(old.attrib)
 restored=etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)
 if restored!=original:raise ValueError('Whole historical TEI exact byte inverse differs')
 return restored

def context_check(manifest,profile,raw):
 # Independent lxml observation/Markdown parser; no annex producer import.
 from ocd_kernel.library._common import io_path
 from urllib.parse import unquote
 d=etree.fromstring(raw);expected=[]
 def wording(n):return (n.text or '')+''.join((wording(c) if c.tag!=NS+'note' else '')+(c.tail or '') for c in n)
 for n in d.find(NS+'text/'+NS+'body').iter():
  ledgers=[c for c in n if c.tag==NS+'note' and c.get('type')=='source-usfm-raw']
  if not ledgers or n.get('type')=='verse':continue
  if len(ledgers)!=1:raise ValueError('Context source ledger cardinality')
  note=ledgers[0];pointer=n.get('corresp') or (note.get('n') or '').removeprefix('Generated source accounting (not an authored footnote): ')
  member=next((p.get('n') for p in [n,*n.iterancestors()] if p.tag==NS+'div' and p.get('type') in {'book','paratext'}),None)
  chapter=next((p.get('n') for p in [n,*n.iterancestors()] if p.tag==NS+'div' and p.get('type')=='chapter'),None)
  features=[]
  for ordinal,c in enumerate(n.iter()):
   if c.tag in {NS+'hi',NS+'seg'}:features.append('Inline '+str(ordinal)+': '+c.tag.rsplit('}',1)[-1]+' '+', '.join(k+'='+v for k,v in c.attrib.items())+'; exact wording '+repr(wording(c)))
  expected.append((member,chapter,pointer,n.get('type'),note.text,wording(n) if n.tag==NS+'ab' else '','\n'.join(features)))
 observed=[];part_total=len(profile['context_bindings'])
 for part,item in enumerate(profile['context_bindings'],1):
  value=io_path(manifest.repository_root/item['notice_path']).read_bytes()
  if sha256(value).hexdigest()!=item['notice_sha256'] or len(value)>65536:raise ValueError('Maintained context part hash/limit')
  text=value.decode()
  if not text.startswith('# Anderson context annex '+str(part).zfill(3)+' of '+str(part_total).zfill(3)+'\n'):raise ValueError('Context part order/identity')
  for record in re.split(r'\n## Context ',text)[1:]:
   label,body=record.split('\n\n',1);number=int(label.split(' — ',1)[0])
   if number!=len(observed)+1:raise ValueError('Complete context order/duplication')
   match=re.fullmatch(r'(\d+) — ([^,]+), source line (\d+)(?:, chapter (\d+))?',label)
   if not match:raise ValueError('Context source grouping label')
   fields=re.fullmatch(r'Source member: \x60([^\x60]+)\x60; literal source locator: \x60([^\x60]+)\x60\. Carrier: ([^.]+)\.',body.split('\n\n',1)[0])
   if not fields:raise ValueError('Context full source locator/role')
   pointer=fields[2];pm=re.fullmatch(r'source-usfm:anderson1864/(.+)#line=(\d+)',pointer)
   if not pm or unquote(pm[1])!=fields[1] or pm[2]!=match[3]:raise ValueError('Context source locator mismatch')
   blocks=re.findall(r'\x60\x60\x60text\n(.*?)\n\x60\x60\x60',body,re.DOTALL)
   if len(blocks)!=2:raise ValueError('Exact raw/visible context distinction')
   feature_lines='\n'.join(line for line in body.splitlines() if line.startswith('Inline '))
   observed.append((match[2],match[4],pointer,fields[3],blocks[0],blocks[1],feature_lines))
 if observed!=expected or len(expected)!=2489:raise ValueError('All2489 source context wording/structure/feature/locator conservation')
 return dict(context_carriers=2489,context_parts=part_total,context_source_order_wording_and_features=True)

def check(manifest,raw):
 manifest.verify();profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes());original=manifest.authority_path('historical-native-baseline').read_bytes()
 members=json.loads(manifest.authority_path('member-set').read_bytes())
 from ocd_kernel.library._common import io_path
 facts,rows,context=source_relationships(members,lambda p:io_path(manifest.repository_root/p).read_bytes(),original)
 inverse(raw,original,profile['header_xml'].encode())
 from ocd_kernel.tei.validate import compiled_schema
 compiled_schema().assertValid(etree.ElementTree(etree.fromstring(raw)))
 facts.update(context_check(manifest,profile,raw),exact_historical_byte_inverse=True,literal_verse_characters=sum(len(r[3]) for r in rows),generated_annotations=121,verse_whitespace_preserve=7946,p5='pass')
 return facts

def _oracle(manifest,candidate):
 manifest.verify();profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
 check(manifest,candidate.member_bytes('content.tei.xml'))
 if candidate.member_bytes('source-accountability.json')!=manifest.authority_path('historical-accountability').read_bytes() or candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes():raise ValueError('Complete source ledger/credit differs')
 if [json.loads(b) for b in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:raise ValueError('Qualified questions differ')
 expected=dict(work_id=profile['work_id'],scope=profile['scope'],source_manifest_sha256=manifest.sha256,historical_native_sha256=sha256(manifest.authority_path('historical-native-baseline').read_bytes()).hexdigest(),scaffold_policy=profile['scaffold_policy'],status='nonaccepted')
 if json.loads(candidate.member_bytes('provenance.json'))!=expected:raise ValueError('Exact source/current scaffold provenance')
 from ocd_kernel.reconstruction.contract import _validation_authority_bindings
 bindings=_validation_authority_bindings(manifest)
 result=dict(status='pass',oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(manifest.repository_root),runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,findings=[],**bindings)
 result['result_sha256']=sha256(canonical(result)).hexdigest();return result

_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
