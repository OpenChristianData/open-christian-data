"""Source-bound L646 successor: literal links, language, and abbreviation titles."""
from pathlib import Path
from hashlib import sha256
import json,re
from lxml import etree
from html5lib import parse
CONVERTER_ID='ocd-whitefield-l646-semantic-envelope-successor'
CONVERTER_VERSION='3'
NS={'t':'http://www.tei-c.org/ns/1.0'}
TEI=NS['t'];XML='{http://www.w3.org/XML/1998/namespace}'
BASE_SHA='4312f282a014ec138197eb44538723cc9571cc9d59825ebc32e3c4e3e3d1b648'

def _canonical(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def _norm(node):return ' '.join(''.join(node.itertext()).split())
def _repair_footer(source,wrapper):
 before=''.join(wrapper.itertext());assert before.split()==''.join(source.itertext()).split()
 source_tokens=[];links=[]
 def walk(n):
  start=len(''.join(source_tokens))
  if n.text:source_tokens.append(n.text)
  for c in n:
   walk(c)
   if c.tail:source_tokens.append(c.tail)
  if n.tag=='a' and n.get('href'):
   prefix=''.join(source_tokens)[:start];assert not prefix or prefix[-1].isspace();label=''.join(n.itertext());assert len(label.split())==1;links.append((len(prefix.split()),label,n.get('href')))
 walk(source);links.sort();tokens=list(re.finditer(r'\S+',before));assert len(links)==3
 fields=[];offset=0
 if wrapper.text:fields.append((wrapper,'text',offset,offset+len(wrapper.text)));offset+=len(wrapper.text)
 for c in wrapper:
  assert not c.text
  if c.tail:fields.append((c,'tail',offset,offset+len(c.tail)));offset+=len(c.tail)
 assert offset==len(before)
 for token,label,target in reversed(links):
  hit=tokens[token];assert hit.group().startswith(label);owner,attribute,start,end=next(f for f in fields if f[2]<=hit.start() and (hit.start()+len(label))<=f[3]);old=getattr(owner,attribute);ref=etree.Element('{http://www.tei-c.org/ns/1.0}ref',target=target);ref.text=old[hit.start()-start:(hit.start()+len(label))-start];ref.tail=old[(hit.start()+len(label))-start:];setattr(owner,attribute,old[:hit.start()-start])
  if attribute=='text':wrapper.insert(0,ref)
  else:wrapper.insert(wrapper.index(owner)+1,ref)
 assert ''.join(wrapper.itertext())==before;assert [(n.text,n.get('target')) for n in wrapper.findall('t:ref',NS)]==[(label,target) for token,label,target in links]

def _converter(manifest):
 original=manifest.authority_path('previous-candidate-tei').read_bytes();assert sha256(original).hexdigest()==BASE_SHA
 tree=etree.fromstring(original);description=tree.find('t:teiHeader/t:fileDesc',NS);notes=etree.Element('{'+TEI+'}notesStmt');description.insert(list(description).index(description.find('t:sourceDesc',NS)),notes)
 account=json.loads(manifest.authority_path('previous-source-accountability').read_bytes());heads=[];fields=[];language_count=0;title_count=0
 for index,ebook in enumerate(['68976','71140','73012'],1):
  doc=parse(manifest.authority_path('pg'+ebook+'-html').read_bytes(),treebuilder='lxml',namespaceHTMLElements=False);head=doc.find('head');body=doc.find('body');volume=tree.find('t:text/t:body',NS)[index-1];mapped={n.get(XML+'id'):n for n in volume.iter() if n.get(XML+'id')}
  source_footer=next(n for n in body.iter('footer') if n.get('id')=='pg-footer');wrapper=mapped['v'+str(index)+'-pg-footer'].find('t:ab',NS);_repair_footer(source_footer,wrapper)
  for ordinal,node in enumerate(head,1):
   if not isinstance(node.tag,str):continue
   record=dict(ebook_id=ebook,ordinal=ordinal,tag=node.tag,attributes=dict(node.attrib),text=node.text or '',tail=node.tail or '',disposition='private-presentation' if node.tag=='style' else 'literal-source-header-note');heads.append(record)
   if node.tag!='style':note=etree.SubElement(notes,'{'+TEI+'}note',type='source-html-head-field',n=ebook+':head:'+str(ordinal));note.text=json.dumps(dict(tag=node.tag,attributes=dict(node.attrib),text=node.text or ''),ensure_ascii=False,sort_keys=True)
  source_abbr=list(body.iter('abbr'));target_abbr=volume.xpath('.//t:hi[@rend="abbr"]',namespaces=NS);assert len(source_abbr)==len(target_abbr)
  for ordinal,(source,target) in enumerate(zip(source_abbr,target_abbr),1):
   assert _norm(source)==_norm(target) and set(source.attrib)=={'title'}
   identifier=target.get(XML+'id') or 'wf-v'+str(index)+'-abbr-'+str(ordinal).zfill(4);target.set(XML+'id',identifier)
   note=etree.SubElement(notes,'{'+TEI+'}note',type='source-abbreviation-title',target='#'+identifier,n=ebook+':abbr:'+str(ordinal));note.text=source.get('title');title_count+=1
  source_italic=list(body.iter('i'));target_italic=volume.xpath('.//t:hi[@rend="i"]',namespaces=NS);assert len(source_italic)==len(target_italic)
  for ordinal,(source,target) in enumerate(zip(source_italic,target_italic),1):
   assert _norm(source)==_norm(target)
   if source.get('lang') is not None:target.set(XML+'lang',source.get('lang'));language_count+=1
  source_tables=list(body.iter('table'));target_tables=volume.findall('.//t:table',NS);assert len(source_tables)==len(target_tables)
  for source_table,target_table in zip(source_tables,target_tables):
   source_rows=list(source_table.iter('tr'));target_rows=target_table.findall('t:row',NS);assert len(source_rows)==len(target_rows)
   for source_row,target_row in zip(source_rows,target_rows):
    source_cells=[n for n in source_row if n.tag in {'th','td'}];target_cells=target_row.findall('t:cell',NS);assert len(source_cells)==len(target_cells)
    for source_cell,target_cell in zip(source_cells,target_cells):
     if source_cell.get('rowspan') is not None:target_cell.set('rows',source_cell.get('rowspan'))
  for source in body.iter():
   if not isinstance(source.tag,str):continue
   if source.get('lang') is not None and source.tag!='i':
    target=mapped['v'+str(index)+'-'+source.get('id')];target.set(XML+'lang',source.get('lang'));language_count+=1
   if source.get('title') is not None and source.tag!='abbr':
    target=mapped['v'+str(index)+'-'+source.get('id')];note=etree.SubElement(notes,'{'+TEI+'}note',type='source-title-attribute',target='#'+target.get(XML+'id'),n=ebook+':'+source.tag);note.text=source.get('title')
   if source.attrib:fields.append(dict(ebook_id=ebook,tag=source.tag,source_id=source.get('id'),attributes=dict(source.attrib),dispositions={k:('private-source-presentation' if k in {'class','style'} else 'literal-source-semantic-carrier') for k in source.attrib}))
 assert title_count==6506 and language_count==105
 output=etree.tostring(tree,encoding='UTF-8',xml_declaration=True);account.update(source_id=manifest.record['source_id'],source_manifest_sha256=manifest.sha256,candidate_tei_sha256=sha256(output).hexdigest(),source_authorities=[dict(x) for x in manifest.record['authorities']],source_head_envelope=heads,source_body_attribute_inventory=fields,successor=dict(original_candidate_sha256=BASE_SHA,footer_links_restored=9,abbreviation_titles_restored=6506,language_attributes_restored=105,original_source_body_normalized_text_unchanged=True))
 provenance=json.loads(manifest.authority_path('previous-provenance').read_bytes());provenance.update(source_id=manifest.record['source_id'],source_manifest_sha256=manifest.sha256,source_bound_successor='Nine literal footer link targets,6506 exact source abbreviation titles and105 source language attributes restored. Complete head/attribute inventory retained; source styling is privately accounted without CSS interpretation. No new authorship, rights, full-six-volume or publication decision.')
 return {'content.tei.xml':output,'source-accountability.json':_canonical(account),'provenance.json':_canonical(provenance),'unresolved.jsonl':manifest.authority_path('previous-unresolved').read_bytes(),'README.source.md':manifest.authority_path('source-readme-v3').read_bytes()}
_converter.converter_id=CONVERTER_ID
_converter.converter_version=CONVERTER_VERSION
