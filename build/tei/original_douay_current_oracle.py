"""Independent direct JSON fields, ownership and exact inverse for retained Douay."""
import json,re,platform,sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote,unquote
from lxml import etree
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
PREFIX='source-json:original-douay-rheims-v1.0/'
ORACLE_ID='ocd-original-douay-independent-source-current-v1';ORACLE_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def fingerprint(n):return n.tag,dict(n.attrib),n.text,n.tail,tuple(fingerprint(c) for c in n)
def closure_sha(root):
 names=['build/tei/original_douay_current_oracle.py','ocd_kernel/reconstruction/contract.py','ocd_kernel/reconstruction/verifier.py','ocd_kernel/reconstruction/__init__.py','ocd_kernel/tei/validate.py']
 return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest()) for p in sorted(names)])).hexdigest()
def markup(node):
 parts=[node.text or '']
 rules={(NS+'hi','italic'):'i',(NS+'hi','small-caps'):'sc',(NS+'hi','ref-title-sub'):'span',(NS+'seg','note-anchor'):'na',(NS+'seg','marginal-note-marker'):'mn',(NS+'seg','alternate-reading'):'alt',(NS+'seg','column-left'):'col-left',(NS+'seg','column-right'):'col-right',(NS+'ref','cross-reference-marker'):'cr'}
 for c in node:
  if c.tag==NS+'lb':
   if dict(c.attrib)!={'type':'source-br'} or len(c) or c.text is not None:raise ValueError('Source inline line-break attributes/children')
   parts.append('<br>')
  else:
   attr='rend' if c.tag==NS+'hi' else 'type';label=c.get(attr);key=rules.get((c.tag,label))
   if key is None or set(c.attrib)-{attr,'ana'} or c.get('ana') not in (None,'#source-unclosed-markup'):raise ValueError('Exact source inline name/style/attributes')
   opening='<span class="ref-title-sub">' if key=='span' else '<'+key+'>'
   parts.extend([opening,markup(c)])
   if c.get('ana') is None:parts.append('</span>' if key=='span' else '</'+key+'>')
  parts.append(c.tail or '')
 return ''.join(parts)
