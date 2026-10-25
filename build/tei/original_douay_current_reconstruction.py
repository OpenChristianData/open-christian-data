"""Bounded reversible scaffolding for the existing complete Original Douay TEI."""
import json,re
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
from lxml import etree

NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'
WORK_ID='original-douay-rheims'
CONVERTER_ID='ocd-original-douay-existing-native-current-v1';CONVERTER_VERSION='1'
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def pointer_id(pointer):return 'odr-source-field-'+sha256(pointer.encode()).hexdigest()

def preserve_empty_spellings(document,raw):
 tokens=list(re.finditer(rb'<(?![/?])([A-Za-z]+)\b[^<>]*>',raw))
 nodes=list(document.iter())
 if len(tokens)!=len(nodes):raise ValueError('Exact element lexical inventory required')
 for token,node in zip(tokens,nodes,strict=True):
  name=token.group(1)
  if etree.QName(node).localname.encode()!=name:raise ValueError('Lexical element order differs')
  if not token.group().endswith(b'/>') and not len(node) and node.text is None and raw[token.end():token.end()+len(name)+3]==b'</'+name+b'>':node.text=''

def add_missing_articles(raw,documents):
 """Renew only nine source-defined omitted chapter articles, before external annotations."""
 from build.tei.original_douay_rheims import _render_article
 d=etree.fromstring(raw);preserve_empty_spellings(d,raw);count=0
 for book in d.find(NS+'text').iter(NS+'div'):
  if book.get('type') not in {'book','appendix-book'}:continue
  rel=book.get('source');doc=documents[rel]
  chapters=[c for c in book if c.tag==NS+'div' and c.get('type')=='chapter']
  for ci,(chapter,source) in enumerate(zip(chapters,doc['chapters'],strict=True)):
   articles=source.get('articles',[])
   if not articles:continue
   if list(source)[-1]!='articles':raise ValueError('Article placement requires newly reviewed source field order')
   if any(c.get('type')=='chapter-article' for c in chapter):raise ValueError('Article already represented')
   scratch=etree.Element(NS+'div');events=[]
   for ai,article in enumerate(articles):_render_article(scratch,article,rel,('chapters',ci,'articles',ai),events,'chapter-article',ai)
   pos=next((i for i,c in enumerate(chapter) if c.get('type')=='chapter-annotations'),len(chapter))
   for article in list(scratch):chapter.insert(pos,article);pos+=1;count+=1
 if count!=9:raise ValueError('Exact nine omitted chapter articles required')
 return etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)
def adapt(raw,header,null_pointers=()):
 d=etree.fromstring(raw);d.replace(d[0],etree.fromstring(header));d.attrib.clear();d.set(XML+'id',WORK_ID)
 text=d.find(NS+'text');group=text.find(NS+'group');group.tag=NS+'body'
 for n in group:
  if n.tag!=NS+'text' or dict(n.attrib) not in [{'type':'testament','n':'OT'},{'type':'testament','n':'NT'}]:raise ValueError('Exact two-testament group required')
  n.tag=NS+'div';n.set('type','source-testament')
  for part in n:
   if part.tag not in {NS+'front',NS+'body'} or part.attrib:raise ValueError('Exact source testament parts required')
   name=etree.QName(part).localname;part.tag=NS+'div';part.set('type','source-part-'+name)
 for ordinal,n in enumerate(text.iter()):
  local=etree.QName(n).localname
  if local=='div':
   extras={k:n.attrib.pop(k) for k in ('source','subtype','ana') if k in n.attrib}
   if n.get('type')=='verse':n.set('type','source-verse-group')
   elif n.get('type')=='appendix-book':extras['original-type']='appendix-book';n.set('type','book')
   if extras:
    if n.get('corresp') is not None:raise ValueError('Source metadata alias conflicts with original target')
    n.set('corresp','source-attributes:'+quote(json.dumps(extras,sort_keys=True,separators=(',',':')),safe=''))
  elif local in {'ab','head','note'}:
   pointer=n.attrib.pop('corresp',None)
   if pointer:
    if XML+'id' in n.attrib:raise ValueError('Source pointer alias conflicts with original ID')
    n.set(XML+'id',pointer_id(pointer))
   if pointer in null_pointers:
    if local!='ab' or n.get('type')!='source-language-title' or n.text!='None' or len(n):raise ValueError('Exact source null-title form required')
    n.set('type','source-null-absence:source-language-title');n.text='null'
   if local=='ab' and n.get('type')=='verse-text':
    if n.getparent().get('type')!='source-verse-group':raise ValueError('Source verse ownership differs')
    n.set('type','verse');n.set('n',n.getparent().get('n'));n.set(XML+'space','preserve')
  elif local=='ref':
   if dict(n.attrib)!={'type':'cross-reference-marker'}:raise ValueError('Unexpected targetless source reference marker')
   n.tag=NS+'seg'
  elif local=='lb':
   if dict(n.attrib)!={'type':'source-br'}:raise ValueError('Unexpected line-break form')
   n.attrib.clear();n.set('break','yes')
  elif local=='hi' and 'ana' in n.attrib:
   if n.get('ana')!='#source-unclosed-markup':raise ValueError('Unexpected markup qualification')
   n.attrib.pop('ana');n.set(XML+'id','odr-source-unclosed-'+str(ordinal))
 return etree.tostring(d,encoding='UTF-8',xml_declaration=True,pretty_print=False)

def _convert(manifest):
 manifest.verify();profile=json.loads(manifest.authority_path('reconstruction-profile').read_bytes())
 from build.tei import original_douay_rheims as historical
 from ocd_kernel.library._common import io_path
 old=manifest.authority_path('historical-native-baseline').read_bytes()
 # Reuse the exact established body builder, not the obsolete ZIP-as-source
 # receipt or its incomplete selected-event assertion.
 config=json.loads(manifest.authority_path('config').read_bytes())
 fresh,counts,events=historical._tei(io_path(manifest.repository_root/profile['source_root']),config)
 repaired=etree.fromstring(old);preserve_empty_spellings(repaired,old)
 for n in repaired.iter():
  if n.get('corresp') in profile['null_source_pointers']:n.text='null'
 expected=etree.tostring(repaired,encoding='UTF-8',xml_declaration=True,pretty_print=False)
 if fresh!=expected:raise ValueError('Established full source replay differs beyond73 typed-null source repairs')
 members=json.loads(manifest.authority_path('member-set').read_bytes())
 documents={m['path'].split('/original-douay-rheims-1.0/',1)[1]:json.loads(io_path(manifest.repository_root/m['path']).read_bytes()) for m in members['members'] if '/bible/tagged/' in m['path']}
 native=add_missing_articles(old,documents)
 if native!=manifest.authority_path('source-complete-native').read_bytes():raise ValueError('Fresh exact9 source article renewal differs')
 return {'content.tei.xml':adapt(native,profile['header_xml'].encode(),profile['null_source_pointers']),'source-accountability.json':manifest.authority_path('current-accountability').read_bytes(),'README.source.md':manifest.authority_path('source-readme').read_bytes(),'unresolved.jsonl':b''.join(canonical(q) for q in profile['questions']),'provenance.json':canonical(dict(work_id=WORK_ID,source_manifest_sha256=manifest.sha256,scope=profile['scope'],status='nonaccepted',existing_native_body_reused=True,repairs=dict(typed_null_absences=73,source_chapter_articles=9),scaffold_policy=profile['scaffold_policy']))}
_convert.converter_id=CONVERTER_ID;_convert.converter_version=CONVERTER_VERSION;_convert.implementation_path=Path(__file__).resolve()
