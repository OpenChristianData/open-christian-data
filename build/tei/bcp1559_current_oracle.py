"""Independent retained-source observer for the complete BCP1559 expression.

Does not import the producer. Separate CPython lexical reading corroborates all
decoded document text, while lxml provides independently traversed attachment
and hierarchy expectations. Shared HTML recovery assumptions remain explicit.
"""
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import re
import sys
from urllib.parse import quote
from lxml import etree, html
from ocd_kernel.library._common import io_path
from ocd_kernel.tei.validate import compiled_schema

ROOT=Path(__file__).resolve().parents[2]
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
ORACLE_ID='ocd-bcp1559-independent-complete-native-html-v1'
ORACLE_VERSION='1'
INLINE={
 (4,'/html/body/table[3]/tr[2]/td[1]/font[1]/p[1]'):('p','font'),
 (5,'/html/body/div[1]/center[1]/table[1]/tr[1]/td[1]/b[1]/h1[1]'):('h1','b'),
 (5,'/html/body/div[1]/center[1]/table[1]/tr[1]/td[1]/b[1]/h3[1]'):('h3','b'),
 (13,'/html/body/table[3]/tr[3]/td[1]/font[1]/div[1]'):('div','font'),
 (13,'/html/body/table[3]/tr[4]/td[1]/font[1]/div[1]'):('div','font')}


def canonical(value):
 return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()


def closure_sha(root):
 paths=['build/tei/bcp1559_current_oracle.py','ocd_kernel/reconstruction/contract.py',
        'ocd_kernel/reconstruction/verifier.py','ocd_kernel/reconstruction/__init__.py',
        'ocd_kernel/tei/validate.py','ocd_kernel/library/_common.py',
        'ocd_kernel/lib/storage_topology.py']
 return sha256(canonical([dict(path=p,sha256=sha256((root/p).read_bytes()).hexdigest())
                          for p in sorted(paths)])).hexdigest()


class LexicalText(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True)
  self.parts=[]
 def handle_data(self,text):
  self.parts.append(text)


def _source(raw):
 reader=LexicalText(); reader.feed(raw.decode('latin1')); reader.close()
 doc=html.document_fromstring(raw,parser=html.HTMLParser(encoding='iso-8859-1',remove_comments=False))
 entity_rows=[]
 for m in re.finditer(rb'&#(x[0-9a-fA-F]+|[0-9]+);',raw):
  value=int(m[1][1:],16) if m[1][:1].lower()==b'x' else int(m[1])
  if 128 <= value <=159:
   if value not in (134,149): raise ValueError('Unreviewed numeric-reference decoding')
   entity_rows.append({'byte_start':m.start(),'byte_end':m.end(),'lexeme':m[0].decode(),
                       'numeric_value':value,'decoded_character':'\u2020' if value==134 else '\u2022'})
 for old,new in ((chr(134),'\u2020'),(chr(149),'\u2022')):
  if sum((n.text or '').count(old)+(n.tail or '').count(old) for n in doc.iter()) != sum(q['numeric_value']==ord(old) for q in entity_rows):
   raise ValueError('Numeric source lexeme attachment count differs')
  for n in doc.iter():
   if n.text: n.text=n.text.replace(old,new)
   if n.tail: n.tail=n.tail.replace(old,new)
 suffix=raw.decode('latin1').rsplit('</html>',1)[1]
 prefix=raw.decode('latin1').split('<html>',1)[0]
 if suffix not in ('\r\n','\r\n\r\n') or prefix not in ('','<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3//EN">\r\n'):
  raise ValueError('Outside-document lexical envelope differs')
 outside_before='\r\n' if prefix else ''
 if ''.join(reader.parts) != outside_before+''.join(doc.itertext())+suffix:
  raise ValueError('Independent full decoded source text differs; no arbitrary whitespace trim permitted')
 return doc,entity_rows,prefix,suffix