def scalar(v):return v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)
def source_check(member_set,read_member,raw):
 d=etree.fromstring(raw);text=d.find(NS+'text');group=text.find(NS+'group')
 if d.tag!=NS+'TEI' or [c.tag for c in d]!=[NS+'teiHeader',NS+'text'] or group is None or [dict(c.attrib) for c in group]!=[{'type':'testament','n':'OT'},{'type':'testament','n':'NT'}]:raise ValueError('Complete native testament envelope')
 docs={};bindings={}
 for i,m in enumerate(member_set['members'],1):
  if m['position']!=i:raise ValueError('Exact retained member order')
  b=read_member(m['path'])
  if len(b)!=m['bytes'] or sha256(b).hexdigest()!=m['sha256']:raise ValueError('Actual retained source binding '+m['path'])
  rel=m['path'].split('/original-douay-rheims-1.0/',1)[1];bindings[rel]=m
  if rel.startswith(('bible/tagged/','annotations/','reference/')):docs[rel]=json.loads(b)
 if len(member_set['members'])!=651 or len(docs)!=497:raise ValueError('Full source textual envelope census')
 if read_member(bindings['bible/tagged/prayer-of-manasseh.json']['path'])!=read_member(bindings['bible/tagged/prayer-of-manasses.json']['path']):raise ValueError('Exact retained Prayer duplicate differs')
 nodes={};field_records=[];by_document={};by_chapter={};null_fields=[]
 for ordinal,n in enumerate(text.iter()):
  ptr=n.get('corresp','')
  if not ptr.startswith(PREFIX):continue
  if ptr in nodes:raise ValueError('Duplicated source scalar pointer '+ptr)
  relative,pointer=ptr[len(PREFIX):].split('#/',1);keys=[k.replace('~1','/').replace('~0','~') for k in pointer.split('/')];v=docs[relative]
  for k in keys:v=v[int(k)] if isinstance(v,list) else v[k]
  if isinstance(v,(list,dict)):raise ValueError('Compound source field rendered as scalar')
  if markup(n)!=scalar(v):
   if v is None and keys==['hebrew_title'] and n.tag==NS+'ab' and n.get('type')=='source-language-title' and n.text=='None' and not len(n):null_fields.append(ptr)
   else:raise ValueError('Literal source scalar/inline wording '+ptr)
  nodes[ptr]=n;by_document.setdefault(relative,[]).append(n)
  if keys and keys[0]=='chapters':by_chapter.setdefault((relative,keys[1]),[]).append(n)
  field_records.append(dict(pointer=ptr,ordinal=ordinal,tag=n.tag,attributes=dict(n.attrib),raw=scalar(v),visible=''.join(n.itertext()),ancestors=[dict(tag=a.tag,attributes=dict(a.attrib)) for a in reversed(list(n.iterancestors())) if a is not d]))
 def ptr(rel,keys):return PREFIX+rel+'#/'+('/'.join(str(x).replace('~','~0').replace('/','~1') for x in keys))
 dispositions=[];expected=set()
 def walk(rel,value,keys=()):
  if isinstance(value,dict):
   for k,v in value.items():walk(rel,v,keys+(k,))
  elif isinstance(value,list):
   for i,v in enumerate(value):walk(rel,v,keys+(i,))
  else:
   p=ptr(rel,keys)
   if p in nodes:expected.add(p);return
   role=None
   if rel=='bible/tagged/prayer-of-manasseh.json':role='whole exact duplicate accounted, not rendered twice'
   elif rel.startswith('bible/tagged/') and keys[-1] in {'chapter','verse','has_annotation','default','label','marker'}:role='native structural numeric/boolean/note-label attribute'
   elif rel.startswith('annotations/') and keys[-1] in {'chapter','verse','marker','label'}:role='native annotation chapter/target/note-label attribute'
   if role is None:raise ValueError('Unaccounted scalar source field '+p)
   dispositions.append(dict(pointer=p,value=value,role=role))
 for relative,doc in docs.items():walk(relative,doc)
 if set(nodes)!=expected or len(nodes)!=62326:raise ValueError('Complete independent source field coverage')
 books=[n for n in text.iter() if n.tag==NS+'div' and n.get('type') in {'book','appendix-book'}]
 if len(books)!=76:raise ValueError('Complete76 unique textual components')
 counts=Counter();verse_fields=[];zero=[];addresses=[]
 for book in books:
  rel=book.get('source');doc=docs[rel]
  if book.get('n')!=rel.rsplit('/',1)[1].removesuffix('.json') or book.get(XML+'id')!='odr-book-'+book.get('n'):raise ValueError('Native book identity/ownership')
  chapters=[n for n in book if n.tag==NS+'div' and n.get('type')=='chapter']
  if len(chapters)!=len(doc['chapters']):raise ValueError('Native source chapter count')
  for index,(c,chapter) in enumerate(zip(chapters,doc['chapters'],strict=True)):
   label=str(chapter['chapter']);counts['chapters']+=1
   if c.get('n')!=label or c.get('source')!=rel+'#/chapters/'+str(index) or c.get(XML+'id')!='odr-'+book.get('n')+'-'+label:raise ValueError('Native source chapter identity/attachment')
   groups=[n for n in c if n.tag==NS+'div' and n.get('type')=='verse']
   if len(groups)!=len(chapter['verses']):raise ValueError('Source verse occurrence count')
   occurrences=Counter()
   for vindex,(group,verse) in enumerate(zip(groups,chapter['verses'],strict=True)):
    vlabel=str(verse['verse']);occurrences[vlabel]+=1;counts['verses']+=1;address=(book.get('n'),label,vlabel);addresses.append(address)
    carrier=nodes[ptr(rel,('chapters',index,'verses',vindex,'text'))]
    want='odr-'+book.get('n')+'-'+label+'-'+vlabel+('-occurrence-'+str(occurrences[vlabel]) if occurrences[vlabel]>1 else '')
    if group.get('n')!=vlabel or group.get(XML+'id')!=want or carrier.getparent() is not group or carrier.tag!=NS+'ab' or carrier.get('type')!='verse-text':raise ValueError('Source verse occurrence/wording/ownership')
    if verse.get('has_annotation') is True and group.get('ana')!='#has-annotation':raise ValueError('Source annotation boolean lost')
    verse_fields.append(carrier.get('corresp'))
    if vlabel=='0':zero.append(dict(book=book.get('n'),chapter=label,verse=vlabel,pointer=carrier.get('corresp'),wording=scalar(verse['text'])))
    for field,kind in [('notes','inline-note'),('cross_refs','cross-reference')]:
     found=[n for n in group if n.tag==NS+'note' and n.get('type')==kind];items=verse.get(field,[])
     if len(found)!=len(items):raise ValueError('Complete source verse note count')
     for ni,(note,item) in enumerate(zip(found,items,strict=True)):
      if note is not nodes[ptr(rel,('chapters',index,'verses',vindex,field,ni,'text'))] or note.get('n')!=(str(item['label']) if 'label' in item else None):raise ValueError('Source note label/attachment/order')
      counts[kind]+=1
   anns=[n for n in c if n.tag==NS+'div' and n.get('type')=='chapter-annotations']
   for container in anns:
    ap=container.get('source');ad=docs[ap]
    if str(ad['chapter'])!=label or not ap.startswith('annotations/'+book.get('n')+'/'):raise ValueError('Source annotation chapter ownership')
    if len(container)!=len(ad['annotations']):raise ValueError('Source annotation count')
    for ai,(ann,value) in enumerate(zip(container,ad['annotations'],strict=True)):
     if ann.get('n')!=str(value['verse']) or ann.get('corresp')!='#odr-'+book.get('n')+'-'+label+'-'+str(value['verse']):raise ValueError('Source annotation native target/order')
     for key in ('title','text','part'):
      if key in value and nodes[ptr(ap,('annotations',ai,key))].getparent() is not ann:raise ValueError('Source annotation field attachment')
     sub=[n for n in ann if n.tag==NS+'note']
     if len(sub)!=len(value.get('notes',[])):raise ValueError('Source annotation subnote count')
     for ni,(note,v) in enumerate(zip(sub,value.get('notes',[]),strict=True)):
      key='marker' if 'marker' in v else 'label'
      if note.get('n')!=str(v[key]) or note is not nodes[ptr(ap,('annotations',ai,'notes',ni,'text'))]:raise ValueError('Source annotation subnote label/attachment')
      counts['annotation-subnotes']+=1
     counts['annotations']+=1
   if any(c not in n.iterancestors() for n in by_chapter.get((rel,str(index)),[])):raise ValueError('Source chapter contextual field ownership')
   articles=[n for n in c if n.tag==NS+'div' and n.get('type')=='chapter-article']
   source_articles=chapter.get('articles',[])
   if len(articles)!=len(source_articles):raise ValueError('Complete source chapter article count')
   if articles:
    if list(chapter)[-1]!='articles':raise ValueError('Unreviewed source chapter article placement')
    others=list(c);positions=[others.index(n) for n in articles]
    if any(others.index(n)>positions[0] for n in c if n.get('type')=='verse') or any(others.index(n)<positions[-1] for n in c if n.get('type')=='chapter-annotations'):raise ValueError('Source article order relative to verse fields/external annotations')
   for ai,(article,value) in enumerate(zip(articles,source_articles,strict=True)):
    attrs={'type':'chapter-article','n':str(ai+1)}
    if value.get('default') is True:attrs['ana']='#default-introduction'
    if dict(article.attrib)!=attrs or article.text is not None or article.tail is not None:raise ValueError('Exact source article envelope/attributes')
    children=[]
    for key,tag,kind in [('title','head',None),('text','ab','chapter-article-text'),('part','ab','annotation-part')]:
     if key in value:
      node=nodes[ptr(rel,('chapters',index,'articles',ai,key))];children.append(node)
      wanted={'corresp':node.get('corresp')}
      if kind:wanted['type']=kind
      if node.tag!=NS+tag or dict(node.attrib)!=wanted:raise ValueError('Exact source article field roles')
    for ni,item in enumerate(value.get('notes',[])):
     node=nodes[ptr(rel,('chapters',index,'articles',ai,'notes',ni,'text'))];children.append(node)
     marker='label' if 'label' in item else 'marker'
     if node.tag!=NS+'note' or dict(node.attrib)!={'corresp':node.get('corresp'),'type':'chapter-article-note','n':str(item[marker])}:raise ValueError('Exact source article subnote labels/roles')
     counts['chapter-article-subnotes']+=1
    if list(article)!=children or any(n.tail is not None for n in children):raise ValueError('Source article field/subnote attachment/order')
    counts['chapter-articles']+=1
 # Every pointer remains under its own book or reference document and source array order.
 for book in books:
  rel=book.get('source')
  if any(book not in n.iterancestors() for n in by_document[rel]):raise ValueError('Cross-book scalar field contamination')
 refs=[n for n in text.iter() if n.tag==NS+'div' and n.get('type')=='reference-document']
 if len(refs)!=26 or {n.get('source') for n in refs}!={p for p in docs if p.startswith('reference/')}:raise ValueError('Complete reference document disposition')
 for document in refs:
  prefix=PREFIX+document.get('source')+'#/'
  if any(document not in n.iterancestors() for n in by_document[document.get('source')]):raise ValueError('Source reference scalar field attachment')
 if counts['chapters']!=1361 or counts['verses']!=37181 or counts['annotations']!=1659 or counts['annotation-subnotes']!=3544 or counts['chapter-articles']!=9 or counts['chapter-article-subnotes']!=440 or len(zero)!=49 or sum(1 for v in Counter(addresses).values() if v>1)!=1:raise ValueError('Complete source structural census')
 return dict(status='pass',counts=dict(counts),scalar_fields=len(nodes),metadata_scalar_dispositions=dispositions,zero_label_carriers=zero,duplicate_native_addresses=[list(k) for k,v in Counter(addresses).items() if v>1],historical_null_encoding_errors=null_fields),field_records,verse_fields

