"""Independent englee retained-line, full-tree, and public-row observer."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import copy
import re
from lxml import etree
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.lib.storage_topology import resolve_repo_path

def check_document(path,rows,receipt,*,root,identity,representation_revision,edition_title,authority=None):
    try:
        pin='ebde4b25545bd97f9970916f685ac83fab37a9f6e2fbf35d2c9927948f251fb6'
        wanted_identity=dict(work_id='isaac-leeser-tanakh',textual_form_id='english',edition_id='ebible-englee-leeser-1853')
        if identity!=wanted_identity:
            raise PipelineError('Leeser observer identity differs')
        acq=validate_acquisition(root/'library/works/isaac-leeser-tanakh/forms/english/editions/ebible-englee-leeser-1853/acquisitions/ebible-englee-usfm.json',root=root)
        members=[m for m in acq['retained_files'] if m['path'].endswith('.usfm')]
        if acq['source_sha256']!=pin or len(acq['retained_files'])!=43 or len(members)!=39:
            raise PipelineError('Leeser observer retained members differ')
        raw=path.read_bytes();doc=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,load_dtd=False,no_network=True))
        from . import bible
        header=bible._checker_header(doc,{})
        if header.get('package_url')!=acq['url'] or header.get('source_sha256')!=pin or header.get('retained_sha256')!=pin:raise PipelineError('Leeser source header bindings differ')
        source_binding={'source_url':header['source_url'],'retained_sha256':header['retained_sha256']}
        if header.get('package_url') and header['package_url']!=header['source_url']:source_binding['package_url']=header['package_url']
        if header.get('source_sha256'):source_binding['source_sha256']=header['source_sha256']
        if doc.getroottree().docinfo.doctype or doc.xpath('//comment()|//processing-instruction()'):
            raise PipelineError('Leeser observer declarations differ')
        N='{http://www.tei-c.org/ns/1.0}';X='{http://www.w3.org/XML/1998/namespace}id';S='{http://www.w3.org/XML/1998/namespace}space'
        if doc.tag!=N+'TEI' or [n.tag for n in doc]!=[N+'teiHeader',N+'text'] or len(doc[1])!=1:
            raise PipelineError('Leeser observer complete text/body scope differs')
        body=doc[1][0];expected_body=etree.Element(N+'body')
        expected_work=etree.SubElement(expected_body,N+'div',{'type':'work',X:'isaac-leeser-tanakh-work'})
        expected=[];anchors=[];context_lines=[];blank_slots=[];counts=Counter();versification='source-native:englee-member-set:'+pin
        for member in members:
            payload=resolve_repo_path(root,member['path']).read_bytes()
            if sha256(payload).hexdigest()!=member['sha256'] or len(payload)!=member['bytes']:
                raise PipelineError('Leeser observer source bytes differ')
            source=payload.decode('utf-8',errors='strict')
            if source.startswith('\ufeff') or '\r' in source or source.endswith('\n'):
                raise PipelineError('Leeser observer source line endings differ')
            lines=source.split('\n');code=lines[0].split()[1];filename=Path(member['path']).name
            book=etree.SubElement(expected_work,N+'div',{'type':'book','n':code,X:f'isaac-leeser-tanakh-book-{code}'})
            chapter=None;chapter_order=0;chapter_label=None
            for number,line in enumerate(lines,1):
                marker=line[1:].split(maxsplit=1)[0];counts[marker]+=1
                if not line.startswith('\\') or marker not in {'id','h','toc1','toc2','toc3','mt1','mt2','c','p','v'}:
                    raise PipelineError('Leeser observer unaccounted source line')
                if marker=='c':
                    chapter_order+=1;chapter_label=line[2:].lstrip().split()[0]
                    chapter=etree.SubElement(book,N+'div',{'type':'chapter','n':chapter_label,X:f'isaac-leeser-tanakh-book-{code}-chapter-{chapter_order:03d}'})
                pointer=f'source-usfm:englee/{filename}#line={number}'
                node=etree.SubElement(chapter if chapter is not None else book,N+'ab',{'type':'usfm-source-line','n':str(number),'corresp':pointer,S:'preserve'})
                node.text=line
                if marker!='v':
                    context_lines.append(dict(source_pointer=pointer,text=line));continue
                match=re.fullmatch(r'\\v ([0-9]+) (.*)',line)
                if match is None or chapter is None:
                    raise PipelineError('Leeser observer unsupported native verse label')
                label,wording=match.groups();text=' '.join(wording.split());sequence=len(expected)+1
                if not text:
                    blank_slots.append(dict(source_pointer=pointer,book=code,chapter=chapter_label,verse=label,source_text=line));continue
                locator=dict(kind='verse',book=code,book_osis=f'isaac-leeser-tanakh-book-{code}',chapter=int(chapter_label),verse=label,versification=versification,source_order=sequence,reference_origin='tei-verse-components',reference_status='unsupported-verse-components')
                record=dict(record_id=f'ebible-englee-leeser-1853:verse-{sequence:06d}',sequence=sequence,**wanted_identity,category='bible',language='en',text=text,locator=locator,provenance=dict(edition_title=edition_title),representation_revision=representation_revision,notes=[],references=[],versification=versification)
                expected.append(record);anchors.append(dict(record_id=record['record_id'],source_pointer=pointer,source_order=sequence,text_sha256=sha256(text.encode()).hexdigest(),locator=copy.deepcopy(locator)))
        def compare(actual,wanted):
            if actual.tag!=wanted.tag or dict(actual.attrib)!=dict(wanted.attrib) or len(actual)!=len(wanted):
                raise PipelineError('Leeser observer complete source tree/attributes differ')
            if wanted.tag==N+'ab':
                if actual.text!=wanted.text:
                    raise PipelineError('Leeser observer source wording differs')
            elif (actual.text or '').strip():
                raise PipelineError('Leeser observer unlocated source text')
            if (actual.tail or '').strip():
                raise PipelineError('Leeser observer extra tail text')
            for child,wanted_child in zip(actual,wanted,strict=True):
                compare(child,wanted_child)
        compare(body,expected_body)
        if any((value or '').strip() for value in (doc.text,doc[0].tail,doc[1].text,doc[1].tail)):
            raise PipelineError('Leeser observer extra outer text')
        if counts!=Counter(dict(c=929,h=39,id=39,mt1=39,mt2=2,p=929,toc1=39,toc2=39,toc3=39,v=23145)):
            raise PipelineError('Leeser observer complete marker inventory differs')
        if rows!=expected:
            raise PipelineError('Leeser source-derived rows/fields/order differ')
        bible._validate_rows(rows)
        projection=dict(mapping_version='ocd-englee-source-lines-v1',assembler_version=bible.ASSEMBLER_VERSION,master_sha256=sha256(raw).hexdigest(),scope_id=None,rows=expected,anchors=anchors,inventory=dict(books=39,chapters=929,source_lines=25239,verse_occurrences=23145,context_lines=2094,blank_verse_slots=2),references=[],warnings=[dict(reason='edition-native book IDs and numbering; no cross-edition versification equivalence asserted')],exclusions=[dict(reason='All nonverse USFM source lines remain in the complete master and private receipt.',members=context_lines),dict(reason='Two source-native blank verse slots remain in the complete master; no text invented.',members=blank_slots)],unsupported=[],source_binding=source_binding)
        wanted=bible.build_bible_receipt(projection,identity=identity,authority=authority or {})
        if receipt!=wanted:
            raise PipelineError('Leeser source-derived receipt bindings differ')
        return []
    except (PipelineError,OSError,KeyError,TypeError,ValueError,etree.XMLSyntaxError) as exc:
        return [str(exc)]