def _expected_attributes(source,index,member,path):
 tag=source.tag if isinstance(source.tag,str) else '#comment'
 obj={'tag':tag,'attributes':[list(v) for v in source.attrib.items()]}
 if tag=='#comment':obj['comment']=source.text or ''
 attrs={XML+'id':f'bcp1559-m{member:02d}-n{index:05d}',
        'ana':'urn:ocd:bcp1559:html:'+quote(json.dumps(obj,ensure_ascii=False,separators=(',',':')),safe='')}
 if (member,path) in INLINE:
  st,parent=INLINE[(member,path)]
  if tag!=st or source.getparent().tag!=parent or any(isinstance(n.tag,str) and n.tag not in ('a','font','span','b','strong','em','i','br','sup','sub','small') for n in source.iterdescendants()):
   raise ValueError('Closed inline-source-block identity/hierarchy differs')
  result='seg';attrs.update(type='source-html-inline-block',subtype=tag)
 elif tag in ('body','p','div','center','blockquote'):
  result='ab';attrs.update(type='source-block',subtype='html-'+tag)
 elif tag in ('h1','h2','h3'):
  result='ab';attrs['type']='source-'+tag
 elif tag in ('b','strong','i','em','sup','sub'):
  result='hi';attrs['rend']='bold' if tag in ('b','strong') else 'italic' if tag in ('i','em') else 'superscript' if tag=='sup' else 'subscript'
 elif tag in ('font','span','small'):
  result='seg';attrs['type']='source-html-'+tag
 elif tag=='table':result='table';attrs['type']='source-html-table'
 elif tag=='tr':result='row'
 elif tag=='td':
  result='cell'
  for src,dst in (('colspan','cols'),('rowspan','rows')):
   if source.get(src) is not None:attrs[dst]=source.get(src)
 elif tag=='ul':result='list';attrs['type']='unordered'
 elif tag=='li':result='item'
 elif tag=='br':result='lb'
 elif tag=='hr':result='milestone';attrs['unit']='horizontal-rule'
 elif tag=='img':
  result='graphic';attrs['url']=source.get('src','')
  if source.get('alt') is not None:attrs['n']=source.get('alt')
 elif tag=='a':
  result='ref' if source.get('href') is not None else 'seg'
  if result=='ref':attrs['target']=source.get('href')
  else:attrs['type']='source-html-anchor'
 elif tag=='#comment':result='anchor';attrs['type']='source-html-comment'
 else:raise ValueError('Unexpected source carrier '+tag)
 return result,attrs