def inverse(raw,old,header,null_pointers=(),native_with_articles=None):
 d=etree.fromstring(raw);b=etree.fromstring(native_with_articles or old);h=etree.fromstring(header)
 if d.tag!=NS+'TEI' or dict(d.attrib)!={XML+'id':'original-douay-rheims'} or [n.tag for n in d]!=[NS+'teiHeader',NS+'text'] or d.text!=b.text or d.tail!=b.tail or fingerprint(d[0])!=fingerprint(h):raise ValueError('Exact source-qualified header/namespace/envelope')
 new=list(d[1].iter());original=list(b[1].iter())
 if len(new)!=len(original):raise ValueError('Complete native node count')
 for ordinal,(n,o) in enumerate(zip(new,original,strict=True)):
  tag=o.tag;attrs=dict(o.attrib);local=etree.QName(o).localname
  if local=='group':tag=NS+'body'
  elif local=='text' and o is not b[1]:tag=NS+'div';attrs['type']='source-testament'
  elif local in {'front','body'}:tag=NS+'div';attrs={'type':'source-part-'+local}
  elif local=='div':
   extra={k:attrs.pop(k) for k in ('source','subtype','ana') if k in attrs}
   if attrs.get('type')=='verse':attrs['type']='source-verse-group'
   elif attrs.get('type')=='appendix-book':extra['original-type']='appendix-book';attrs['type']='book'
   if extra:
    if 'corresp' in attrs:raise ValueError('Source alias cannot overwrite target')
    attrs['corresp']='source-attributes:'+quote(json.dumps(extra,sort_keys=True,separators=(',',':')),safe='')
  elif local in {'head','ab','note'}:
   p=attrs.pop('corresp',None)
   if p:attrs[XML+'id']='odr-source-field-'+sha256(p.encode()).hexdigest()
   if local=='ab' and o.get('type')=='verse-text':attrs.update(type='verse',n=o.getparent().get('n'));attrs[XML+'space']='preserve'
  elif local=='ref':tag=NS+'seg'
  elif local=='lb':attrs={'break':'yes'}
  elif local=='hi' and attrs.get('ana')=='#source-unclosed-markup':attrs.pop('ana');attrs[XML+'id']='odr-source-unclosed-'+str(ordinal)
  expected_text=o.text
  if o.get('corresp') in null_pointers:
   if o.tag!=NS+'ab' or o.get('type')!='source-language-title' or o.text!='None' or len(o):raise ValueError('Exact source typed-null repair form')
   attrs['type']='source-null-absence:source-language-title';expected_text='null'
  if n.tag!=tag or dict(n.attrib)!=attrs or n.text!=expected_text or n.tail!=o.tail or len(n)!=len(o):raise ValueError('Exact reversible source alias/text/tail/namespace/order/ownership at '+str(ordinal))
  n.tag=o.tag;n.attrib.clear();n.attrib.update(o.attrib);n.text=o.text
 d.replace(d[0],b[0]);d.attrib.clear();d.attrib.update(b.attrib)
 lexical=native_with_articles or old
 starts=list(re.finditer(rb'<(?![/?])([A-Za-z]+)\b[^<>]*>',lexical));elements=list(d.iter())
 if len(starts)!=len(elements):raise ValueError('Exact native lexical element inventory')
 for start,node in zip(starts,elements,strict=True):
  name=start.group(1)
  if etree.QName(node).localname.encode()!=name:raise ValueError('Native lexical element order')
  if not start.group().endswith(b'/>') and node.text is None and not len(node) and lexical[start.end():start.end()+len(name)+3]==b'</'+name+b'>':node.text=''
 restored=etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)
 if native_with_articles is not None:
  if restored!=native_with_articles:raise ValueError('Whole source-checked renewed native exact byte inverse')
  articles=[n for n in d[1].iter(NS+'div') if n.get('type')=='chapter-article']
  if len(articles)!=9:raise ValueError('Exact nine source articles for historical inverse')
  for article in articles:
   if article.tail is not None:raise ValueError('Article removal cannot erase outer source text')
   article.getparent().remove(article)
  restored=etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)
 if restored!=old:raise ValueError('Whole original native exact byte inverse')
 return restored

