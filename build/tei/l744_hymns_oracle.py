"""Independent html5lib source oracle for the retained L744 hymn editions."""
from __future__ import annotations
import hashlib,json,platform,sys,re
from pathlib import Path
import html5lib
import html5lib.html5parser,html5lib._inputstream,html5lib._tokenizer,html5lib.treebuilders.etree
from lxml import etree
from ocd_kernel.reconstruction import CandidatePackage,SourceManifest
from zipfile import ZipFile
TEI='http://www.tei-c.org/ns/1.0'
XML_ID='{http://www.w3.org/XML/1998/namespace}id'
BOOKS={'l744-pg33128-gospel-hymns':{'ebook':'33128'},'l744-pg33105-chinook-hymns':{'ebook':'33105'}}
def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def encoded(value:object)->bytes:return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def source_html(manifest):
 profile=json.loads(manifest.authority_path('profile').read_bytes());archive=manifest.authority_path('retained-archive')
 if sha(archive.read_bytes())!=profile['archive_sha256']:raise ValueError('source archive digest differs')
 with ZipFile(archive) as z:
  if z.testzip() is not None:raise ValueError('source ZIP CRC failure')
  members=[{'path':x.filename,'bytes':x.file_size,'crc32':f'{x.CRC:08x}','sha256':sha(z.read(x))} for x in z.infolist() if not x.is_dir()]
  if members!=profile['archive_members']:raise ValueError('source ZIP member inventory differs')
  raw=z.read(profile['html_member'])
 raw.decode('utf-8',errors='strict');return raw,profile
ORACLE_ID='ocd-independent-l744-hymns-html5lib-oracle'
def norm(s):return ' '.join(s.split())
def _scoped_text(root):
 parts=[root.text or ""]
 children=list(root)
 for index,child in enumerate(children):
  parts.extend(child.itertext())
  if index<len(children)-1:parts.append(child.tail or "")
 return ''.join(parts)
def _ledger(body):
 rows=[];ordinals={body:0};stack=[(body,None,0)]
 while stack:
  el,parent,pos=stack.pop()
  if el is not body:
   tag=el.tag if isinstance(el.tag,str) else '#comment'; ordinal=len(ordinals);ordinals[el]=ordinal
   rows.append({'ordinal':ordinal,'parent_ordinal':parent,'position':pos,'tag':tag,'attributes':dict(sorted(el.attrib.items())),'text_sha256':sha((el.text or '').encode()),'tail_sha256':sha((el.tail or '').encode())})
  for childpos,ch in reversed(list(enumerate(list(el),1))):stack.append((ch,ordinals[el],childpos))
 return rows,ordinals
def _closure():
 paths=[Path(__file__).resolve(),Path(html5lib.__file__).resolve(),Path(html5lib.html5parser.__file__).resolve(),Path(html5lib._inputstream.__file__).resolve(),Path(html5lib._tokenizer.__file__).resolve(),Path(html5lib.treebuilders.etree.__file__).resolve()]
 return sha(encoded([{'path':x.name,'sha256':sha(x.read_bytes())} for x in paths]))
def _expected_tag(tag):
 if tag=='body':return 'body',None
 maps={'header':('div','provider-header'),'footer':('div','provider-footer'),'blockquote':('div','source-html-blockquote'),'ul':('list','unordered'),'ol':('list','ordered'),'dl':('list','gloss'),'dt':('label',None),'dd':('item',None),'li':('item',None),'pre':('ab',None),'a':('ref',None),'img':('milestone','source-image-reference'),'br':('lb',None),'hr':('milestone',None),'table':('table',None),'tr':('row',None),'td':('cell',None),'th':('cell',None),'abbr':('abbr',None),'b':('hi',None),'strong':('hi',None),'i':('hi',None),'em':('hi',None),'sup':('hi',None),'sub':('hi',None),'span':('seg',None),'small':('hi',None),'code':('code',None),'u':('hi',None),'tbody':('milestone',None),'thead':('milestone',None),'tfoot':('milestone',None),'colgroup':('milestone',None),'col':('milestone',None),'div':('div','source-html-div'),'p':('p',None)}
 if tag in maps:return maps[tag]
 if tag in {'h1','h2','h3','h4','h5','h6'}:return 'head',tag
 if tag=='#comment':return 'milestone','source-html-comment'
 raise ValueError(f'unmapped source tag in independent oracle: {tag}')
