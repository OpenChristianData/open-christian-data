"""Exact retained engtnt single-TEI verse projection; headings stay in the master."""
from __future__ import annotations
from pathlib import Path
from hashlib import sha256
import copy,json,xml.etree.ElementTree as ET
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.tei.acceptance import _source_binding
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.projection.envelope import make_row,canonical_row_bytes
WORK='tyndale-new-testament-1534'
IDENTITY=dict(work_id=WORK,textual_form_id='tyndale-1534-english',edition_id='engtnt-ebible-electronic-1534')
ED=Path('library/works')/WORK/'forms/tyndale-1534-english/editions/engtnt-ebible-electronic-1534'
SOURCE_SHA='12b1fb09831fdd259e45faba6fb29df95780a637596af83eb87ef19028d4e453'
N='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}id'
def digest(raw):return sha256(raw).hexdigest()
def source(root):
 acq=validate_acquisition(root/ED/'acquisitions/engtnt-usfm-archive-1534.json',root=root)
 if _source_binding(acq,context='Tyndale')['source_sha256']!=SOURCE_SHA or len(acq['retained_files'])!=1:raise PipelineError('Tyndale exact retained source set differs')
 return acq
def context(root,acceptance_path):
 from . import bible
 meta=bible._accepted_metadata(root,acceptance_path)
 if meta['identity']!=IDENTITY or meta['language']!='en' or meta['acceptance']['source']['source_sha256']!=SOURCE_SHA:raise PipelineError('Tyndale accepted identity/source differs')
 included=meta['acceptance']['scope']['included_members'];members=meta['acquisition']['retained_files']
 if len(included)!=1 or meta['acceptance']['scope']['excluded_members']:raise PipelineError('Tyndale accepted ZIP accounting differs')
 for i,(a,b) in enumerate(zip(included,members),1):
  if a['position']!=i or any(a[k]!=b[k] for k in ('path','sha256','bytes')):raise PipelineError('Tyndale accepted source member/order differs')
 header=bible._header(ET.fromstring(meta['master_path'].read_bytes()));bible._validate_accepted_header(header,meta)
 return meta
def receipt(path,rows,anchors,identity,authority,source_binding,headings,paragraphs,blank_slots):
 from . import bible
 projection=dict(mapping_version='ocd-engtnt-source-lines-v1',assembler_version=bible.ASSEMBLER_VERSION,master_sha256=digest(path.read_bytes()),scope_id=None,rows=rows,anchors=anchors,inventory=dict(books=27,chapters=260,source_lines=8639,verse_occurrences=7957,heading_lines=162,paragraph_starts=260,blank_verse_slots=3),references=[],warnings=[dict(reason='edition-native book IDs and numbering; no cross-edition versification equivalence asserted')],exclusions=[dict(reason='source headings remain in the complete master and private receipt',members=headings),dict(reason='empty source paragraph starts remain in the complete master and private receipt',members=paragraphs),dict(reason='Three source-native blank verse slots remain in the complete master; no text invented.',members=blank_slots)],unsupported=[],source_binding=source_binding,authority=copy.deepcopy(authority))
 projection['receipt']=bible.build_bible_receipt(projection,identity=identity,authority=authority)
 return projection
def project_document(path,*,root,identity,representation_revision,edition_title,authority=None):
 if identity!=IDENTITY:raise PipelineError('Tyndale exact identity differs')
 acq=source(root);raw=path.read_bytes()
 if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:raise PipelineError('Tyndale declarations unsupported')
 doc=ET.fromstring(raw);body=doc.find(N+'text/'+N+'body');books=list(body) if body is not None else []
 if len(books)!=27:raise PipelineError('Tyndale ordered 27-book master required')
 rows=[];anchors=[];headings=[];paragraphs=[];blank_slots=[];versification='source-native:engtnt-archive:'+SOURCE_SHA
 for book in books:
  if book.tag!=N+'div' or book.get('type')!='book' or not book.get(X):raise PipelineError('Tyndale book carrier differs')
  for node in book:
   if node.tag==N+'head':headings.append(dict(source_pointer=node.get('corresp'),text=node.text or ''));continue
   if node.tag!=N+'div' or node.get('type')!='chapter':raise PipelineError('Tyndale chapter carrier differs')
   for verse in node:
    if verse.tag==N+'milestone':paragraphs.append(dict(source_pointer=verse.get('corresp'),unit=verse.get('unit')));continue
    if verse.tag!=N+'ab' or len(verse):raise PipelineError('Tyndale plain verse carrier differs')
    seq=len(rows)+1;text=' '.join((verse.text or '').split());label=verse.get('n')
    if not label or not label.isdigit():raise PipelineError('Tyndale verse text or label differs')
    if not text:
     blank_slots.append(dict(source_pointer=verse.get('corresp'),book=book.get('n'),chapter=node.get('n'),verse=label,source_text=verse.text));continue
    locator=dict(kind='verse',book=book.get('n'),book_osis=book.get(X),chapter=int(node.get('n')),verse=label,versification=versification,source_order=seq,reference_origin='tei-verse-components',reference_status='unsupported-verse-components')
    row=make_row(record_id=f"{identity['edition_id']}:verse-{seq:06d}",sequence=seq,**identity,category='bible',language='en',text=text,locator=locator,provenance=dict(edition_title=edition_title),representation_revision=representation_revision)
    row.update(notes=[],references=[],versification=versification);rows.append(row);anchors.append(dict(record_id=row['record_id'],source_pointer=verse.get('corresp'),source_order=seq,text_sha256=digest(text.encode()),locator=copy.deepcopy(locator)))
 if len(rows)!=7954 or len(headings)!=162 or len(paragraphs)!=260 or len(blank_slots)!=3:raise PipelineError('Tyndale full source carrier inventory differs')
 from . import bible
 bible._validate_rows(rows)
 return receipt(path,rows,anchors,identity,authority or {},bible._source_binding(bible._header(doc)),headings,paragraphs,blank_slots)
def project_accepted(root,*,acceptance_path):
 meta=context(root,acceptance_path)
 result=project_document(meta['master_path'],root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
 # The independent observer also rejects altered master/source carriers.
 from .tyndale_native_bible_check import check_document
 errors=check_document(meta['master_path'],result['rows'],result['receipt'],root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
 if errors:raise PipelineError('; '.join(errors))
 return result
def verify_accepted(root,*,acceptance_path,rows,receipt=None):
 from .tyndale_native_bible_check import check_document
 try:
  meta=context(root,acceptance_path)
  return check_document(meta['master_path'],rows,receipt,root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
 except (PipelineError,OSError,KeyError,TypeError,ValueError) as exc:return [str(exc)]