def context_check(repository_root,bindings,raw,field_inventory):
 """Independent ET event walk and fragment reader, without context producer calls."""
 from xml.etree import ElementTree as ET
 from ocd_kernel.library._common import io_path
 root=ET.fromstring(raw);text=root.find(NS+'text');nodes=list(text.iter());positions={n:i for i,n in enumerate(nodes)}
 parents={c:n for n in nodes for c in n};sources={}
 for field in field_inventory:
  native='odr-source-field-'+sha256(field['pointer'].encode()).hexdigest()
  if native in sources:raise ValueError('Duplicate source pointer identity')
  sources[native]=field['pointer']
 expected=[]
 for ordinal,node in enumerate(nodes):
  parent=parents.get(node);chain=[];walk=node
  while walk is not None:chain.append(walk);walk=parents.get(walk)
  carrier=next((e for e in chain if e.tag==NS+'ab' and e.get('type')=='verse'),None)
  if carrier is not None and carrier is not node:continue
  attributes=dict(node.attrib);source=sources.get(node.get(XML+'id'))
  if source:del attributes[XML+'id'];attributes['source-field-pointer']=source
  reference=attributes.get('corresp','')
  if reference.startswith('source-attributes:'):
   del attributes['corresp'];attributes['source-original-attributes']=json.loads(unquote(reference.split(':',1)[1]))
  event=dict(ordinal=ordinal,parent=positions.get(parent),kind='verse-output-placeholder' if carrier is node else 'context-node',tag=node.tag.removeprefix(NS),attributes=attributes,text=node.text,tail=node.tail)
  if carrier is node:event.pop('text');event['disposition']='Full literal verse wording/inline structure is in the Bible row at this source address; original native occurrence ID is retained.'
  if node.get('type')=='source-null-absence:source-language-title':event['qualification']='Absent source field: JSON null, not an authored language title. The lexical null token is generated typed accounting.'
  expected.append(event)
 observed=[];pending=[];event_number=1;fragment_number=1;total=None
 for number,binding in enumerate(bindings,1):
  value=io_path(repository_root/binding['notice_path']).read_bytes()
  if sha256(value).hexdigest()!=binding['notice_sha256'] or not 0<len(value)<=65536:raise ValueError('Context part exact binding/limit')
  content=value.decode()
  if not content.startswith('# Original Douay context annex '+str(number).zfill(4)+' of '+str(len(bindings)).zfill(4)+'\n'):raise ValueError('Context part identity/order')
  for block in re.split(r'\n## Context event ',content)[1:]:
   match=re.fullmatch(r'(\d+) fragment (\d+) of (\d+)\n\n\x60\x60\x60json-fragment\n(.*?)\n\x60\x60\x60\n',block,re.DOTALL)
   if not match:raise ValueError('Exact context record fragment shape')
   ev,fr,count=map(int,match.group(1,2,3))
   if ev!=event_number or fr!=fragment_number or count<1 or (total is not None and total!=count):raise ValueError('Context fragment duplication/omission/order')
   total=count;pending.append(match[4])
   if fr==count:observed.append(json.loads(''.join(pending)));pending=[];total=None;event_number+=1;fragment_number=1
   else:fragment_number+=1
 if pending or observed!=expected:raise ValueError('Complete actual-TEI context node/text/tail/structure/pointer/null/verse-placeholder conservation')
 return dict(context_events=len(expected),context_parts=len(bindings),actual_tei_context_complete=True)

