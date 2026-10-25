"""Actual-TEI context events; public locators expose source pointers, never private digests."""
import json
from hashlib import sha256
from urllib.parse import unquote
from lxml import etree
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'

def records(raw,field_inventory):
 pointers={'odr-source-field-'+sha256(r['pointer'].encode()).hexdigest():r['pointer'] for r in field_inventory}
 d=etree.fromstring(raw);text=d.find(NS+'text');all_nodes=list(text.iter());ordinals={n:i for i,n in enumerate(all_nodes)}
 output=[]
 for ordinal,n in enumerate(all_nodes):
  verse=next((a for a in [n,*n.iterancestors()] if a.tag==NS+'ab' and a.get('type')=='verse'),None)
  if verse is not None and verse is not n:continue
  attrs=dict(n.attrib);pointer=pointers.get(attrs.get(XML+'id'))
  if pointer:attrs.pop(XML+'id');attrs['source-field-pointer']=pointer
  # The reversible opaque attribute alias is decoded for public understanding.
  if attrs.get('corresp','').startswith('source-attributes:'):
   original=json.loads(unquote(attrs.pop('corresp').removeprefix('source-attributes:')))
   attrs['source-original-attributes']=original
  row=dict(ordinal=ordinal,parent=ordinals.get(n.getparent()),kind='verse-output-placeholder' if verse is n else 'context-node',tag=etree.QName(n).localname,attributes=attrs,text=n.text,tail=n.tail)
  if verse is n:row.pop('text');row['disposition']='Full literal verse wording/inline structure is in the Bible row at this source address; original native occurrence ID is retained.'
  if n.get('type')=='source-null-absence:source-language-title':row['qualification']='Absent source field: JSON null, not an authored language title. The lexical null token is generated typed accounting.'
  output.append(row)
 return output

def ascii_json(value):
 return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e')

def parts(raw,field_inventory):
 chunks=[];current=[];size=0;events=records(raw,field_inventory)
 for index,event in enumerate(events,1):
  payload=ascii_json(event)
  # A large single source article may exceed the maintained notice cap. Its
  # exact JSON record is divided by character offsets, never stripped/truncated.
  pieces=[payload[i:i+22000] for i in range(0,len(payload),22000)]
  for fragment,piece in enumerate(pieces,1):
   block=('\n## Context event '+str(index)+' fragment '+str(fragment)+' of '+str(len(pieces))+'\n\n'
          '```json-fragment\n'+piece+'\n```\n')
   length=len(block.encode())
   if current and size+length>48000:chunks.append(''.join(current));current=[];size=0
   current.append(block);size+=length
 if current:chunks.append(''.join(current))
 result=[]
 for number,body in enumerate(chunks,1):
  value=('# Original Douay context annex '+str(number).zfill(4)+' of '+str(len(chunks)).zfill(4)+'\n\n'
         'Generated deterministically from the complete actual TEI. These ordered context events retain every nonverse node, field, annotation, article, title, reference, inline style, text and tail, with exact source-field locators and parent ordinals. Verse placeholders preserve position and native occurrence identity while the public Bible rows carry verse wording. Generated source-field IDs are represented by their reversible literal JSON pointer, and opaque source-attribute aliases are decoded; these labels are explanatory, not source-supplied identifiers. JSON string escapes preserve literal whitespace and comparison characters; joining numbered fragments restores each complete record. Null-title records explicitly denote source absence. These context records are not extra Bible verses or newly authored footnotes.\n'+body)
  if len(value.encode())>65536:raise ValueError('Maintained context part exceeds64KiB')
  result.append(value.encode())
 return result
