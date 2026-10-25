"""Source-native projection of the complete retained englee Tanakh lines."""
from pathlib import Path
from hashlib import sha256
import copy
import re
import xml.etree.ElementTree as ET
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.projection.envelope import make_row
WORK='isaac-leeser-tanakh'
IDENTITY=dict(work_id=WORK,textual_form_id='english',edition_id='ebible-englee-leeser-1853')
ED=Path('library/works')/WORK/'forms/english/editions/ebible-englee-leeser-1853'
SOURCE_SHA='ebde4b25545bd97f9970916f685ac83fab37a9f6e2fbf35d2c9927948f251fb6'
N='{http://www.tei-c.org/ns/1.0}'; X='{http://www.w3.org/XML/1998/namespace}id'
def source(root):
    acq=validate_acquisition(root/ED/'acquisitions/ebible-englee-usfm.json',root=root)
    if acq['source_sha256']!=SOURCE_SHA or len(acq['retained_files'])!=43:
        raise PipelineError('Leeser exact retained source set differs')
    return acq
def context(root,acceptance_path):
    from . import bible
    meta=bible._accepted_metadata(root,acceptance_path)
    if meta['identity']!=IDENTITY or meta['language']!='en' or meta['acceptance']['source']['source_sha256']!=SOURCE_SHA:
        raise PipelineError('Leeser accepted identity/source differs')
    included=meta['acceptance']['scope']['included_members']; members=meta['acquisition']['retained_files']
    if len(included)!=43 or meta['acceptance']['scope']['excluded_members']:
        raise PipelineError('Leeser whole member accounting differs')
    for position,(present,native) in enumerate(zip(included,members,strict=True),1):
        if present['position']!=position or any(present[k]!=native[k] for k in ('path','sha256','bytes')):
            raise PipelineError('Leeser source-member binding differs')
    bible._validate_accepted_header(bible._header(ET.fromstring(meta['master_path'].read_bytes())),meta)
    return meta

def project_document(path,*,root,identity,representation_revision,edition_title,authority=None):
    from . import bible
    if identity!=IDENTITY:
        raise PipelineError('Leeser exact identity differs')
    acq=source(root);raw=path.read_bytes()
    if b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise PipelineError('Leeser declarations unsupported')
    doc=ET.fromstring(raw);parents={child:parent for parent in doc.iter() for child in parent};work=doc.find(N+'text/'+N+'body/'+N+'div')
    if work is None or work.get('type')!='work' or len(work)!=39:
        raise PipelineError('Leeser complete 39-book work required')
    rows=[];anchors=[];context_lines=[];blank_slots=[]
    versification='source-native:englee-member-set:'+SOURCE_SHA
    for book in work:
        if book.tag!=N+'div' or book.get('type')!='book' or not book.get(X):
            raise PipelineError('Leeser book identity differs')
        for node in book.iter(N+'ab'):
            if node.get('type')!='usfm-source-line' or len(node):
                raise PipelineError('Leeser literal source-line carrier required')
            text=node.text or ''
            match=re.fullmatch(r'\\v ([0-9]+) (.*)',text)
            if match is None:
                context_lines.append(dict(source_pointer=node.get('corresp'),text=text));continue
            chapter=parents.get(node)
            if chapter is None or chapter.get('type')!='chapter':
                raise PipelineError('Leeser verse has no source chapter')
            label,wording=match.groups();text=' '.join(wording.split());sequence=len(rows)+1
            if not text:
                blank_slots.append(dict(source_pointer=node.get('corresp'),book=book.get('n'),chapter=chapter.get('n'),verse=label,source_text=node.text));continue
            locator=dict(kind='verse',book=book.get('n'),book_osis=book.get(X),chapter=int(chapter.get('n')),verse=label,versification=versification,source_order=sequence,reference_origin='tei-verse-components',reference_status='unsupported-verse-components')
            row=make_row(record_id=f"{IDENTITY['edition_id']}:verse-{sequence:06d}",sequence=sequence,**IDENTITY,category='bible',language='en',text=text,locator=locator,provenance=dict(edition_title=edition_title),representation_revision=representation_revision)
            row.update(notes=[],references=[],versification=versification);rows.append(row)
            anchors.append(dict(record_id=row['record_id'],source_pointer=node.get('corresp'),source_order=sequence,text_sha256=sha256(text.encode()).hexdigest(),locator=copy.deepcopy(locator)))
    if len(rows)!=23143 or len(context_lines)!=2094 or len(blank_slots)!=2:
        raise PipelineError('Leeser complete source inventory differs')
    bible._validate_rows(rows)
    source_binding=bible._source_binding(bible._header(doc))
    projection=dict(mapping_version='ocd-englee-source-lines-v1',assembler_version=bible.ASSEMBLER_VERSION,master_sha256=sha256(raw).hexdigest(),scope_id=None,rows=rows,anchors=anchors,inventory=dict(books=39,chapters=929,source_lines=25239,verse_occurrences=23145,context_lines=2094,blank_verse_slots=2),references=[],warnings=[dict(reason='edition-native book IDs and numbering; no cross-edition versification equivalence asserted')],exclusions=[dict(reason='All nonverse USFM source lines remain in the complete master and private receipt.',members=context_lines),dict(reason='Two source-native blank verse slots remain in the complete master; no text invented.',members=blank_slots)],unsupported=[],source_binding=source_binding,authority=copy.deepcopy(authority or {}))
    projection['receipt']=bible.build_bible_receipt(projection,identity=identity,authority=authority or {})
    return projection

def project_accepted(root,*,acceptance_path):
    meta=context(root,acceptance_path)
    result=project_document(meta['master_path'],root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
    from .leeser_native_bible_check import check_document
    errors=check_document(meta['master_path'],result['rows'],result['receipt'],root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
    if errors:
        raise PipelineError('; '.join(errors))
    return result

def verify_accepted(root,*,acceptance_path,rows,receipt=None):
    from .leeser_native_bible_check import check_document
    try:
        meta=context(root,acceptance_path)
        return check_document(meta['master_path'],rows,receipt,root=root,identity=meta['identity'],representation_revision=meta['acceptance']['representation_revision']['id'],edition_title=meta['edition'].title,authority=meta['authority'])
    except (PipelineError,OSError,KeyError,TypeError,ValueError) as exc:
        return [str(exc)]