def _oracle(manifest:SourceManifest,candidate:CandidatePackage):
 findings=[];work_id=str(manifest.record['work_id']);book=BOOKS[work_id];policy=json.loads(manifest.authority_path('policy').read_bytes());profile=json.loads(manifest.authority_path('profile').read_bytes())
 raw,observed_profile=source_html(manifest)
 try:
  doc=html5lib.parse(raw,treebuilder='etree',namespaceHTMLElements=False);src=doc.find('.//body');head=doc.find('.//head')
  if src is None or head is None:raise ValueError('source HTML head/body missing')
  ledger,ordinals=_ledger(src)
 except Exception as exc:
  findings.append(f'independent source parse failed: {type(exc).__name__}: {exc}');src=None;ledger=[];head=None
 if src is not None:
  if ledger!=profile['node_ledger']:findings.append('complete source node/attribute/parent-position ledger differs from profile')
  if len(src)!=profile['body_direct_child_count'] or sum(1 for x in src.iter() if isinstance(x.tag,str))!=profile['body_element_count']:findings.append('source body carrier census differs from profile')
  head_members=[{'tag':x.tag if isinstance(x.tag,str) else '#comment','attributes':dict(sorted(x.attrib.items())),'text_sha256':sha((x.text or '').encode())} for x in head]
  if head_members!=profile['html_head_members']:findings.append('HTML head envelope differs from profile')
 tei=None;body=None
 try:
  tei=etree.fromstring(candidate.member_bytes('content.tei.xml'),etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True));body=tei.find(f'.//{{{TEI}}}text/{{{TEI}}}body')
  if body is None:findings.append('TEI body missing')
 except Exception as exc:findings.append(f'TEI parse failed: {type(exc).__name__}: {exc}')
 if src is not None and body is not None:
  source_text=_scoped_text(src);target_text=_scoped_text(body)
  normalize_lines=lambda value:value.replace('\r\n','\n').replace('\r','\n')
  if sha(normalize_lines(source_text).encode('utf-8'))!=profile['body_text_sha256']:findings.append('complete source profile body-text digest differs')
  if normalize_lines(source_text)!=normalize_lines(target_text):findings.append('complete source body text or whitespace differs from readable TEI')
  src_nodes=[x for x in src.iter() if isinstance(x.tag,str)]
  trg_nodes=[body]+[x for x in body.iter() if x is not body and x.get('n') is not None and x.get('unit')!='source-html-comment']
  if len(src_nodes)!=profile['body_element_count']:findings.append('source element count changed during traversal')
  if len(trg_nodes)!=len(src_nodes):findings.append('source element was omitted or invented in TEI')
  ledger_by_ordinal={row['ordinal']:row for row in ledger}
  for index,(s,t) in enumerate(zip(src_nodes,trg_nodes),1):
   expected_ord=ordinals[s]
   want_tag,want_type=_expected_tag(s.tag)
   if s.tag in {'div','blockquote'}:
    ancestor=ledger_by_ordinal.get(expected_ord,{}).get('parent_ordinal');inside_item_cell=False
    while ancestor is not None:
     row=ledger_by_ordinal.get(ancestor,{})
     if row.get('tag') in {'li','td','th'}:inside_item_cell=True;break
     ancestor=row.get('parent_ordinal')
    if inside_item_cell:
     if s.tag=='div':want_tag,want_type='milestone','source-html-div'
     elif s.tag=='blockquote':want_tag,want_type='quote',None
   if expected_ord and t.get('n')!=str(expected_ord):findings.append(f'source element order/identity differs at source node {expected_ord}');break
   if etree.QName(t).localname!=want_tag:findings.append(f'source element mapping differs at node {expected_ord}');break
   if want_type and (t.get('unit') if want_tag=='milestone' else t.get('type'))!=want_type:findings.append(f'source element role differs at node {expected_ord}');break
   if s.get('id') and t.get(XML_ID)!=s.get('id'):findings.append(f'source anchor identity differs at node {expected_ord}');break
   if s.tag=='a' and t.get('target')!=s.get('href'):findings.append(f'link target differs at node {expected_ord}');break
   if s.tag=='img' and ('source-image-member:'+s.get('src')) not in (t.get('rend') or ''):findings.append(f'image reference differs at node {expected_ord}');break
   if s.tag=='img' and 'alt' in s.attrib and ('source-alt:'+s.get('alt')) not in (t.get('rend') or ''):findings.append(f'image alt text differs at node {expected_ord}');break
   if s.get('lang') and t.get('{http://www.w3.org/XML/1998/namespace}lang')!=s.get('lang'):findings.append(f'language differs at node {expected_ord}');break
   if s.get('title') and ('source-title:'+s.get('title')) not in (t.get('rend') or ''):findings.append(f'title attribute differs at node {expected_ord}');break
   if s.tag=='img' and 'alt' in s.attrib and ('source-alt:'+s.get('alt')) not in (t.get('rend') or ''):findings.append(f'image alt text differs at node {expected_ord}');break
   if s.get('colspan') and t.get('cols')!=s.get('colspan'):findings.append(f'table cell span differs at node {expected_ord}');break
   css=norm(s.get('class') or '')
   if css and ('source-class:'+css) not in (t.get('rend') or ''):findings.append(f'source class differs at node {expected_ord}');break
  # Every original attribute is either semantically represented or explicitly classified as presentation-only.
  for source_node,target_node in zip(src_nodes,trg_nodes):
   attrs=source_node.attrib
   if source_node.get('id') and target_node.get(XML_ID)!=source_node.get('id'):findings.append('source id attribute is not preserved');break
   if source_node.get('class') and 'source-class:'+norm(source_node.get('class')) not in (target_node.get('rend') or ''):findings.append('source class attribute is not preserved');break
   for key in attrs:
    if key in {'id','class','href','src','alt','title','lang','colspan'}:continue
    if key=='style':
     marker='presentation-style-omitted-sha256:'+sha(attrs[key].encode())
     if marker not in (target_node.get('rend') or ''):findings.append('presentation-only style value lacks an explicit omission marker');break
     continue
    findings.append(f'unclassified source attribute {key!r} on <{source_node.tag}>');break
  source_heads=[(x.tag,norm(''.join(x.itertext()))) for x in src.iter() if isinstance(x.tag,str) and x.tag in {'h1','h2','h3','h4','h5','h6'}]
  tei_heads=[(x.get('type'),norm(''.join(x.itertext()))) for x in body.iter(f'{{{TEI}}}head')]
  if source_heads!=tei_heads:findings.append('heading level, wording, or order differs')
  # Source-native hymn and interlinear boundaries are derived independently from HTML.
  try:
   if book['ebook']=='33128':
    source_h3=[' '.join(''.join(x.itertext()).split()) for x in src.iter('h3')]
    expected=[label for i in range(1,39) for label in (f'Hymn {i}.',f'Nuhguhmoowin {i}.')]
    target_h3=[' '.join(''.join(x.itertext()).split()) for x in body.iter(f'{{{TEI}}}head') if x.get('type')=='h3']
    if source_h3!=expected or target_h3!=expected:findings.append('Ojibway/English hymn pair count, numbering, order, or heading wording differs')
    for section_id in ('titlepg','h','index_e','index_o','phonics'):
     source_node=next((x for x in src.iter() if x.get('id')==section_id),None)
     ledger_row=next((x for x in ledger if source_node is not None and x['ordinal']==ordinals[source_node]),None)
     tei_node=next((x for x in body.iter() if ledger_row is not None and x.get('n')==str(ledger_row['ordinal'])),None)
     if source_node is None or tei_node is None or etree.QName(tei_node).localname!='div':
      findings.append(f'Ojibway collection section boundary is missing: #{section_id}')
     elif ''.join(source_node.itertext()).replace('\r\n','\n').replace('\r','\n')!=''.join(tei_node.itertext()).replace('\r\n','\n').replace('\r','\n'):
      findings.append(f'Ojibway collection section text differs: #{section_id}')
    verse_nodes=[x for x in src.iter('div') if 'verse' in (x.get('class') or '').split()]
    target_verses=[x for x in body.iter(f'{{{TEI}}}div') if 'source-class:verse' in (x.get('rend') or '')]
    if len(verse_nodes)!=390 or len(target_verses)!=390:findings.append('Ojibway verse division count or class boundary differs')
   elif book['ebook']=='33105':
    source_labels=[' '.join(''.join(x.itertext()).split()) for x in src.iter('h3')]
    source_numbered=[x for x in source_labels if re.fullmatch(r'No\. \d+\.',x)]
    expected=[f'No. {i}.' for i in range(1,21)]
    target_labels=[' '.join(''.join(x.itertext()).split()) for x in body.iter(f'{{{TEI}}}head') if x.get('type')=='h3']
    target_numbered=[x for x in target_labels if re.fullmatch(r'No\. \d+\.',x)]
    if source_numbered!=expected or target_numbered!=expected:findings.append('Chinook hymn boundary count, numbering, order, or heading wording differs')
    source_tables=list(src.iter('table'));target_tables=list(body.iter(f'{{{TEI}}}table'))
    if len(source_tables)!=142 or len(target_tables)!=142:findings.append('Chinook interlinear table count differs')
    else:
     for table_index,(source_table,target_table) in enumerate(zip(source_tables,target_tables),1):
      srows=list(source_table.iter('tr'));trows=list(target_table.iter(f'{{{TEI}}}row'))
      if len(srows)!=2 or len(trows)!=2:
       findings.append(f'Chinook interlinear table {table_index} must retain its two-row boundary');break
      source_cells=[[c for c in row if c.tag in {'td','th'}] for row in srows]
      target_cells=[list(row.findall(f'{{{TEI}}}cell')) for row in trows]
      if [len(x) for x in source_cells]!=[1,1] or [len(x) for x in target_cells]!=[1,1]:
       findings.append(f'Chinook interlinear table {table_index} cell boundary differs');break
      source_pair=[''.join(c[0].itertext()).replace('\r\n','\n').replace('\r','\n') for c in source_cells]
      target_pair=[''.join(c[0].itertext()).replace('\r\n','\n').replace('\r','\n') for c in target_cells]
      if source_pair!=target_pair or 'source-class:interlinear' not in (target_table.get('rend') or ''):
       findings.append(f'Chinook interlinear table {table_index} pairing, row order, or class differs');break
    source_closers=[' '.join(''.join(x.itertext()).split()).casefold() for x in src.iter() if isinstance(x.tag,str) and x.tag in {'h3','h4'}]
    target_closers=[' '.join(''.join(x.itertext()).split()).casefold() for x in body.iter(f'{{{TEI}}}head')]
    for phrase in ('lord','blessing before meals'):
     source_hits=[x for x in source_closers if phrase in x]
     target_hits=[x for x in target_closers if phrase in x]
     if len(source_hits)!=1 or source_hits!=target_hits:findings.append(f'Chinook closing material heading is missing or moved: {phrase}')
  except Exception as exc:
   findings.append(f'source-specific boundary check failed: {type(exc).__name__}: {exc}')
  source_links=[(x.get('href'),norm(''.join(x.itertext()))) for x in src.iter('a')]
  target_links=[(x.get('target'),norm(''.join(x.itertext()))) for x in body.iter(f'{{{TEI}}}ref')]
  if source_links!=target_links:findings.append('link count, order, target, or label differs')
  source_images=[x.get('src') for x in src.iter('img')]
  member_paths={m['path']:m for m in profile['archive_members']}
  refs=account_refs=json.loads(candidate.member_bytes('source-accountability.json')).get('source_image_references',[])
  if [r['source_url'] for r in refs]!=source_images:findings.append('source image references are not fully accounted')
  for ref in refs:
   member=member_paths.get(ref['archive_member'])
   if member is None or member['sha256']!=ref['sha256']:findings.append('source image support hash differs from retained archive');break
   if ref.get('package_policy')!='retained-source-support-only; nonrendered TEI header and body milestone':findings.append('source image omission policy is not explicit');break
  if body is not None and any(True for _ in body.iter(f'{{{TEI}}}graphic')):findings.append('unresolved rendered graphic reference remains in the TEI package')
  source_ids=[x.get('id') for x in src.iter() if isinstance(x.tag,str) and x.get('id')]
  if len(source_ids)!=len(set(source_ids)):findings.append('source HTML contains duplicate anchor IDs')
  target_ids=[x.get(XML_ID) for x in body.iter() if x.get(XML_ID)]
  if len(target_ids)!=len(set(target_ids)):findings.append('TEI xml:id values are not unique')
  for href,_ in source_links:
   if href and href.startswith('#') and href[1:] not in set(source_ids):findings.append(f'internal link target is unresolved: {href}');break
 account=json.loads(candidate.member_bytes('source-accountability.json'))
 if account.get('ebook_id')!=book['ebook'] or account.get('source_archive_sha256')!=profile['archive_sha256'] or account.get('source_html_sha256')!=profile['html_sha256'] or account.get('archive_members')!=profile['archive_members']:findings.append('source accountability does not cover the exact archive and member set')
 if body is not None and account.get('candidate_sha256')!=sha(candidate.member_bytes('content.tei.xml')):findings.append('source accountability candidate digest differs')
 if candidate.member_bytes('README.source.md')!=manifest.authority_path('readme').read_bytes():findings.append('source README differs from bound source-local deliverable')
 if json.loads(candidate.member_bytes('provenance.json'))!=policy['provenance']:findings.append('candidate provenance differs from policy')
 if candidate.member_bytes('unresolved.jsonl')!=b''.join(encoded(x) for x in policy['unresolved']):findings.append('candidate unresolved ledger differs from policy')
 try:
  schema=etree.XMLSchema(etree.parse(str(manifest.authority_path('tei-validation-schema'))))
  if tei is None or not schema.validate(tei):findings.append(f'TEI P5 schema validation failed: {schema.error_log.last_error if tei is not None else "no TEI"}')
 except Exception as exc:findings.append(f'TEI schema could not load: {type(exc).__name__}: {exc}')
 roles={x['role']:x for x in manifest.record['authorities']};source_auth=sorted(({'name':x['name'],'path':x['path'],'bytes':x['bytes'],'sha256':x['sha256']} for x in manifest.record['authorities'] if x['role']=='primary-source'),key=lambda x:(x['path'],x['name']))
 source_digest=source_auth[0]['sha256'] if len(source_auth)==1 else sha(encoded({'contract':'ocd-source-member-set-v1','members':source_auth}))
 result={'status':'pass' if not findings else 'fail','oracle_id':ORACLE_ID,'oracle_version':'1','implementation_sha256':sha(Path(__file__).read_bytes()),'import_closure_sha256':_closure(),'runtime':f'{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})','source_manifest_sha256':manifest.sha256,'candidate_sha256':candidate.sha256,'source_sha256':source_digest,'profile_sha256':roles['complete-source-feature-profile']['sha256'],'policy_sha256':roles['independent-validation-policy']['sha256'],'xsd_sha256':roles['tei-validation-schema']['sha256'],'package_schema_sha256':roles['candidate-package-schema']['sha256'],'findings':findings}
 result['result_sha256']=sha(encoded(result));return result
_oracle.oracle_id=ORACLE_ID;_oracle.oracle_version='1';_oracle.implementation_path=Path(__file__).resolve()
