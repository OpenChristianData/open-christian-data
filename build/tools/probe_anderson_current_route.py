"""Probe the existing Anderson TEI and reversible local publication scaffolds."""
import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote
from lxml import etree
from ocd_kernel.library._common import io_path
from ocd_kernel.projection.categories.bible import project_bible_document, verify_bible_document

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/anderson-current-reconciliation-20261002-v1')
WORK=Path('library/works/anderson-1864-new-testament')
EDITION=WORK/'forms/anderson-1864-new-testament-retained-en/editions/anderson-1864-new-testament-electronic'
OLD=Path('reports/clean-ready-acquisition-to-tei/master-3/21/anderson-1864-new-testament/candidate/content.tei.xml')
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'
BASELINE_SHA='3e939afa458613b26f044094f92e1aa592f5e77df81fb52e78cf59da9458f09a'

def header(source_sha):
 h=etree.Element(NS+'teiHeader',nsmap={None:NS[1:-1]});f=etree.SubElement(h,NS+'fileDesc')
 t=etree.SubElement(f,NS+'titleStmt');etree.SubElement(t,NS+'title').text='The New Testament Translated from the Original Greek'
 p=etree.SubElement(f,NS+'publicationStmt');etree.SubElement(p,NS+'p').text='Private technical preparation of the retained electronic witness; human acceptance, print collation, rights clearance and publication remain separate.'
 s=etree.SubElement(f,NS+'sourceDesc');b=etree.SubElement(s,NS+'bibl')
 etree.SubElement(b,NS+'ptr',type='source',target='https://github.com/BibleCorps/ENG-B1-Anderson1864-pd-USFM')
 for k,v in [('sha256',source_sha),('source_sha256',source_sha),('bible_versification','source-native:anderson-USFM-abfccf6965b4c47781843930907b1ac180e9b4a3')]:etree.SubElement(b,NS+'idno',type=k).text=v
 etree.SubElement(b,NS+'note',type='source-scope').text='All 30 extracted USFM members, 27 New Testament books, front matter, introduction and glossary. ZIP is a package; SWORD and printed witnesses are comparison support. The retained print title is dated 1865 while copyright and dedication/preface identify 1864; equivalence remains uncollated.'
 etree.SubElement(b,NS+'note',type='translation-credit').text='The literal USFM title credits H. T. Anderson. Henry Tompkins Anderson is named by retained configuration and comparison metadata; no additional contributor role is inferred.'
 return h

def adapt(d):
 changes=[]
 for n in d.find(NS+'text').iter():
  old_tag=n.tag;old=dict(n.attrib)
  if n.tag==NS+'ab':
   pointer=n.attrib.pop('corresp',None)
   if pointer:
    raw=n.find(NS+'note')
    if raw is None or raw.get('type')!='source-usfm-raw':raise ValueError('Expected existing raw note')
    raw.set('n',pointer)
   if n.get('type')!='verse':n.attrib.pop('n',None)
  elif n.tag==NS+'supplied':
   if n.get('reason')!='source-marked' or set(n.attrib)!= {'reason'}:raise ValueError('Unexpected supplied form')
   n.tag=NS+'hi';n.attrib.clear();n.set('rend','source-supplied:source-marked')
  elif n.tag==NS+'term':
   if n.get('type')!='glossary-keyword' or set(n.attrib)-{'type','key'}:raise ValueError('Unexpected term form')
   key=n.get('key');n.tag=NS+'seg';n.attrib.clear();n.set('type','source-glossary-keyword'+(':'+quote(key,safe='') if key is not None else ''))
  if n.tag!=old_tag or dict(n.attrib)!=old:changes.append(dict(old_tag=old_tag,new_tag=n.tag,old_attributes=old,new_attributes=dict(n.attrib)))
 return changes

def main():
 raw=io_path(ROOT/OLD).read_bytes()
 if sha256(raw).hexdigest()!=BASELINE_SHA:raise ValueError('Existing exact TEI differs')
 d=etree.fromstring(raw);source_sha=sha256(io_path(ROOT/EDITION/'source-member-set.json').read_bytes()).hexdigest()
 d.replace(d[0],header(source_sha));out=io_path(ROOT/LOG/'projection-probes');out.mkdir(parents=True,exist_ok=True)
 context=dict(identity=dict(work_id='anderson-1864-new-testament',textual_form_id='anderson-1864-new-testament-retained-en',edition_id='anderson-1864-new-testament-electronic'),language='en',representation_revision='anderson-complete-electronic-v1',edition_title='Pinned BibleCorps Anderson 1864 USFM electronic witness',versification='source-native:anderson-USFM-abfccf6965b4c47781843930907b1ac180e9b4a3',source_sha256=source_sha,retained_sha256=source_sha,source_url='https://github.com/BibleCorps/ENG-B1-Anderson1864-pd-USFM')
 cases=[]
 def probe(name):
  p=out/(name+'.tei.xml');p.write_bytes(etree.tostring(d,encoding='UTF-8',xml_declaration=True))
  try:
   result=project_bible_document(p,**context);errors=verify_bible_document(p,result['rows'],result['receipt'],**context)
  except ValueError as error:cases.append(dict(name=name,status='rejected',reason=str(error)));return
  if errors:raise ValueError(errors)
  cases.append(dict(name=name,status='pass',rows=len(result['rows']),empty_rows=sum(r['text']=='' for r in result['rows']),text_characters=sum(len(r['text']) for r in result['rows']),independent_errors=[]))
  (out/'passing-projection.json').write_text(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
 probe('renewed-header-only')
 for k in (XML+'lang','ana'):d.attrib.pop(k,None)
 probe('generated-root-attributes-removed')
 changes=adapt(d);probe('reversible-native-aliases')
 report=dict(baseline_sha256=BASELINE_SHA,source_member_set_sha256=source_sha,cases=cases,alias_counts=Counter((c['old_tag'].rsplit('}',1)[-1]+'->'+c['new_tag'].rsplit('}',1)[-1]) for c in changes),changes=changes,qualification='Diagnostic only. New source-independent feature/attachment oracle and exact inverse, current packaging, replay and guarded installation remain pending. No canonical authority or shared runtime changed.')
 io_path(ROOT/LOG/'current-route-probe.json').write_text(json.dumps(report,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
 print(json.dumps(dict(cases=cases,alias_counts=report['alias_counts'])))
if __name__=='__main__':main()
