"""Exact retained enggnv single-TEI verse projection; headings stay in the master."""
from __future__ import annotations
from pathlib import Path
from hashlib import sha256
import copy,json,xml.etree.ElementTree as ET
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.projection.envelope import make_row,canonical_row_bytes
WORK='geneva-bible-1599'
IDENTITY=dict(work_id=WORK,textual_form_id='english-geneva-1599',edition_id='ebible-enggnv-usfm')
ED=Path('library/works')/WORK/'forms/english-geneva-1599/editions/ebible-enggnv-usfm'
SOURCE_SHA='3e9111b1826c47f357b8b470c29ff15e7a8722255384c8c942035a420b5ddcef'
N='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}id'
def digest(raw):return sha256(raw).hexdigest()
def source(root):
 acq=validate_acquisition(root/ED/'acquisitions/ebible-enggnv-retained-2026-09-24.json',root=root)
 if acq['source_sha256']!=SOURCE_SHA or len(acq['retained_files'])!=66:raise PipelineError('Geneva exact retained source set differs')
 return acq
def context(root,acceptance_path):
 from . import bible
 meta=bible._accepted_metadata(root,acceptance_path)
 if meta['identity']!=IDENTITY or meta['language']!='en' or meta['acceptance']['source']['source_sha256']!=SOURCE_SHA:raise PipelineError('Geneva accepted identity/source differs')
 included=meta['acceptance']['scope']['included_members'];members=meta['acquisition']['retained_files']
 if len(included)!=66 or meta['acceptance']['scope']['excluded_members']:raise PipelineError('Geneva accepted 66-member accounting differs')
 for i,(a,b) in enumerate(zip(included,members),1):
  if a['position']!=i or any(a[k]!=b[k] for k in ('path','sha256','bytes')):raise PipelineError('Geneva accepted source member/order differs')
 header=bible._header(ET.fromstring(meta['master_path'].read_bytes()));bible._validate_accepted_header(header,meta)
 return meta
def receipt(path,rows,anchors,identity,authority,acq,headings,paragraphs):
 from . import bible
 source_binding=bible._source_binding(bible._header(ET.fromstring(path.read_bytes())))
 projection=dict(mapping_version='ocd-enggnv-source-lines-public-alias-v2',assembler_version=bible.ASSEMBLER_VERSION,master_sha256=digest(path.read_bytes()),scope_id=None,rows=rows,anchors=anchors,inventory=dict(books=66,chapters=1189,source_lines=33864,verse_occurrences=31090,heading_lines=396,paragraph_starts=1189),references=[],warnings=[dict(reason='edition-native book IDs and numbering; no cross-edition versification equivalence asserted')],exclusions=[dict(reason='source headings remain in the complete master and private receipt',members=headings),dict(reason='empty source paragraph starts remain in the complete master and private receipt',members=paragraphs)],unsupported=[],source_binding=source_binding,authority=copy.deepcopy(authority))
 projection['source_binding']=source_binding
 projection['receipt']=bible.build_bible_receipt(projection,identity=identity,authority=authority)
 return projection
def project_document(path,*,root,identity,representation_revision,edition_title,authority=None):
 if identity!=IDENTITY:raise PipelineError('Geneva exact identity differs')
 if representation_revision!='geneva-enggnv-retained-accepted-20261003-v1':raise PipelineError('Geneva public mapping revision differs')
 acq=source(root);raw=path.read_bytes()
 if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:raise PipelineError('Geneva declarations unsupported')
 doc=ET.fromstring(raw);body=doc.find(N+'text/'+N+'body');books=list(body) if body is not None else []
 if len(books)!=66:raise PipelineError('Geneva ordered 66-book master required')
 rows=[];anchors=[];headings=[];paragraphs=[];versification='source-native:enggnv-member-set:'+IDENTITY['edition_id']+':'+representation_revision
 for book in books:
  if book.tag!=N+'div' or book.get('type')!='book' or not book.get(X):raise PipelineError('Geneva book carrier differs')
  for node in book:
   if node.tag==N+'head':headings.append(dict(source_pointer=node.get('corresp'),text=node.text or ''));continue
   if node.tag!=N+'div' or node.get('type')!='chapter':raise PipelineError('Geneva chapter carrier differs')
   for verse in node:
    if verse.tag==N+'milestone':paragraphs.append(dict(source_pointer=verse.get('corresp'),unit=verse.get('unit')));continue
    if verse.tag!=N+'ab' or len(verse):raise PipelineError('Geneva plain verse carrier differs')
    seq=len(rows)+1;text=' '.join((verse.text or '').split());label=verse.get('n')
    if not text or not label or not label.isdigit():raise PipelineError('Geneva verse text or label differs')
    locator=dict(kind='verse',book=book.get('n'),book_osis=book.get(X),chapter=int(node.get('n')),verse=label,versification=versification,source_order=seq,reference_origin='tei-verse-components',reference_status='unsupported-verse-components')
    row=make_row(record_id=f"{identity['edition_id']}:verse-{seq:06d}",sequence=seq,**identity,category='bible',language='en',text=text,locator=locator,provenance=dict(edition_title=edition_title),representation_revision=representation_revision)
    row.update(notes=[],references=[],versification=versification);rows.append(row);anchors.append(dict(record_id=row['record_id'],source_pointer=verse.get('corresp'),source_order=seq,text_sha256=digest(text.encode()),locator=copy.deepcopy(locator)))
 if len(rows)!=31090 or len(headings)!=396 or len(paragraphs)!=1189:raise PipelineError('Geneva full source carrier inventory differs')
 from . import bible
 bible._validate_rows(rows)
 return receipt(path,rows,anchors,identity,authority or {},acq,headings,paragraphs)
def project_accepted(root,*,acceptance_path):
 meta=context(root,acceptance_path)
 result=project_document(meta['master_path'],root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
 # The independent observer also rejects altered master/source carriers.
 from .geneva_native_bible_check import check_document
 errors=check_document(meta['master_path'],result['rows'],result['receipt'],root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
 if errors:raise PipelineError('; '.join(errors))
 return result
def verify_accepted(root,*,acceptance_path,rows,receipt=None):
 from .geneva_native_bible_check import check_document
 try:
  meta=context(root,acceptance_path)
  return check_document(meta['master_path'],rows,receipt,root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
 except (PipelineError,OSError,KeyError,TypeError,ValueError) as exc:return [str(exc)]
