"""Complete the one existing First Samuel work with a work-local native emitter."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.blaikie_first_samuel_retained_native_emitter import emit_text
from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el

ROOT = Path(__file__).resolve().parents[2]
WORK = 'expositors-bible--william-g-blaikie'
WORK_ID = WORK
LOG = Path('reports/_logs/blaikie-first-samuel-existing-install-20261003-v1')
SOURCE_DIR = Path('sources/commentaries/expositors-bible/blaikie-first-samuel-existing-20261003-v4')
OLD_PACKAGE = LOG / 'qualified-current-lib036-replay'
EMITTER_SHA = 'cdfa1e1390b3af1b752e25e97f2663cbe83ba302d5b17d54e6b510b98904ed98'
MEMBERS = {'blaikie-expositor8': ('blaikie_expositor8.xml', ('i',), ('xl',))}
SPECS = {'blaikie-expositor8': {'path': 'raw/ccel/expositors-bible/blaikie_expositor8.xml', 'sha256': 'b46bd6cb856df0819dedc06b23a657f7763b49501248db63ce762585d67603d4', 'bytes': 818071, 'elements': 2153, 'body_elements': 2049, 'comments': 14, 'form': 'expositors-bible--william-g-blaikie--blaikie-expositor8--retained-en', 'edition': 'expositors-bible--william-g-blaikie--blaikie-expositor8--ccel-electronic', 'acquisition': 'expositors-bible--william-g-blaikie--blaikie-expositor8--acquired'}}

def sha(raw):
 return sha256(raw).hexdigest()
SCOPE = 'Complete retained CCEL electronic XML witness for the separately titled First Book of Samuel commentary, Toronto 1888. One complete authored work; Second Samuel and Joshua excluded; not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. This XML witness contains no image elements. Source layout is not a print or universal typography claim.'

ANCESTORS=('build/tei/dods_retained_native_emitter.py','build/tei/dods_retained_native_prepare.py','build/tei/dods_retained_native_oracle.py')


def lineage_bindings():
    paths=[OLD_PACKAGE/name for name in ('content.tei.xml','source-accountability.json','provenance.json','unresolved.jsonl','README.source.md','manifest.json')]
    paths += [LOG/name for name in ('legacy-replay-receipt.json','source-inventory.json','reconcile_legacy.py')]
    paths += [Path('sources/commentaries/expositors-bible/lib036.reconstruction-profile.json'),Path('sources/commentaries/expositors-bible/lib036.source-manifest.json')]
    return [dict(path=p.as_posix(),bytes=len((ROOT/p).read_bytes()),sha256=sha((ROOT/p).read_bytes())) for p in paths]


def missing_navigation(body):
    ids={n.get('id') for n in body.iter() if isinstance(n.tag,str) and n.get('id')}
    result=[]
    def walk(node,path):
        if not isinstance(node.tag,str):return
        for key in ('next','prev'):
            if node.get(key) is not None and node.get(key) not in ids:
                result.append(dict(source_path=path,source_tag=node.tag,source_id=node.get('id'),field=key,target=node.get(key)))
        for i,child in enumerate(node):walk(child,path+[i])
    for i,node in enumerate(body):walk(node,[i])
    return result


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode('utf-8')


def convert(member_id: str) -> dict[str, bytes]:
    if member_id not in MEMBERS:
        raise ValueError('Unknown existing First Samuel witness')
    if sha256((ROOT/'build/tei/blaikie_first_samuel_retained_native_emitter.py').read_bytes()).hexdigest() != EMITTER_SHA:
        raise ValueError('Pinned work-local First Samuel emitter changed')
    filename,front,back=MEMBERS[member_id]
    source_path='raw/ccel/expositors-bible/'+filename
    raw=(ROOT/source_path).read_bytes()
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    head=source.find('ThML.head')
    if head is None: raise ValueError('Complete source head required')
    spec=SPECS[member_id]
    acquisition_path=Path('library/works')/WORK/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
    acquisition=json.loads((ROOT/acquisition_path).read_bytes())
    if acquisition['source_path']!=source_path or acquisition['source_sha256']!=spec['sha256'] or acquisition['source_bytes']!=len(raw):raise ValueError('Exact Dods acquired source URI authority differs')
    text,account=emit_text(raw,member_id=member_id,front_ids=front,back_ids=back,source_url=acquisition['url'])
    account['source_uri_acquisition_path']=acquisition_path.as_posix();account['source_uri_acquisition_sha256']=sha((ROOT/acquisition_path).read_bytes())
    title=head.findtext('.//DC.Title')
    creators=head.findall('.//DC.Creator')
    author=next(n.text for n in creators if n.get('sub')=='Author' and n.get('scheme')=='short-form')
    editor=next(n.text for n in creators if n.get('sub')=='Editor' and n.get('scheme')=='short-form')
    tei=tei_el('TEI',{'xml:id':member_id+'--candidate'})
    header=tei_el('teiHeader');fd=tei_el('fileDesc');ts=tei_el('titleStmt')
    for tag,value in [('title',title),('author',author),('editor',editor)]:ts.append(tei_el(tag,text=value))
    fd.append(ts);pub=tei_el('publicationStmt')
    pub.append(tei_el('p',text='Reconstruction candidate of an existing acquired electronic witness. Publication: not_ready; human acceptance: not_recorded; rights: unresolved.'))
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
    account['source_root_text']=source.text
    account['source_root_tail']=source.tail
    prefix=raw[:raw.index(b'<ThML')].decode('utf-8')
    account['source_document_prefix']=prefix
    account['source_document_prefix_sha256']=sha(prefix.encode('utf-8'))
    bibl.append(tei_el('note',{'type':'retained-source-document-prefix'},text='Literal retained XML document prefix: '+prefix))
    account['missing_source_navigation']=missing_navigation(source.find('ThML.body'))
    account['source_head_xml']=etree.tostring(head,encoding='unicode')
    account['source_path']=source_path
    for ordinal,marker in enumerate(account['source_prolog'],1):
        value='Retained source prolog '+str(ordinal)+': '+json.dumps(marker,ensure_ascii=False,sort_keys=True)
        bibl.append(tei_el('note',{'type':'retained-source-prolog','n':str(ordinal)},text=value))
    desc.append(bibl);fd.append(desc);header.append(fd);tei.extend([header,text])
    raw_tei=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
    source_sha=sha256(raw).hexdigest()
    legacy='The selected First Samuel member of a frozen qualified current-authority LIB036 converter replay is independently reconciled against its complete current raw source. The inaccessible September 11 package was not recovered, and historical TEI/accounting byte equality or historical oracle pass is not claimed. The historical profile has no First Samuel correction rows. All original raw readings remain in the readable body.'
    historical=json.loads((ROOT/'sources/commentaries/expositors-bible/lib036.reconstruction-profile.json').read_bytes())
    correction_rows=[r for r in historical['text_corrections'] if r['member_id']==member_id]
    account['historical_text_corrections']=correction_rows
    account['historical_correction_disposition']='Original raw source readings retained unchanged in native body. The historical LIB036 profile has zero First Samuel correction rows; no sic/corr annotations or witness correction claims apply to this selected work.'
    readme=(f'# Retained source: {title}\n\nSourced via CCEL.org.\n\n'
        f'Retained authority: {source_path}; SHA-256 {source_sha}; {len(raw)} bytes.\n\n'
        f'Primary source author: {author}. Series editor: {editor}.\n\n'
        f'Literal source printed-edition statement: {head.findtext(".//published")}.\n\n'
        f'Literal DC.Rights: {head.findtext(".//DC.Rights") or "[empty in retained source]"}. '
        'This is the source statement, not a rights clearance. CCEL file formatting and attribution conditions require release review.\n\n'
        'Copyright Christian Classics Ethereal Library is preserved as a source notice where present; source metadata, literal CSS and stylesheet directives are retained in visible header notes and source accounting.\n\n'
        f'{legacy}\n\n{SCOPE}\n\n'
        'Generated administrative index comments retain exact fields and positions in source accounting; their whitespace-only tails are joined in actual TEI. All readable source index content and directives remain in order. '
        'Source h1 through h6 retain their literal source-level heading roles, preserving exact order. This source has no tables or tbody wrappers.\n\n'
        'This First Samuel XML contains no images or tables. Source paragraph, note, page, scripture, anchor and emphasis roles remain readable; relative hrefs carry the exact acquired-source per-ref xml:base, without changing literal targets. Known navigation resolves only source IDs; missing source targets remain explicit annotations. Chapter XXIII retains its author note about paragraphs reproduced from David, King of Israel. The primary title page states Toronto 1888; electronic print metadata literally spells Williard, which remains unchanged. No typographic equivalence is claimed.\n')
    readme+='\nHistorical First Samuel correction ledger: zero selected correction rows; original raw readings remain unchanged:\n\n'+json.dumps(correction_rows,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    readme+='\nLiteral retained XML document prefix, including declaration and DOCTYPE where present:\n\n'+prefix+'\n'
    readme+='\nMissing source navigation targets (retained literal annotations, not invented destinations):\n\n'+json.dumps(account['missing_source_navigation'],ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    notice=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes().split(b'## Using ThML',1)[0]
    readme+='\nExisting retained CCEL permission record follows; formatting rights and publication remain separate. Do not sell CCEL files or derivatives of their formatting. Attribution: sourced via CCEL.org.\n\n'
    return {'content.tei.xml':raw_tei,'source-accountability.json':canonical(account),
            'README.source.md':readme.encode('utf-8')+notice,
            'provenance.json':canonical(dict(contract='ocd-blaikie-first-samuel-composite-provenance-v1',status='nonaccepted',work_id=WORK,member_id=member_id,
                source_path=source_path,source_sha256=source_sha,source_bytes=len(raw),scope=SCOPE,
                source_title=title,source_print_statement=head.findtext('.//published'),source_url=acquisition['url'],form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition'],acquisition_path=acquisition_path.as_posix(),acquisition_sha256=account['source_uri_acquisition_sha256'],source_document_prefix_sha256=account['source_document_prefix_sha256'],
                legacy_basis=legacy,lineage_bindings=lineage_bindings(),historical_accounting_pin_exact=False,historical_tei_pin_exact=False,historical_correction_disposition=account['historical_correction_disposition'],historical_correction_count=len(correction_rows),
                producer_recipe_sha256=sha(Path(__file__).read_bytes()),emitter_sha256=EMITTER_SHA,oracle_sha256=sha((ROOT/'build/tei/blaikie_first_samuel_retained_native_oracle.py').read_bytes()),ancestor_implementation_pins=[dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in ANCESTORS],human_acceptance='not_recorded',rights='unresolved',publication='not_ready')),
            'unresolved.jsonl':canonical(dict(id=member_id+'-human-rights-print',status='unresolved',detail=SCOPE))+canonical(dict(id=member_id+'-missing-source-navigation',status='unresolved',raw_source_fields=account['missing_source_navigation'],disposition='Exact source fields remain typed source annotations; destinations not invented'))}


def _convert(manifest: SourceManifest) -> dict[str,bytes]:
    manifest.verify()
    member_id=manifest.record['source_id'].removeprefix('ccel-blaikie-first-samuel-retained-native-').removesuffix('-v1')
    result=convert(member_id)
    if manifest.authority_path('retained-thml').read_bytes() != (ROOT/'raw/ccel/expositors-bible'/MEMBERS[member_id][0]).read_bytes():
        raise ValueError('Retained source binding differs')
    if result['README.source.md'] != manifest.authority_path('source-local-attribution-readme').read_bytes():
        raise ValueError('Visible source credit binding differs')
    return result


_convert.converter_id='ocd-blaikie-first-samuel-retained-native-to-tei'
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