def check(manifest,raw):
 manifest.verify();profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
 members=json.loads(manifest.authority_path('member-set').read_bytes())
 old=manifest.authority_path('historical-native-baseline').read_bytes();native=manifest.authority_path('source-complete-native').read_bytes()
 # Aliases are challenged before the expensive full source walk. The complete
 # renewed native baseline is independently compared with every actual member.
 inverse(raw,old,profile['header_xml'].encode(),profile['null_source_pointers'],native)
 from ocd_kernel.library._common import io_path
 facts,inventory,verses=source_check(members,lambda p:io_path(manifest.repository_root/p).read_bytes(),native)
 if facts['historical_null_encoding_errors']!=profile['null_source_pointers'] or inventory!=json.loads(manifest.authority_path('source-field-inventory').read_bytes()):raise ValueError('Exact independently source-derived scalar/pointer profile')
 from ocd_kernel.tei.validate import compiled_schema
 compiled_schema().assertValid(etree.ElementTree(etree.fromstring(raw)))
 facts.update(context_check(manifest.repository_root,profile['context_bindings'],raw,inventory),exact_historical_byte_inverse=True,typed_null_absences=73,added_source_chapter_articles=9,p5='pass')
 return facts

def _oracle(manifest,candidate):
 manifest.verify();profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes());check(manifest,candidate.member_bytes('content.tei.xml'))
 for name,authority in [('source-accountability.json','current-accountability'),('README.source.md','source-readme')]:
  if candidate.member_bytes(name)!=manifest.authority_path(authority).read_bytes():raise ValueError('Exact current accounting/credit differs')
 if [json.loads(b) for b in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:raise ValueError('Qualified questions differ')
 expected=dict(work_id=profile['work_id'],source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted',existing_native_body_reused=True,repairs=dict(typed_null_absences=73,source_chapter_articles=9),scaffold_policy=profile['scaffold_policy'])
 if json.loads(candidate.member_bytes('provenance.json'))!=expected:raise ValueError('Exact current source/repair/scaffold provenance')
 from ocd_kernel.reconstruction.contract import _validation_authority_bindings
 result=dict(status='pass',oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(manifest.repository_root),runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,findings=[],**_validation_authority_bindings(manifest))
 result['result_sha256']=sha256(canonical(result)).hexdigest();return result
_oracle.oracle_id=ORACLE_ID;_oracle.oracle_version=ORACLE_VERSION;_oracle.implementation_path=Path(__file__).resolve()
