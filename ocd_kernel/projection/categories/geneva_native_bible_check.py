"""Independent retained USFM/lxml observer for every enggnv source line and row."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json,copy,re
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.projection.envelope import canonical_row_bytes
def check_document(path,rows,receipt,*,root,identity,representation_revision,edition_title,authority=None):
 try:
  pin='3e9111b1826c47f357b8b470c29ff15e7a8722255384c8c942035a420b5ddcef';expected_identity=dict(work_id='geneva-bible-1599',textual_form_id='english-geneva-1599',edition_id='ebible-enggnv-usfm')
  if identity!=expected_identity:raise PipelineError('Geneva source observer identity differs')
  if representation_revision!='geneva-enggnv-retained-accepted-20261003-v1':raise PipelineError('Geneva source observer public mapping revision differs')
  acq=validate_acquisition(root/'library/works/geneva-bible-1599/forms/english-geneva-1599/editions/ebible-enggnv-usfm/acquisitions/ebible-enggnv-retained-2026-09-24.json',root=root)
  if acq['source_sha256']!=pin or len(acq['retained_files'])!=66:raise PipelineError('Geneva source observer member-set identity differs')
  raw=path.read_bytes();doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True));ns={'t':'http://www.tei-c.org/ns/1.0'};N='{'+ns['t']+'}';X='{http://www.w3.org/XML/1998/namespace}id'
  from . import bible
  header=bible._checker_header(doc,{})
  if header.get('package_url')!=acq['url'] or header.get('source_sha256')!=pin or header.get('retained_sha256')!=pin:raise PipelineError('Geneva source header bindings differ')
  source_binding={'source_url':header['source_url'],'retained_sha256':header['retained_sha256']}
  if header.get('package_url') and header['package_url']!=header['source_url']:source_binding['package_url']=header['package_url']
  if header.get('source_sha256'):source_binding['source_sha256']=header['source_sha256']
  if doc.getroottree().docinfo.doctype or doc.xpath('//comment()|//processing-instruction()'):raise PipelineError('Geneva source observer declarations differ')
  texts=doc.findall('t:text',ns)
  if len(texts)!=1 or len(texts[0])!=1:raise PipelineError('Geneva complete text/body scope differs')
  body=texts[0][0]
  if body.tag!=N+'body' or dict(body.attrib)!={'{http://www.w3.org/XML/1998/namespace}space':'preserve'} or body.text or body.tail or len(body)!=66:raise PipelineError('Geneva complete body differs')
  expected=[];anchors=[];headings=[];paragraphs=[];counts=Counter();versification='source-native:enggnv-member-set:'+expected_identity['edition_id']+':'+representation_revision
  for book,member in zip(body,acq['retained_files'],strict=True):
   source=resolve_repo_path(root,member['path']).read_bytes()
   if sha256(source).hexdigest()!=member['sha256'] or len(source)!=member['bytes']:raise PipelineError('Geneva source observer source bytes differ')
   lines=source.decode('utf-8',errors='strict').splitlines();filename=Path(member['path']).name
   code=lines[0][4:].split()[0]
   if book.tag!=N+'div' or dict(book.attrib)!={'type':'book','n':code,X:'enggnv-'+code} or book.text or book.tail:raise PipelineError('Geneva source observer book identity differs')
   carriers=list(book.iter())[1:]
   if len(carriers)!=len(lines):raise PipelineError('Geneva source observer complete source line count differs')
   current=None
   for number,(line,node) in enumerate(zip(lines,carriers,strict=True),1):
    match=re.fullmatch(r'\\([a-z0-9]+)(?: (.*))?',line)
    if match is None:raise PipelineError('Geneva source observer marker differs')
    marker,value=match.groups();counts[marker]+=1;pointer=f'source-usfm:enggnv/{filename}#line={number}'
    if node.tail:raise PipelineError('Geneva source observer extra tail text')
    if marker in ('id','h','toc1','toc2','toc3','mt1'):
     if node.tag!=N+'head' or node.getparent() is not book or len(node) or dict(node.attrib)!={'corresp':pointer} or node.text!=value or current is not None:raise PipelineError('Geneva source observer heading/order differs')
     headings.append(dict(source_pointer=pointer,text=value))
    elif marker=='c':
     if node.tag!=N+'div' or node.getparent() is not book or dict(node.attrib)!={'type':'chapter','n':value.split()[0],'corresp':pointer} or node.text:raise PipelineError('Geneva source observer chapter/attachment differs')
     current=node
    elif marker=='p':
     if node.tag!=N+'milestone' or node.getparent() is not current or len(node) or node.text or value not in (None,'') or dict(node.attrib)!={'unit':'paragraph','corresp':pointer}:raise PipelineError('Geneva source observer paragraph start differs')
     paragraphs.append(dict(source_pointer=pointer,unit='paragraph'))
    elif marker=='v':
     label,wording=value.split(' ',1)
     if node.tag!=N+'ab' or node.getparent() is not current or len(node) or node.text!=wording or dict(node.attrib)!={'n':label,'corresp':pointer}:raise PipelineError('Geneva source observer verse wording/label/attachment differs')
     seq=len(expected)+1;text=' '.join(wording.split());locator=dict(kind='verse',book=code,book_osis='enggnv-'+code,chapter=int(current.get('n')),verse=label,versification=versification,source_order=seq,reference_origin='tei-verse-components',reference_status='unsupported-verse-components')
     record=dict(record_id=f'ebible-enggnv-usfm:verse-{seq:06d}',sequence=seq,**expected_identity,category='bible',language='en',text=text,locator=locator,provenance=dict(edition_title=edition_title),representation_revision=representation_revision,notes=[],references=[],versification=versification)
     expected.append(record);anchors.append(dict(record_id=record['record_id'],source_pointer=pointer,source_order=seq,text_sha256=sha256(text.encode()).hexdigest(),locator=copy.deepcopy(locator)))
    else:raise PipelineError('Geneva source observer unaccounted marker '+marker)
  if counts!=Counter(dict(id=66,h=66,toc1=66,toc2=66,toc3=66,mt1=66,c=1189,p=1189,v=31090)):raise PipelineError('Geneva source observer complete marker inventory differs')
  if rows!=expected:raise PipelineError('Geneva source-derived row fields/order differ')
  bible._validate_rows(rows)
  projection=dict(mapping_version='ocd-enggnv-source-lines-public-alias-v2',assembler_version=bible.ASSEMBLER_VERSION,master_sha256=sha256(raw).hexdigest(),scope_id=None,rows=expected,anchors=anchors,inventory=dict(books=66,chapters=1189,source_lines=33864,verse_occurrences=31090,heading_lines=396,paragraph_starts=1189),references=[],warnings=[dict(reason='edition-native book IDs and numbering; no cross-edition versification equivalence asserted')],exclusions=[dict(reason='source headings remain in the complete master and private receipt',members=headings),dict(reason='empty source paragraph starts remain in the complete master and private receipt',members=paragraphs)],unsupported=[],source_binding=source_binding)
  wanted=bible.build_bible_receipt(projection,identity=identity,authority=authority or {})
  if receipt!=wanted:raise PipelineError('Geneva source-derived receipt bindings differ')
  return []
 except (PipelineError,OSError,KeyError,TypeError,ValueError,etree.XMLSyntaxError) as exc:return [str(exc)]