def check_profile(profile,raw,accounting):
 doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
 if doc.tag!=NS+'TEI' or doc.attrib or [n.tag for n in doc]!=[NS+'teiHeader',NS+'text']:
  raise ValueError('Complete one-work TEI envelope differs')
 expected_header=etree.fromstring(profile['header_xml'].encode())
 def header_shape(n):
  return n.tag,list(n.attrib.items()),n.text,n.tail,[header_shape(c) for c in n]
 if header_shape(doc[0])!=header_shape(expected_header):
  raise ValueError('Source-qualified header differs')
 if doc[1].attrib or [n.tag for n in doc[1]]!=[NS+'body'] or doc[1][0].attrib:
  raise ValueError('One complete native body required')
 units=doc[1][0]
 if len(units)!=16 or len(accounting['members'])!=16:raise ValueError('Declared sixteen-member scope differs')
 expected_nodes=[];total=0;entities=0
 for member,(record,unit,evidence) in enumerate(zip(profile['source_members'],units,accounting['members']),1):
  source_raw=io_path(ROOT/record['path']).read_bytes()
  if len(source_raw)!=record['bytes'] or sha256(source_raw).hexdigest()!=record['sha256']:
   raise ValueError('Actual retained source binding differs')
  source,encoded,before,after=_source(source_raw); native=source.find('body'); title=''.join(source.find('head/title').itertext())
  if unit.tag!=NS+'div' or dict(unit.attrib)!={'type':'retained-member','n':record['name']} or len(unit)!=2 or unit[0].tag!=NS+'head' or unit[0].attrib or len(unit[0]) or unit[0].text!=title or unit.text is not None or unit.tail is not None or unit[0].tail is not None:
   raise ValueError('Complete literal member identity/title/envelope differs')
  ordinal=0
  def observe(src,dst,path):
   nonlocal ordinal
   ordinal+=1; index=ordinal
   tag,attrs=_expected_attributes(src,index,member,path)
   if dst.tag!=NS+tag or list(dst.attrib.items())!=list(attrs.items()) or dst.tail!=src.tail:
    raise ValueError('Source carrier tag/ordered attributes/tail differs: '+record['name']+path)
   is_comment=not isinstance(src.tag,str)
   if dst.text!=(None if is_comment else src.text) or len(dst)!=(0 if is_comment else len(src)):
    raise ValueError('Source text/child multiplicity differs: '+record['name']+path)
   expected_nodes.append(dict(member=member,source_path=path,ordinal=index,
     source_tag='#comment' if is_comment else src.tag,source_attributes=[list(v) for v in src.attrib.items()],
     text=src.text,tail=src.tail,target_id=attrs[XML+'id'],target_tag=tag,
     disposition='comment-annotation' if is_comment else 'native-html-body-carrier'))
   tally={}
   for child,target in zip(src,dst):
    name=child.tag if isinstance(child.tag,str) else '#comment';tally[name]=tally.get(name,0)+1
    observe(child,target,path+'/'+name+'['+str(tally[name])+']')
  observe(native,unit[1],'/html/body');total+=ordinal;entities+=len(encoded)
  if evidence['html_envelope']!=etree.tostring(source,encoding='unicode',method='xml') or evidence['native_body_elements']!=ordinal or evidence['numeric_character_references']!=encoded or evidence['pre_html_declaration']!=before or evidence['post_html_whitespace']!=after or evidence['member']!=member or evidence['name']!=record['name'] or evidence['sha256']!=record['sha256']:
   raise ValueError('Complete source envelope/accounting differs')
 if accounting['nodes']!=expected_nodes:raise ValueError('Complete source-to-TEI ledger differs')
 if total!=10307 or entities!=92 or len(doc.findall('.//'+NS+'table'))!=128 or len(doc.findall('.//'+NS+'row'))!=391 or len(doc.findall('.//'+NS+'cell'))!=998:
  raise ValueError('Full native/table/numeric reference census differs')
 compiled_schema().assertValid(doc)
 return dict(status='pass',members=16,body_carriers=total,tables=128,rows=391,cells=998,
             numeric_character_references=entities,p5='pass',
             independent_lexical_text='All decoded document characters agree with CPython HTMLParser, accounting only exact outside-html whitespace.',
             independence='No producer imported. Separate source traversal and lexical parser; lxml HTML hierarchy recovery assumption shared and explicitly qualified.')


def _oracle(manifest,candidate):
 manifest.verify();candidate.verify_integrity()
 if candidate.manifest['source_manifest']['sha256']!=manifest.sha256 or manifest.record['validator']['import_closure_sha256']!=closure_sha(manifest.repository_root):
  raise ValueError('Current source/observer closure differs')
 profile=json.loads(manifest.authority_path('profile').read_bytes())
 facts=check_profile(profile,candidate.member_bytes('content.tei.xml'),json.loads(candidate.member_bytes('source-accountability.json')))
 if candidate.member_bytes('README.source.md')!=manifest.authority_path('source-readme').read_bytes() or [json.loads(q) for q in candidate.member_bytes('unresolved.jsonl').splitlines()]!=profile['questions']:
  raise ValueError('Visible source credits or qualifications differ')
 expected={'work_id':'bcp-1559','source_manifest_sha256':manifest.sha256,'scope':profile['scope'],'status':'nonaccepted'}
 if json.loads(candidate.member_bytes('provenance.json'))!=expected:raise ValueError('Current provenance differs')
 result=dict(status='pass',oracle_id=ORACLE_ID,oracle_version=ORACLE_VERSION,
 implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),import_closure_sha256=closure_sha(manifest.repository_root),
 runtime=f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})',
 source_manifest_sha256=manifest.sha256,candidate_sha256=candidate.sha256,
 profile_sha256=sha256(manifest.authority_path('profile').read_bytes()).hexdigest(),package_schema_sha256=manifest.record['package_schema']['sha256'],
 source_sha256=profile['source_sha256'],xsd_sha256=sha256(manifest.authority_path('tei-p5-xsd').read_bytes()).hexdigest(),
 policy_sha256=sha256(manifest.authority_path('validation-policy-current').read_bytes()).hexdigest(),findings=[])
 result['result_sha256']=sha256(canonical(result)).hexdigest()
 return result


_oracle.oracle_id=ORACLE_ID
_oracle.oracle_version=ORACLE_VERSION
_oracle.implementation_path=Path(__file__).resolve()
