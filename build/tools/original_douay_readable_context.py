"""Readable complete actual-TEI context; private event ledger remains separate."""
import json
from hashlib import sha256
from urllib.parse import unquote
from lxml import etree
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'

def records(raw,inventory):
 pointers={'odr-source-field-'+sha256(r['pointer'].encode()).hexdigest():r['pointer'] for r in inventory}
 root=etree.fromstring(raw);text=root.find(NS+'text');out=[]
 def metadata(n):
  values={k:v for k,v in n.attrib.items() if k!=XML+'id'}
  alias=values.get('corresp','')
  if alias.startswith('source-attributes:'):values.pop('corresp');values.update(json.loads(unquote(alias.split(':',1)[1])))
  return values
 def grouping(n):
  result=[]
  for a in reversed(list(n.iterancestors())):
   if a.tag==NS+'div':result.append(metadata(a))
  return result
 def content(n):
  chunks=[];features=[];offset=0
  def walk(e):
   nonlocal offset
   start=offset
   if e.text is not None:chunks.append(e.text);offset+=len(e.text)
   for c in e:
    walk(c)
    if c.tail is not None:chunks.append(c.tail);offset+=len(c.tail)
   if e is not n:
    attributes=metadata(e)
    if e.get(XML+'id','').startswith('odr-source-unclosed-'):attributes['source-unclosed-markup']=True
    features.append(dict(start=start,end=offset,tag=etree.QName(e).localname,attributes=attributes))
  walk(n)
  return ''.join(chunks),features
 for n in text.iter():
  if any(a.tag==NS+'ab' and a.get('type')=='verse' for a in [n,*n.iterancestors()]):continue
  pointer=pointers.get(n.get(XML+'id'));empty=n.tag==NS+'div' and not len(n) and n.text is None
  if pointer is None and not empty and n.get('type')!='source-disposition':continue
  visible,styles=content(n);out.append(dict(pointer=pointer,groups=grouping(n),role=etree.QName(n).localname,attributes=metadata(n),wording=visible,tail=n.tail,inline=styles,empty_structure=empty))
 return out

def safe(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True).replace('<','\\u003c').replace('>','\\u003e')

def parts(raw,inventory):
 chunks=[];current=[];size=0;previous=None;document=None
 for index,r in enumerate(records(raw,inventory),1):
  prefix=''
  group=r['groups']
  if group!=previous:
   # Meaningful source-native path only at a natural unit transition, without
   # private node ordinals, empty-node events, generated digest IDs or URIs.
   prefix+='\n## Source section\n\n'+safe(group)+'\n'
   previous=group
  pointer=r['pointer']
  if pointer:
   member,local=pointer.split('source-json:original-douay-rheims-v1.0/',1)[1].split('#/',1)
   if member!=document:prefix+='\nSource document: '+member+'. Locator prefix: source-json:original-douay-rheims-v1.0/'+member+'#.\n';document=member
   location='/'+local
  else:location='Generated source disposition' if not r['empty_structure'] else 'Empty structured source field'
  values=r['attributes']
  values.pop(XML+'space',None)
  values.pop('n',None) if r['role']=='div' and r['empty_structure'] else None
  # The source-pointer alias is represented above, not repeated as a digest.
  wording=r['wording'];fragments=[wording[i:i+16000] for i in range(0,len(wording),16000)] or ['']
  for number,piece in enumerate(fragments,1):
   block=prefix if number==1 else ''
   block+='\n### Context '+str(index)+' fragment '+str(number)+' of '+str(len(fragments))+'\n\n'
   block+='Source field: '+location+'; role '+r['role']+' '+safe(values)+'.\n\n'
   if r['attributes'].get('type')=='source-null-absence:source-language-title':block+='Absent source title field (JSON null); the following null token is generated typed accounting, not an authored title.\n\n'
   block+='Exact literal wording (JSON string escapes preserve all spaces and comparison characters):\n\n```json\n'+safe(piece)+'\n```\n'
   if number==1:
    block+='\nInline styles/markers with character offsets into the joined literal wording: '+safe(r['inline'])+'.\n'
    block+='Exact following source tail: '+safe(r['tail'])+'. Empty structured field: '+str(r['empty_structure']).lower()+'.\n'
   length=len(block.encode())
   if current and size+length>48000:chunks.append(''.join(current));current=[];size=0
   current.append(block);size+=length
 if current:chunks.append(''.join(current))
 result=[]
 for number,body in enumerate(chunks,1):
  payload=('# Original Douay readable context '+str(number).zfill(4)+' of '+str(len(chunks)).zfill(4)+'\n\n'
           'Complete source-native nonverse context generated from the actual TEI: front matter, introductions, reference documents and tables, chapter summaries, articles, authored source notes and annotation relationships. Source sections preserve chapter, article and reference/table hierarchy; note labels and native targets remain explicit. The locator prefix plus local source field reconstructs the exact JSON pointer. Inline offsets record literal styles, source markers and line breaks without altering wording. JSON escapes and numbered fragments preserve all original whitespace. Null-title records mean source absence. The exhaustive private event ledger is evidence, not this reader companion; generated metadata is distinct from authored text.\n'+body)
  if len(payload.encode())>65536:raise ValueError('Readable context notice exceeds64KiB')
  result.append(payload.encode())
 return result
