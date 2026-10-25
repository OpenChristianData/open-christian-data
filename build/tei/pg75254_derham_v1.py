"""Source-bound reconstruction of Project Gutenberg 75254, Derham, 1720."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Mapping
from zipfile import ZipFile
from lxml import etree,html
from ocd_kernel.reconstruction.contract import SourceManifest

TEI='http://www.tei-c.org/ns/1.0'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
BOOKS={'william-derham-physico-theology-1720': {'ebook':'75254','title':'Physico-theology: Or, a demonstration of the being and attributes of God, from His works of creation','author':'William Derham'}}
def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def enc(value:object)->bytes: return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def node(parent,tag,**attrs): return etree.SubElement(parent,f'{{{TEI}}}{tag}',**attrs)
def _members(z): return [{'path':x.filename,'bytes':x.file_size,'crc32':f'{x.CRC:08x}','sha256':sha(z.read(x))} for x in z.infolist() if not x.is_dir()]
def source_html(manifest:SourceManifest):
 book=BOOKS[manifest.record['work_id']]; profile=json.loads(manifest.authority_path('profile').read_bytes()); path=manifest.authority_path('retained-archive')
 if sha(path.read_bytes())!=profile['archive_sha256']: raise ValueError('retained archive digest differs from profile')
 with ZipFile(path) as z:
  if z.testzip() is not None: raise ValueError('ZIP CRC failure')
  if _members(z)!=profile['archive_members']: raise ValueError('ZIP member inventory differs from profile')
  raw=z.read(profile['html_member'])
 raw.decode('utf-8',errors='strict'); return raw,profile

def _mapped(tag):
 special={'header':('div',{'type':'provider-header'}),'footer':('div',{'type':'provider-footer'}),'blockquote':('div',{'type':'source-html-blockquote'}),'ul':('list',{'type':'unordered'}),'ol':('list',{'type':'ordered'}),'li':('item',{}),'a':('ref',{}),'img':('milestone',{'unit':'source-image-reference'}),'br':('lb',{}),'hr':('milestone',{'unit':'source-rule'}),'table':('table',{}),'tr':('row',{}),'td':('cell',{}),'th':('cell',{'role':'label'}),'abbr':('abbr',{}),'b':('hi',{'rend':'bold'}),'strong':('hi',{'rend':'strong'}),'i':('hi',{'rend':'italic'}),'em':('hi',{'rend':'emphasis'}),'sup':('hi',{'rend':'superscript'}),'sub':('hi',{'rend':'subscript'}),'span':('seg',{}),'small':('hi',{'rend':'small'}),'code':('code',{}),'u':('hi',{'rend':'underline'}),'figure':('figure',{'type':'source-html-figure'}),'figcaption':('figDesc',{})}
 if tag in {'tbody','thead','tfoot','colgroup','col'}:return 'milestone',{'unit':'source-html-'+tag}
 if tag in special:return special[tag]
 if tag=='div':return 'div',{'type':'source-html-div'}
 if tag=='p':return 'p',{}
 if tag in {'h1','h2','h3','h4','h5','h6'}:return 'head',{'type':tag}
 raise ValueError(f'unmapped source HTML element: {tag}')
def _copy(src,parent,counter):
 counter[0]+=1;n=counter[0]
 if not isinstance(src.tag,str):
  out=node(parent,'milestone',unit='source-html-comment',n=str(n));out.set('rend','comment-digest:'+sha((src.text or '').encode()));out.tail=src.tail;return out
 tag=src.tag.lower();outname,attrs=_mapped(tag);parent_name=etree.QName(parent).localname
 # HTML layout divisions have no direct TEI div equivalent inside item/cell.
 if tag=='blockquote' and parent_name=='cell':
  out=node(parent,'quote');out.set('n',str(n));out.set(XML_ID,src.get('id') or f'source-node-{n}')
  css=' '.join((src.get('class') or '').split())
  if css:out.set('rend','source-class:'+css)
  for child in src:_copy(child,out,counter)
  out.tail=src.tail;return out
 if tag=='div' and any(str(a.tag).lower() in {'li','td','th'} for a in src.iterancestors()):
  out=node(parent,'milestone',unit='source-html-div',n=str(n));out.set(XML_ID,src.get('id') or f'source-node-{n}')
  css=' '.join((src.get('class') or '').split())
  if css:out.set('rend','source-class:'+css)
  if src.get('title'):out.set('rend',' '.join(filter(None,(out.get('rend'),'source-title:'+src.get('title')))))
  if src.get('style'):out.set('rend',' '.join(filter(None,(out.get('rend'),'presentation-style-omitted-sha256:'+sha(src.get('style').encode())))))
  if src.get('lang'):out.set('{http://www.w3.org/XML/1998/namespace}lang',src.get('lang'))
  for child in src:_copy(child,parent,counter)
  out.tail=src.tail;return out
 if tag in {'tbody','thead','tfoot','colgroup'}:
  out=node(parent,'milestone',unit='source-html-'+tag,n=str(n));out.set(XML_ID,src.get('id') or f'source-node-{n}')
  css=' '.join((src.get('class') or '').split())
  if css:out.set('rend','source-class:'+css)
  if src.get('style'):out.set('rend',' '.join(filter(None,(out.get('rend'),'presentation-style-omitted-sha256:'+sha(src.get('style').encode())))))
  if src.get('title'):out.set('rend',' '.join(filter(None,(out.get('rend'),'source-title:'+src.get('title')))))
  if src.get('lang'):out.set('{http://www.w3.org/XML/1998/namespace}lang',src.get('lang'))
  for child in src:_copy(child,parent,counter)
  out.tail=src.tail;return out
 if tag=='table':
  figure=node(parent,'figure',type='source-html-table');out=node(figure,'table')
 else:out=node(parent,outname,**attrs)
 out.set('n',str(n));out.set(XML_ID,src.get('id') or f'source-node-{n}')
 css=' '.join((src.get('class') or '').split())
 if css:out.set('rend',' '.join(filter(None,(out.get('rend'),'source-class:'+css))))
 if tag=='a' and src.get('href'):out.set('target',src.get('href'))
 if tag=='img':
  if not src.get('src'):raise ValueError('source image has no src')
  out.set('rend',' '.join(filter(None,(out.get('rend'),'source-image-member:'+src.get('src')))))
  if 'alt' in src.attrib:out.set('rend',' '.join(filter(None,(out.get('rend'),'source-alt:'+src.get('alt')))))
 if tag in {'td','th'} and src.get('colspan'):out.set('cols',src.get('colspan'))
 if src.get('lang'):out.set('{http://www.w3.org/XML/1998/namespace}lang',src.get('lang'))
 if src.get('title'):out.set('rend',' '.join(filter(None,(out.get('rend'),'source-title:'+src.get('title')))))
 if src.get('style'):out.set('rend',' '.join(filter(None,(out.get('rend'),'presentation-style-omitted-sha256:'+sha(src.get('style').encode())))))
 if outname=='div' and src.text and src.text.strip():
  seg=node(out,'div',type='source-block-segment');para=node(seg,'p',rend='source-direct-text');para.text=src.text
 else:out.text=src.text
 for child in src:
  if outname=='figDesc' and child.tag=='p':
   if len(child) or child.attrib:raise ValueError('figure caption paragraph has unsupported structure/attributes')
   counter[0]+=1
   out.text=(out.text or '')+(child.text or '')+(child.tail or '')
   continue
  block=child.tag in {'div','p','header','footer','blockquote','ul','ol','li','table','h1','h2','h3','h4','h5','h6','hr','figure','figcaption'}
  if outname=='div' and parent_name not in {'item','cell'} and isinstance(child.tag,str) and not block:
   seg=node(out,'div',type='source-block-segment');para=node(seg,'p');converted=_copy(child,para,counter)
  elif outname=='div' and parent_name not in {'item','cell'} and child.tag not in {'div'}:
   seg=node(out,'div',type='source-block-segment');converted=_copy(child,seg,counter)
  else:converted=_copy(child,out,counter)
  if outname=='div' and child.tail and child.tail.strip():
   if parent_name in {'item','cell'}:para=node(out,'p',rend='source-direct-text')
   else:para=node(node(out,'div',type='source-block-segment'),'p',rend='source-direct-text')
   para.text=child.tail;converted.tail=None
 if outname=='div':_place_late_heads(out)
 out.tail=src.tail;return out

def _place_late_heads(section):
 """Partition one section into sequential sibling blocks at each late heading."""
 children=list(section)
 if not any(child.tag==f'{{{TEI}}}head' and any(x.tag not in {f'{{{TEI}}}head',f'{{{TEI}}}milestone'} for x in children[:i]) for i,child in enumerate(children)):
  return
 for child in children: section.remove(child)
 current=None;seen=False
 for child in children:
  if child.tag==f'{{{TEI}}}head' and seen: current=None
  if current is None:
   current=etree.SubElement(section,f'{{{TEI}}}div',type='source-heading-segment')
  current.append(child)
  if child.tag not in {f'{{{TEI}}}head',f'{{{TEI}}}milestone'}:seen=True

def _convert(manifest:SourceManifest)->Mapping[str,bytes]:
 book=BOOKS[str(manifest.record['work_id'])]; raw,profile=source_html(manifest); parsed=html.fromstring(raw); srcbody=parsed.find('.//body')
 if srcbody is None:raise ValueError('source HTML body missing')
 root=etree.Element(f'{{{TEI}}}TEI',nsmap={None:TEI});root.set('{http://www.w3.org/XML/1998/namespace}lang','en'); hdr=node(root,'teiHeader');fd=node(hdr,'fileDesc');ts=node(fd,'titleStmt');node(ts,'title').text=book['title'];node(ts,'author').text=book['author'];
 if book['ebook']=='77576':node(ts,'editor').text='Alexander Roberts and James Donaldson'
 pub=node(fd,'publicationStmt');node(pub,'p').text='Nonaccepted source reconstruction. Project Gutenberg states public domain in the USA; no worldwide rights conclusion is recorded.'
 sd=node(fd,'sourceDesc');cover_note=(" The archive cover is retained and hash-accounted as support only; the source HTML body contains no image reference." if book['ebook']=='49917' else " The archive cover is retained and hash-accounted as support evidence; the source body image reference is represented by a nonrendered source-image-reference milestone.");node(sd,'p').text=f"Project Gutenberg eBook {book['ebook']}; archive SHA-256 {profile['archive_sha256']}."+cover_note
 text=node(root,'text');body=node(text,'body');container=node(body,'div',type='complete-gutenberg-html-container');container.text=srcbody.text;counter=[0]
 for child in srcbody:
  if child.tag=='div':_copy(child,container,counter)
  else:
   wrap=node(container,'div',type='source-body-block');_copy(child,wrap,counter)
 _place_late_heads(container)
 xml=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
 image_refs=[]
 member_by_path={x['path']:x for x in profile['archive_members']}
 for row in profile['node_ledger']:
  if row['tag']=='img':
   src=row['attributes'].get('src');member=member_by_path.get(src)
   if not src or not member:raise ValueError(f'source image is not a retained archive member: {src}')
   image_refs.append({'source_url':src,'archive_member':src,'sha256':member['sha256'],'package_policy':'retained-source-support-only; nonrendered TEI header and body milestone'})
 account={'contract':'ocd-gutenberg-complete-body-accountability-v1','source_image_references':image_refs,'ebook_id':book['ebook'],'source_archive_sha256':profile['archive_sha256'],'source_html_sha256':profile['html_sha256'],'candidate_sha256':sha(xml),'candidate_bytes':len(xml),'archive_members':profile['archive_members'],'body_element_count':profile['body_element_count'],'body_direct_child_count':profile['body_direct_child_count'],'body_text_sha256':profile['body_text_sha256'],'mapping':'All source body elements are represented in order as readable TEI elements or explicitly typed milestones. Headings, classes, linked notes, anchor IDs, image references, lists, tables, punctuation, and mixed-inline order are preserved. The feature profile records all original attributes and parent/child positions.','archive_support':'Complete ZIP member set including cover art retained and hash-accounted; no declared archive member is omitted.','html_head_policy':'HTML head stylesheet/provider metadata remain in the retained archive and feature profile; all source body content is reconstructed.'}
 policy=json.loads(manifest.authority_path('policy').read_bytes())
 return {'README.source.md':manifest.authority_path('readme').read_bytes(),'content.tei.xml':xml,'source-accountability.json':enc(account),'provenance.json':enc(policy['provenance']),'unresolved.jsonl':b''.join(enc(x) for x in policy['unresolved'])}
_convert.converter_id='ocd-pg75254-derham-complete-html-to-tei';_convert.converter_version='1';_convert.implementation_path=Path(__file__).resolve()

