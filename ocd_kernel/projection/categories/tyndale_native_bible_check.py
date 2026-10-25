"""Independent retained USFM/lxml observer for every engtnt source line and row."""
from pathlib import Path
from zipfile import ZipFile
from hashlib import sha256
from collections import Counter
import json,copy,re
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.tei.acceptance import _source_binding
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.projection.envelope import canonical_row_bytes
def check_document(path,rows,receipt,*,root,identity,representation_revision,edition_title,authority=None):
 try:
  pin='12b1fb09831fdd259e45faba6fb29df95780a637596af83eb87ef19028d4e453';expected_identity=dict(work_id='tyndale-new-testament-1534',textual_form_id='tyndale-1534-english',edition_id='engtnt-ebible-electronic-1534')
  if identity!=expected_identity:raise PipelineError('Tyndale source observer identity differs')
  acq=validate_acquisition(root/'library/works/tyndale-new-testament-1534/forms/tyndale-1534-english/editions/engtnt-ebible-electronic-1534/acquisitions/engtnt-usfm-archive-1534.json',root=root)
  if _source_binding(acq,context='Tyndale source observer')['source_sha256']!=pin or len(acq['retained_files'])!=1:raise PipelineError('Tyndale source observer member-set identity differs')
  raw=path.read_bytes();doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True));ns={'t':'http://www.tei-c.org/ns/1.0'};N='{'+ns['t']+'}';X='{http://www.w3.org/XML/1998/namespace}id'
  if doc.getroottree().docinfo.doctype or doc.xpath('//comment()|//processing-instruction()'):raise PipelineError('Tyndale source observer declarations differ')
  texts=doc.findall('t:text',ns)
  if len(texts)!=1 or len(texts[0])!=1:raise PipelineError('Tyndale complete text/body scope differs')
  body=texts[0][0]
  if body.tag!=N+'body' or dict(body.attrib)!={} or body.text or body.tail or len(body)!=27:raise PipelineError('Tyndale complete body differs')
  expected=[];anchors=[];headings=[];paragraphs=[];blank_slots=[];counts=Counter();versification='source-native:engtnt-archive:'+pin
  archive=resolve_repo_path(root,acq['retained_files'][0]['path']);archive_raw=archive.read_bytes()
  if sha256(archive_raw).hexdigest()!=pin or len(archive_raw)!=acq['retained_files'][0]['bytes']:raise PipelineError('Tyndale retained ZIP differs')
  with ZipFile(archive) as z:
   if z.testzip() is not None or len(z.namelist())!=30:raise PipelineError('Tyndale full archive inventory or CRC differs')
   filenames=[name for name in z.namelist() if name.endswith('engtnt.usfm')];payloads=[z.read(name) for name in filenames]
   if len(filenames)!=27 or len(set(filenames))!=27:raise PipelineError('Tyndale complete ordered 27-book ZIP members required')
  for book,filename,source in zip(body,filenames,payloads,strict=True):
   lines=source.decode('utf-8',errors='strict').splitlines()
   code=lines[0][4:].split()[0]
   if book.tag!=N+'div' or dict(book.attrib)!={'type':'book','n':code,X:'engtnt-'+code} or book.text or book.tail:raise PipelineError('Tyndale source observer book identity differs')
   carriers=list(book.iter())[1:]
   if len(carriers)!=len(lines):raise PipelineError('Tyndale source observer complete source line count differs')
   current=None
   for number,(line,node) in enumerate(zip(lines,carriers,strict=True),1):
    match=re.fullmatch(r'\\([a-z0-9]+)(?: (.*))?',line)
    if match is None:raise PipelineError('Tyndale source observer marker differs')
    marker,value=match.groups();counts[marker]+=1;pointer=f'source-usfm:engtnt/{filename}#line={number}'
    if node.tail:raise PipelineError('Tyndale source observer extra tail text')
    if marker in ('id','h','toc1','toc2','toc3','mt1'):
     if node.tag!=N+'head' or node.getparent() is not book or len(node) or dict(node.attrib)!={'type':'usfm-'+marker,'corresp':pointer} or node.text!=value or current is not None:raise PipelineError('Tyndale source observer heading/order differs')
     headings.append(dict(source_pointer=pointer,text=value))
    elif marker=='c':
     if node.tag!=N+'div' or node.getparent() is not book or dict(node.attrib)!={'type':'chapter','n':value.split()[0],'corresp':pointer} or node.text:raise PipelineError('Tyndale source observer chapter/attachment differs')
     current=node
    elif marker=='p':
     if node.tag!=N+'milestone' or node.getparent() is not current or len(node) or node.text or value not in (None,'') or dict(node.attrib)!={'unit':'paragraph','corresp':pointer}:raise PipelineError('Tyndale source observer paragraph start differs')
     paragraphs.append(dict(source_pointer=pointer,unit='paragraph'))
    elif marker=='v':
     label,wording=value.split(' ',1)
     if node.tag!=N+'ab' or node.getparent() is not current or len(node) or node.text!=wording or dict(node.attrib)!={'type':'verse','n':label,'corresp':pointer}:raise PipelineError('Tyndale source observer verse wording/label/attachment differs')
     text=' '.join(wording.split())
     if not text:
      blank_slots.append(dict(source_pointer=pointer,book=code,chapter=current.get('n'),verse=label,source_text=wording));continue
     seq=len(expected)+1;locator=dict(kind='verse',book=code,book_osis='engtnt-'+code,chapter=int(current.get('n')),verse=label,versification=versification,source_order=seq,reference_origin='tei-verse-components',reference_status='unsupported-verse-components')
     record=dict(record_id=f'engtnt-ebible-electronic-1534:verse-{seq:06d}',sequence=seq,**expected_identity,category='bible',language='en',text=text,locator=locator,provenance=dict(edition_title=edition_title),representation_revision=representation_revision,notes=[],references=[],versification=versification)
     expected.append(record);anchors.append(dict(record_id=record['record_id'],source_pointer=pointer,source_order=seq,text_sha256=sha256(text.encode()).hexdigest(),locator=copy.deepcopy(locator)))
    else:raise PipelineError('Tyndale source observer unaccounted marker '+marker)
  if counts!=Counter(dict(id=27,h=27,toc1=27,toc2=27,toc3=27,mt1=27,c=260,p=260,v=7957)):raise PipelineError('Tyndale source observer complete marker inventory differs')
  if rows!=expected:raise PipelineError('Tyndale source-derived row fields/order differ')
  from . import bible
  header=bible._checker_header(doc,{})
  if header.get('package_url')!=acq['url'] or header.get('source_sha256')!=pin or header.get('retained_sha256')!=pin:raise PipelineError('Tyndale source header bindings differ')
  source_binding={'source_url':header['source_url'],'retained_sha256':header['retained_sha256']}
  if header.get('package_url') and header['package_url']!=header['source_url']:source_binding['package_url']=header['package_url']
  if header.get('source_sha256'):source_binding['source_sha256']=header['source_sha256']
  bible._validate_rows(rows)
  projection=dict(mapping_version='ocd-engtnt-source-lines-v1',assembler_version=bible.ASSEMBLER_VERSION,master_sha256=sha256(raw).hexdigest(),scope_id=None,rows=expected,anchors=anchors,inventory=dict(books=27,chapters=260,source_lines=8639,verse_occurrences=7957,heading_lines=162,paragraph_starts=260,blank_verse_slots=3),references=[],warnings=[dict(reason='edition-native book IDs and numbering; no cross-edition versification equivalence asserted')],exclusions=[dict(reason='source headings remain in the complete master and private receipt',members=headings),dict(reason='empty source paragraph starts remain in the complete master and private receipt',members=paragraphs),dict(reason='Three source-native blank verse slots remain in the complete master; no text invented.',members=blank_slots)],unsupported=[],source_binding=source_binding)
  wanted=bible.build_bible_receipt(projection,identity=identity,authority=authority or {})
  if receipt!=wanted:raise PipelineError('Tyndale source-derived receipt bindings differ')
  return []
 except (PipelineError,OSError,KeyError,TypeError,ValueError,etree.XMLSyntaxError) as exc:return [str(exc)]
