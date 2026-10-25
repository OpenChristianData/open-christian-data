"""Repair four existing Maclaren witnesses with a work-local native emitter."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.maclaren_retained_native_emitter import emit_text
from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el

ROOT = Path(__file__).resolve().parents[2]
WORK = 'expositors-bible--alexander-maclaren'
WORK_ID = WORK
LOG = Path('reports/_logs/maclaren-existing-install-20261003-v1')
SOURCE_DIR = Path('sources/commentaries/expositors-bible/maclaren-retained-install-20261003-v2')
OLD_PACKAGE = LOG / 'retained-lib033-package'
EMITTER_SHA = '6e457b3e1c9187bdcfc2b59a891ed66c9b1ee07fcc1b684c30846b2828430599'
MEMBERS = {'maclaren-expositorpsalms1': ('maclaren_expositorpsalms1.xml', ('i', 'ii'), ('xli',)), 'maclaren-expositorpsalms2': ('maclaren_expositorpsalms2.xml', ('i',), ('lii',)), 'maclaren-expositorpsalms3': ('maclaren_expositorpsalms3.xml', ('i',), ('lxiii',)), 'maclaren-expositorcolphm': ('maclaren_expositorcolphm.xml', ('i', 'ii'), ('v',))}
SPECS = {'maclaren-expositorpsalms1': {'path': 'raw/ccel/expositors-bible/maclaren_expositorpsalms1.xml', 'sha256': '5f76553f07cf45368a772e0a2f654df2852ee9be5c3f0f4d35549391a4791b58', 'bytes': 790728, 'elements': 4279, 'body_elements': 4207, 'comments': 10, 'form': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms1--retained-en', 'edition': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms1--ccel-electronic', 'acquisition': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms1--acquired'}, 'maclaren-expositorpsalms2': {'path': 'raw/ccel/expositors-bible/maclaren_expositorpsalms2.xml', 'sha256': 'e7bf253c78cc91a77c3a3a5173122f89d03b29390ade4f3e14f5d2db2ef98ebb', 'bytes': 1048849, 'elements': 6503, 'body_elements': 6434, 'comments': 10, 'form': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms2--retained-en', 'edition': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms2--ccel-electronic', 'acquisition': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms2--acquired'}, 'maclaren-expositorpsalms3': {'path': 'raw/ccel/expositors-bible/maclaren_expositorpsalms3.xml', 'sha256': '451e5e3c7196a06caa96992cbc7c43f23f033ab84459373368b5685195c942bb', 'bytes': 960697, 'elements': 5443, 'body_elements': 5372, 'comments': 10, 'form': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms3--retained-en', 'edition': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms3--ccel-electronic', 'acquisition': 'expositors-bible--alexander-maclaren--maclaren-expositorpsalms3--acquired'}, 'maclaren-expositorcolphm': {'path': 'raw/ccel/expositors-bible/maclaren_expositorcolphm.xml', 'sha256': 'f611e456b4855ebb529de32346343f0358bfe29f6b114639ab569b4a5a1d3c63', 'bytes': 934108, 'elements': 2777, 'body_elements': 2708, 'comments': 10, 'form': 'expositors-bible--alexander-maclaren--maclaren-expositorcolphm--retained-en', 'edition': 'expositors-bible--alexander-maclaren--maclaren-expositorcolphm--ccel-electronic', 'acquisition': 'expositors-bible--alexander-maclaren--maclaren-expositorcolphm--acquired'}}

def sha(raw):
 return sha256(raw).hexdigest()
SCOPE = ('Complete retained CCEL electronic XML witness for this separately acquired volume; '
         'not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. '
         'These four source XML witnesses contain no image elements. Source layout is not a print or universal typography claim.')


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode('utf-8')


def convert(member_id: str) -> dict[str, bytes]:
    if member_id not in MEMBERS:
        raise ValueError('Unknown existing Maclaren witness')
    if sha256((ROOT/'build/tei/maclaren_retained_native_emitter.py').read_bytes()).hexdigest() != EMITTER_SHA:
        raise ValueError('Pinned work-local Maclaren emitter changed')
    filename,front,back=MEMBERS[member_id]
    source_path='raw/ccel/expositors-bible/'+filename
    raw=(ROOT/source_path).read_bytes()
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    head=source.find('ThML.head')
    if head is None: raise ValueError('Complete source head required')
    spec=SPECS[member_id]
    acquisition_path=Path('library/works')/WORK/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
    acquisition=json.loads((ROOT/acquisition_path).read_bytes())
    if acquisition['source_path']!=source_path or acquisition['source_sha256']!=spec['sha256'] or acquisition['source_bytes']!=len(raw):raise ValueError('Exact Maclaren acquired source URI authority differs')
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
    account['source_head_xml']=etree.tostring(head,encoding='unicode')
    account['source_path']=source_path
    for ordinal,marker in enumerate(account['source_prolog'],1):
        value='Retained source prolog '+str(ordinal)+': '+json.dumps(marker,ensure_ascii=False,sort_keys=True)
        bibl.append(tei_el('note',{'type':'retained-source-prolog','n':str(ordinal)},text=value))
    desc.append(bibl);fd.append(desc);header.append(fd);tei.extend([header,text])
    raw_tei=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
    source_sha=sha256(raw).hexdigest()
    legacy='All four original LIB033 flat feature-ledger members and exact encoded witnesses independently reconciled against current raw sources before readable hierarchy repair.'
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
        'These four XML sources contain no images. Table summaries/spans and th header roles retained; relative hrefs carry exact acquired-source per-ref xml:base, without changing literal targets; navigation next/prev resolves only known source IDs, missing source targets remain explicit annotations. Psalms I / II / III cover 1-38 / 39-89 / 90-150. Psalms I through II often represent verse lines with spans/br; these literal source carriers remain unchanged. No invented stanza grouping or typographic equivalence is claimed.\n')
    notice=(ROOT/'sources/commentaries/expositors-bible/ccel-permission.md').read_bytes().split(b'## Using ThML',1)[0]
    readme+='\nExisting retained CCEL permission record follows; formatting rights and publication remain separate. Do not sell CCEL files or derivatives of their formatting. Attribution: sourced via CCEL.org.\n\n'
    return {'content.tei.xml':raw_tei,'source-accountability.json':canonical(account),
            'README.source.md':readme.encode('utf-8')+notice,
            'provenance.json':canonical(dict(status='nonaccepted',work_id=WORK,member_id=member_id,
                source_path=source_path,source_sha256=source_sha,source_bytes=len(raw),scope=SCOPE,
                legacy_basis=legacy,emitter_sha256=EMITTER_SHA,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')),
            'unresolved.jsonl':canonical(dict(id=member_id+'-human-rights-print-assets',status='unresolved',detail=SCOPE))}


def _convert(manifest: SourceManifest) -> dict[str,bytes]:
    manifest.verify()
    member_id=manifest.record['source_id'].removeprefix('ccel-maclaren-retained-native-').removesuffix('-v1')
    result=convert(member_id)
    if manifest.authority_path('retained-thml').read_bytes() != (ROOT/'raw/ccel/expositors-bible'/MEMBERS[member_id][0]).read_bytes():
        raise ValueError('Retained source binding differs')
    if result['README.source.md'] != manifest.authority_path('source-local-attribution-readme').read_bytes():
        raise ValueError('Visible source credit binding differs')
    return result


_convert.converter_id='ocd-maclaren-retained-native-to-tei'
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
