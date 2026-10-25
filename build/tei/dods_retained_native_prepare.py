"""Repair four existing Dods witnesses with a work-local native emitter."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.dods_retained_native_emitter import emit_text
from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el

ROOT = Path(__file__).resolve().parents[2]
WORK = 'expositors-bible--marcus-dods'
WORK_ID = WORK
LOG = Path('reports/_logs/dods-existing-install-20261003-v1')
SOURCE_DIR = Path('sources/commentaries/expositors-bible/dods-retained-install-20261003-v1')
OLD_PACKAGE = LOG / 'replayed-lib035-package'
EMITTER_SHA = '9156858af96ccc350348731cfd4779368da843adb6e05a67ecffbb76fbd16bf2'
MEMBERS = {'dods-expositor1': ('dods_expositor1.xml', ('i',), ('xxxiii', 'xxxiv')), 'dods-expositor1cor': ('dods_expositor1cor.xml', ('i',), ('xxvii',)), 'dods-expositorjohn1': ('dods_expositorjohn1.xml', ('i', 'ii'), ('xxvii', 'xxviii')), 'dods-expositorjohn2': ('dods_expositorjohn2.xml', ('i',), ('xxviii',))}
SPECS = {'dods-expositor1': {'path': 'raw/ccel/expositors-bible/dods_expositor1.xml', 'sha256': 'dc9526775af27e6820b38f9cf23375b784bce0d457c670aeae930cc000456b65', 'bytes': 844512, 'elements': 1938, 'body_elements': 1875, 'comments': 10, 'form': 'expositors-bible--marcus-dods--dods-expositor1--retained-en', 'edition': 'expositors-bible--marcus-dods--dods-expositor1--ccel-electronic', 'acquisition': 'expositors-bible--marcus-dods--dods-expositor1--acquired'}, 'dods-expositor1cor': {'path': 'raw/ccel/expositors-bible/dods_expositor1cor.xml', 'sha256': '270a4491def4a4a89d74612c1e1caa0205d423d1c6ad620374a060c3d0bb3b3b', 'bytes': 694716, 'elements': 1751, 'body_elements': 1681, 'comments': 14, 'form': 'expositors-bible--marcus-dods--dods-expositor1cor--retained-en', 'edition': 'expositors-bible--marcus-dods--dods-expositor1cor--ccel-electronic', 'acquisition': 'expositors-bible--marcus-dods--dods-expositor1cor--acquired'}, 'dods-expositorjohn1': {'path': 'raw/ccel/expositors-bible/dods_expositorjohn1.xml', 'sha256': 'a492b1d93e0fb5ca06ee88cf515fd7b35b61e432419b7f0e94f0cb84a1ad54d6', 'bytes': 677469, 'elements': 1934, 'body_elements': 1852, 'comments': 10, 'form': 'expositors-bible--marcus-dods--dods-expositorjohn1--retained-en', 'edition': 'expositors-bible--marcus-dods--dods-expositorjohn1--ccel-electronic', 'acquisition': 'expositors-bible--marcus-dods--dods-expositorjohn1--acquired'}, 'dods-expositorjohn2': {'path': 'raw/ccel/expositors-bible/dods_expositorjohn2.xml', 'sha256': '409412471fd4a5965579d992e76b70a08bfce14b446617fff49994c2e4aa47b8', 'bytes': 733463, 'elements': 1912, 'body_elements': 1841, 'comments': 14, 'form': 'expositors-bible--marcus-dods--dods-expositorjohn2--retained-en', 'edition': 'expositors-bible--marcus-dods--dods-expositorjohn2--ccel-electronic', 'acquisition': 'expositors-bible--marcus-dods--dods-expositorjohn2--acquired'}}

def sha(raw):
 return sha256(raw).hexdigest()
SCOPE = ('Complete retained CCEL electronic XML witness for this separately acquired volume; '
         'not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. '
         'These four source XML witnesses contain no image elements. Source layout is not a print or universal typography claim.')

ANCESTORS=('build/tei/maclaren_retained_native_emitter.py','build/tei/maclaren_retained_native_prepare.py','build/tei/maclaren_retained_native_oracle.py')


def lineage_bindings():
    paths=[OLD_PACKAGE/name for name in ('content.tei.xml','source-accountability.json','provenance.json','unresolved.jsonl','README.source.md','manifest.json')]
    paths += [LOG/name for name in ('legacy-replay-receipt.json','source-inventory.json','replay_legacy_lib035.py','reconcile_legacy.py')]
    paths += [Path('sources/commentaries/expositors-bible/lib035.reconstruction-profile.json'),Path('sources/commentaries/expositors-bible/lib035.source-manifest.json')]
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
        raise ValueError('Unknown existing Dods witness')
    if sha256((ROOT/'build/tei/dods_retained_native_emitter.py').read_bytes()).hexdigest() != EMITTER_SHA:
        raise ValueError('Pinned work-local Dods emitter changed')
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
    tei=tei_el('TEI',{'xml:id':member_id})
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
    legacy='Three historical LIB035 Dods flat feature-graph members reconciled independently against current raw sources, including 31 John I correction choices. The replayed accounting exactly matches the historical pin; replayed TEI differs from its dated ticket pin. Historical source readings are preserved in this readable body. John II is the already acquired companion outside that old three-member cohort. Historical correction witness readings have not been independently confirmed from retained witness bytes.'
    historical=json.loads((ROOT/'sources/commentaries/expositors-bible/lib035.reconstruction-profile.json').read_bytes())
    correction_rows=[r for r in historical['text_corrections'] if r['member_id']==member_id]
    account['historical_text_corrections']=correction_rows
    account['historical_correction_disposition']='Original raw source readings retained in native body. Prior sic/corr annotations retained in accounting and visible README; historical transcript URL is not independent witness confirmation.'
    readme=(f'# Retained source: {title}\n\nSourced via CCEL.org.\n\n'
        f'Retained authority: {source_path}; SHA-256 {source_sha}; {len(raw)} bytes.\n\n'
        f'Primary source author: {author}. Series editor: {editor}.\n\n'
        f'Literal source printed-edition statement: {head.findtext(".//published")}.\n\n'
        f'Literal DC.Rights: {head.findtext(".//DC.Rights") or "[empty in retained source]"}. '
        'This is the source statement, not a rights clearance. CCEL file formatting and attribution conditions require release review.\n\n'
        'Copyright Christian Classics Ethereal Library is preserved as a source notice where present; source metadata, literal CSS and stylesheet directives are retained in visible header notes and source accounting.\n\n'
        f'{legacy}\n\n{SCOPE}\n\n'
        'Generated administrative index comments retain exact fields and positions in source accounting; their whitespace-only tails are joined in actual TEI. All readable source index content and directives remain in order. '
        'HTML tbody has no TEI carrier: intact rows remain in their owning table, with wrapper fields and whitespace accounted. Source h1 through h6 are explicit source-level heading paragraphs, preserving exact order.\n\n'
        'These four XML sources contain no images. Source paragraph, list, note, verse, page, citation and emphasis roles retained; relative hrefs carry exact acquired-source per-ref xml:base, without changing literal targets; navigation next/prev resolves only known source IDs, missing source targets remain explicit annotations. Genesis retains its complete Project Gutenberg Information section. John I and John II retain distinct literal New York 1891 and London 1892 printed-edition statements, without asserting a single print edition. Literal source verse and index carriers remain unchanged. No invented stanza grouping or typographic equivalence is claimed.\n')
    readme+='\nHistorical correction annotation ledger (original readings preserved; external witness readings not independently confirmed):\n\n'+json.dumps(correction_rows,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    readme+='\nLiteral retained XML document prefix, including declaration and DOCTYPE where present:\n\n'+prefix+'\n'
    readme+='\nMissing source navigation targets (retained literal annotations, not invented destinations):\n\n'+json.dumps(account['missing_source_navigation'],ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    readme+='\nJohn II Greek index wrapper at source body path [28, 2, 1], id xxviii.ii-p0.2, class Greek, retains all children/order as source-index-container division because it contains a class Index child. Other ordinary unnumbered source containers remain quotes.\n'
    notice=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes().split(b'## Using ThML',1)[0]
    readme+='\nExisting retained CCEL permission record follows; formatting rights and publication remain separate. Do not sell CCEL files or derivatives of their formatting. Attribution: sourced via CCEL.org.\n\n'
    return {'content.tei.xml':raw_tei,'source-accountability.json':canonical(account),
            'README.source.md':readme.encode('utf-8')+notice,
            'provenance.json':canonical(dict(contract='ocd-dods-composite-provenance-v1',status='nonaccepted',work_id=WORK,member_id=member_id,
                source_path=source_path,source_sha256=source_sha,source_bytes=len(raw),scope=SCOPE,
                source_title=title,source_print_statement=head.findtext('.//published'),source_url=acquisition['url'],form_id=spec['form'],edition_id=spec['edition'],acquisition_id=spec['acquisition'],acquisition_path=acquisition_path.as_posix(),acquisition_sha256=account['source_uri_acquisition_sha256'],source_document_prefix_sha256=account['source_document_prefix_sha256'],
                legacy_basis=legacy,lineage_bindings=lineage_bindings(),historical_accounting_pin_exact=True,historical_tei_pin_exact=False,historical_correction_disposition=account['historical_correction_disposition'],historical_correction_count=len(correction_rows),
                producer_recipe_sha256=sha(Path(__file__).read_bytes()),emitter_sha256=EMITTER_SHA,oracle_sha256=sha((ROOT/'build/tei/dods_retained_native_oracle.py').read_bytes()),ancestor_implementation_pins=[dict(path=p,sha256=sha((ROOT/p).read_bytes())) for p in ANCESTORS],human_acceptance='not_recorded',rights='unresolved',publication='not_ready')),
            'unresolved.jsonl':canonical(dict(id=member_id+'-human-rights-print',status='unresolved',detail=SCOPE))+canonical(dict(id=member_id+'-missing-source-navigation',status='unresolved',raw_source_fields=account['missing_source_navigation'],disposition='Exact source fields remain typed source annotations; destinations not invented'))}


def _convert(manifest: SourceManifest) -> dict[str,bytes]:
    manifest.verify()
    member_id=manifest.record['source_id'].removeprefix('ccel-dods-retained-native-').removesuffix('-v1')
    result=convert(member_id)
    if manifest.authority_path('retained-thml').read_bytes() != (ROOT/'raw/ccel/expositors-bible'/MEMBERS[member_id][0]).read_bytes():
        raise ValueError('Retained source binding differs')
    if result['README.source.md'] != manifest.authority_path('source-local-attribution-readme').read_bytes():
        raise ValueError('Visible source credit binding differs')
    return result


_convert.converter_id='ocd-dods-retained-native-to-tei'
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
