"""Repair Chadwick's existing retained electronic witnesses using the frozen emitter."""
from __future__ import annotations

from hashlib import sha256
import json
import re
from urllib.parse import urlsplit
from pathlib import Path

from lxml import etree

from build.tei.chadwick_retained_native_emitter import emit_text
from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el

from build.tei.chadwick_retained_scope import ROOT, LOG, WORK_ID, OLD_PACKAGE, MEMBERS as SPECS, retained, reconcile_mark, OLD_TEI_SHA, OLD_ACCOUNT_SHA
WORK = WORK_ID
SOURCE_DIR = Path('sources/commentaries/expositors-bible/chadwick-retained-install-20261003-v2')
EMITTER_SHA = 'a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f'
MEMBERS = {member:(Path(spec['path']).name,tuple(spec['front']),tuple(spec['back'])) for member,spec in SPECS.items()}

def sha(raw):
 return sha256(raw).hexdigest()
SCOPE = ('Complete retained CCEL electronic volume, including every original title/front matter, commentary part, generated index and note; exactly one of the two already acquired Chadwick editions. '
         'Human review, print collation, rights clearance and publication remain separate. No new source or image acquisition.')

def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode('utf-8')


def mark_text(source_raw):
    """Patch only source-backed attributes in exact existing native text bytes."""
    original,legacy,review=reconcile_mark()
    if original.count(b'<text>')!=1 or original.count(b'</text>')!=1:raise ValueError('Original Mark exact text boundary differs')
    begin=original.index(b'<text>');end=original.index(b'</text>',begin)+len(b'</text>')
    body=original[begin:end];unchanged=body
    source=etree.fromstring(source_raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
    nodes=[n for n in source.find('ThML.body').iterdescendants() if isinstance(n.tag,str)]
    changes=[]
    for ordinal,node in enumerate(nodes,1):
        identity=node.get('id') or f'mark-generated-{ordinal:05d}'
        additions=[]
        if re.fullmatch('h[1-4]',node.tag):additions.append(('rend','source-'+node.tag))
        href=node.get('href')
        if node.tag=='a' and href and not href.startswith('#') and not urlsplit(href).scheme:
            additions.append(('xml:base',SPECS['chadwick-mark']['source_base_url']))
        if not additions:continue
        pattern=rb'<[A-Za-z]+(?=[ >])[^>]*\bxml:id="'+re.escape(identity.encode('ascii'))+rb'"[^>]*>'
        matches=list(re.finditer(pattern,body))
        if len(matches)!=1:raise ValueError('Mark native annotation identity cardinality differs '+identity)
        old=matches[0].group(0)
        if any((b' '+key.encode('ascii')+b'=') in old for key,_ in additions):raise ValueError('Unexpected existing Mark annotation '+identity)
        value=old[:-1]+b''.join(b' '+key.encode('ascii')+b'="'+value.encode('ascii')+b'"' for key,value in additions)+b'>'
        body=body[:matches[0].start()]+value+body[matches[0].end():]
        changes.append(dict(source_ordinal=ordinal,source_tag=node.tag,tei_xml_id=identity,attributes=dict(additions),old_start=old.decode('utf-8'),new_start=value.decode('utf-8')))
    restored=body
    for change in changes:
        new=change['new_start'].encode('utf-8');old=change['old_start'].encode('utf-8')
        if restored.count(new)!=1:raise ValueError('Mark annotation byte inverse cardinality differs')
        restored=restored.replace(new,old,1)
    if restored!=unchanged:raise ValueError('Mark readable native text changed beyond bounded attribute additions')
    source_body=source.find('ThML.body')
    account=dict(legacy)
    account.update(route='bounded-existing-readable-mark-annotation-repair',member_id='chadwick-mark',source_sha256=sha(source_raw),
        original_native_tei_sha256=OLD_TEI_SHA,original_account_sha256=OLD_ACCOUNT_SHA,
        original_native_text_sha256=sha(unchanged),annotation_changes=changes,
        source_body_tag=source_body.tag,source_body_attributes=dict(source_body.attrib),source_body_text=source_body.text,source_body_tail=source_body.tail,
        source_body_comments=[dict(path=source.getroottree().getpath(n),text=n.text,tail=n.tail,parent_path=source.getroottree().getpath(n.getparent()),child_index=list(n.getparent()).index(n)) for n in source_body.iter() if n.tag is etree.Comment],
        source_prolog=[dict(node_kind='pi' if n.tag is etree.ProcessingInstruction else 'comment',target=n.target if n.tag is etree.ProcessingInstruction else None,text=n.text,tail=n.tail) for n in source.getroottree().xpath('/processing-instruction() | /comment()')],
        source_body_c14n_sha256=sha(etree.tostring(source_body,method='c14n',with_comments=True)))
    return body,account


def _provenance(member,raw,account):
    spec=SPECS[member]
    relative=Path('library/works')/WORK_ID/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
    acquisition_raw=(ROOT/relative).read_bytes();acquisition=json.loads(acquisition_raw)
    previous=None
    if member=='chadwick-mark':
        previous=dict(package_members=[dict(name=name,bytes=len((ROOT/OLD_PACKAGE/name).read_bytes()),sha256=sha((ROOT/OLD_PACKAGE/name).read_bytes())) for name in sorted(('content.tei.xml','source-accountability.json','manifest.json','provenance.json','README.source.md','unresolved.jsonl'))],original_native_text_sha256=account['original_native_text_sha256'],bounded_additive_annotation_count=len(account['annotation_changes']))
    return dict(contract='ocd-chadwick-existing-retained-provenance-v1',status='nonaccepted',work_id=WORK_ID,member_id=member,
        identity=dict(work_id=WORK_ID,textual_form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition']),
        source_path=spec['path'],source_sha256=sha(raw),source_bytes=len(raw),conversion_route=spec['route'],scope=SCOPE,
        producer=dict(path='build/tei/chadwick_retained_native_prepare.py',sha256=sha(Path(__file__).read_bytes())),
        emitter=dict(ancestor_path='build/tei/ccel_retained_native_emitter.py',ancestor_sha256=EMITTER_SHA,derivative_path='build/tei/chadwick_retained_native_emitter.py',derivative_sha256=sha((ROOT/'build/tei/chadwick_retained_native_emitter.py').read_bytes()),used_for_this_member=member=='chadwick-exodus'),
        primary_acquisition=dict(path=relative.as_posix(),bytes=len(acquisition_raw),sha256=sha(acquisition_raw),url=acquisition['url'],source_path=acquisition['source_path'],source_sha256=acquisition['source_sha256'],source_bytes=acquisition['source_bytes']),
        original_mark=previous,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')


def convert(member_id: str) -> dict[str, bytes]:
    if member_id not in MEMBERS:
        raise ValueError('Unknown existing Chadwick witness')
    if sha256((ROOT/'build/tei/ccel_retained_native_emitter.py').read_bytes()).hexdigest() != EMITTER_SHA:
        raise ValueError('Frozen CCEL emitter changed')
    filename,front,back=MEMBERS[member_id]
    source_path='raw/ccel/expositors-bible/'+filename
    raw=retained(member_id)
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    head=source.find('ThML.head')
    if head is None: raise ValueError('Complete source head required')
    if member_id == 'chadwick-mark':
        preserved_text,account = mark_text(raw)
        text = None
    else:
        text,account=emit_text(raw,member_id=member_id,front_ids=front,back_ids=back)
        preserved_text = None
    title=head.findtext('.//DC.Title')
    creators=head.findall('.//DC.Creator')
    author=next(n.text for n in creators if n.get('sub')=='Author' and n.get('scheme')=='short-form')
    editor=next(n.text for n in creators if n.get('sub')=='Editor' and n.get('scheme')=='short-form')
    tei=tei_el('TEI',{'xml:id':member_id})
    header=tei_el('teiHeader');fd=tei_el('fileDesc');ts=tei_el('titleStmt')
    for tag,value in [('title',title),('author',author),('editor',editor)]:ts.append(tei_el(tag,text=value))
    fd.append(ts);pub=tei_el('publicationStmt')
    pub.append(tei_el('p',text='Agent-reviewed reconstruction of an existing acquired electronic witness. Human review, print collation, CCEL formatting rights and publication remain separate gates.'))
    fd.append(pub);desc=tei_el('sourceDesc')
    qualification=tei_el('bibl')
    qualification.append(tei_el('note',{'type':'source-limitations'},text=SCOPE))
    desc.append(qualification)
    bibl=tei_el('bibl');bibl.append(tei_el('title',text=title))
    header_records=[]
    for ordinal,node in enumerate(head.iter(),1):
        if not isinstance(node.tag,str):
            value='Retained source head comment: '+(node.text or '')
            bibl.append(tei_el('note',{'type':'retained-source-head-comment','n':str(ordinal)},text=value))
            header_records.append(dict(ordinal=ordinal,kind='comment',text=node.text,tail=node.tail,
                source_xpath=source.getroottree().getpath(node),visible_header_note_text=value))
            continue
        path=source.getroottree().getpath(node)
        record=dict(ordinal=ordinal,kind='element',tag=node.tag,attributes=dict(node.attrib),
                    text=node.text,tail=node.tail,source_xpath=path)
        if (node.text or '').strip() or node.attrib:
            value='Source field '+path+': '+json.dumps(dict(attributes=dict(node.attrib),text=node.text),ensure_ascii=False,sort_keys=True)
            bibl.append(tei_el('note',{'type':'retained-source-head-field','n':str(ordinal)},text=value))
            record['visible_header_note_text']=value
        header_records.append(record)
    account['source_head_records']=header_records
    account['source_root_attributes']=dict(source.attrib)
    account['source_head_xml']=etree.tostring(head,encoding='unicode')
    account['source_path']=source_path
    for ordinal,marker in enumerate(account['source_prolog'],1):
        value='Retained source prolog '+str(ordinal)+': '+json.dumps(marker,ensure_ascii=False,sort_keys=True)
        bibl.append(tei_el('note',{'type':'retained-source-prolog','n':str(ordinal)},text=value))
    prefix = raw[:raw.index(b'<ThML')].decode('utf-8')
    account['source_document_prefix'] = prefix
    bibl.append(tei_el('note',{'type':'retained-source-document-prefix'},text=prefix))
    desc.append(bibl);fd.append(desc);header.append(fd);tei.append(header)
    if preserved_text is None:
        tei.append(text)
        raw_tei=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
    else:
        scaffold=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
        if not scaffold.endswith(b'</TEI>'):raise ValueError('Chadwick header scaffold boundary differs')
        raw_tei=scaffold[:-len(b'</TEI>')]+preserved_text+b'</TEI>' 
    source_sha=sha256(raw).hexdigest()
    legacy='The exact previously reviewed Mark readable TEI/package is retained and field-for-field reconciled; Mark text is preserved with only source heading-level and per-query XML base annotations. The already downloaded Exodus companion is completed independently within its existing canonical edition; bounded prior candidate discovery is qualified.'
    readme=(f'# Retained source: {title}\n\nSourced via CCEL.org.\n\n'
        f'Retained authority: {source_path}; SHA-256 {source_sha}; {len(raw)} bytes.\n\n'
        f'Primary source author: {author}. Series editor: {editor}.\n\n'
        f'Literal source printed-edition statement: {head.findtext(".//published")}.\n\n'
        f'Literal DC.Rights: {head.findtext(".//DC.Rights") or "[empty in retained source]"}. '
        'This is the source statement, not a rights clearance. CCEL file formatting and attribution conditions require release review. Copies of CCEL-produced electronic files must not be sold, and published excerpts must attribute CCEL.org, as recorded in the retained permission evidence.\n\n'
        'Copyright Christian Classics Ethereal Library is preserved as a source notice where present; source metadata, literal CSS and stylesheet directives are retained in visible header notes and source accounting.\n\n'
        f'{legacy}\n\n{SCOPE}\n\n'
        'Generated administrative index comments retain exact fields and positions in source accounting. Mark keeps its original native whitespace; Exodus joins administrative comment whitespace to adjacent native carriers. All readable index content/directives remain in source order. '
        'Source heading levels remain explicit; Mark keeps its existing native heading carriers and Exodus uses source-level heading paragraphs.\n\n'
        'Mark retains all original readable hierarchy and direct/tail fields; only source h1-h4 level attributes and acquired URL context are added to its exact existing native text bytes. The source unresolved prev/next toc pointers remain literal qualified exclusions, without invented targets. '
        'Exodus retains all original hierarchy, including grouped Chapters XXXV-XL and the literal The Typial Bearings of the History. Its single broken #xxvi-Page_348 link labelled 8 remains unsupported with its exact literal target. '
        'Complete source headers, CSS, stylesheet/copyright prolog and literal XML declaration/DOCTYPE prefix are visible and accounted. External DTDs are never fetched. Relative query links retain literal targets with primary acquired CCEL HTML URL context. Both source envelopes contain no images or tables.\n')
    return {'content.tei.xml':raw_tei,'source-accountability.json':canonical(account),
            'README.source.md':readme.encode('utf-8'),
            'provenance.json':canonical(_provenance(member_id,raw,account)),
            'unresolved.jsonl':canonical(dict(id=member_id+'-human-rights-print-assets',status='unresolved',detail=SCOPE))}


def _convert(manifest: SourceManifest) -> dict[str,bytes]:
    manifest.verify()
    member_id=manifest.record['source_id'].removeprefix('ccel-chadwick-retained-native-').removesuffix('-v1')
    result=convert(member_id)
    if manifest.authority_path('retained-thml').read_bytes() != (ROOT/'raw/ccel/expositors-bible'/MEMBERS[member_id][0]).read_bytes():
        raise ValueError('Retained source binding differs')
    if result['README.source.md'] != manifest.authority_path('source-local-attribution-readme').read_bytes():
        raise ValueError('Visible source credit binding differs')
    return result


_convert.converter_id='ocd-chadwick-retained-native-to-tei'
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()


def main() -> None:
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path);parser.add_argument('--source-manifest',type=Path)
    args=parser.parse_args()
    if args.source_manifest:
        print(reconstruct(SourceManifest.load(args.source_manifest,repository_root=ROOT),args.destination,_convert).sha256)
    else:
        for member in MEMBERS:
            out=args.destination/member;out.mkdir(parents=True,exist_ok=True)
            for name,content in convert(member).items():(out/name).write_bytes(content)


if __name__=='__main__':main()
