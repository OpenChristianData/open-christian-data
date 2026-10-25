"""Repair Watson's existing retained electronic witnesses using the frozen emitter."""
from __future__ import annotations

from hashlib import sha256
from functools import lru_cache
import base64
import json
from pathlib import Path

from lxml import etree

from build.tei.watson_retained_native_emitter import emit_text
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage,reconstruct
from ocd_kernel.tei.writer import tei_el

ROOT = Path(__file__).resolve().parents[2]
WORK = 'expositors-bible--r-a-watson'
WORK_ID = WORK
LOG = Path('reports/_logs/watson-existing-install-20261003-v1')
SOURCE_DIR = Path('sources/commentaries/expositors-bible/watson-retained-install-20261003-v2')
OLD_PACKAGE = LOG/'retained-final-package'
EMITTER_SHA = 'da178027a2057ebf4242c98adeb2605a5f6c15cb5bc945b190b0dc7a767e219a'
MEMBERS = {'watson-ra-expositor7': ('watson_ra_expositor7.xml', ('i', 'iii'), ('vi', 'vii')), 'watson-ra-expositorjob': ('watson_ra_expositorjob.xml', ('i',), ('viii', 'ix')), 'watson-ra-expositornum': ('watson_ra_expositornum.xml', ('i',), ('xxviii', 'xxix'))}
SPECS = {'watson-ra-expositor7': {'path': 'raw/ccel/expositors-bible/watson_ra_expositor7.xml', 'sha256': '9d235aa2fd1d93d33c3a1bb8ea462c28c30ea01f711cc44c091d337dd792ad47', 'bytes': 811010, 'elements': 3261, 'body_elements': 3168, 'form': 'expositors-bible--r-a-watson--watson-ra-expositor7--retained-en', 'edition': 'expositors-bible--r-a-watson--watson-ra-expositor7--ccel-electronic', 'acquisition': 'expositors-bible--r-a-watson--watson-ra-expositor7--acquired'}, 'watson-ra-expositorjob': {'path': 'raw/ccel/expositors-bible/watson_ra_expositorjob.xml', 'sha256': '9e8fab9fe169699cad7ab72c0cc5cc77732c6b1045379b3693d351b804180bc0', 'bytes': 853065, 'elements': 5540, 'body_elements': 5482, 'form': 'expositors-bible--r-a-watson--watson-ra-expositorjob--retained-en', 'edition': 'expositors-bible--r-a-watson--watson-ra-expositorjob--ccel-electronic', 'acquisition': 'expositors-bible--r-a-watson--watson-ra-expositorjob--acquired'}, 'watson-ra-expositornum': {'path': 'raw/ccel/expositors-bible/watson_ra_expositornum.xml', 'sha256': 'ea84347fe36b4380749c077dc41bf4a8431f0a7bf7157668579833bb72dc602f', 'bytes': 877572, 'elements': 4148, 'body_elements': 4086, 'form': 'expositors-bible--r-a-watson--watson-ra-expositornum--retained-en', 'edition': 'expositors-bible--r-a-watson--watson-ra-expositornum--ccel-electronic', 'acquisition': 'expositors-bible--r-a-watson--watson-ra-expositornum--acquired'}}

def sha(raw):
 return sha256(raw).hexdigest()
SCOPE = ('Complete retained CCEL electronic XML witness for this separately acquired volume; '
         'not complete author or series. Human acceptance, print collation, rights and publication remain unresolved. '
         'External image pixels were not acquired, inferred or visually reviewed.')


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode('utf-8')


@lru_cache(maxsize=1)
def historical():
    package=CandidatePackage.load(ROOT/OLD_PACKAGE)
    if package.sha256!='685517f52f9be603117e42c1afe9d6bf2d20a95145c855b7cbb5b37971042605' or sha(package.member_bytes('content.tei.xml'))!='94c7f5a9b7c393dca2fd53e07d5f3a21f39c995cbe0266b776b6914d8c919f75':raise ValueError('Exact Watson historical package changed')
    return package,etree.fromstring(package.member_bytes('content.tei.xml')),json.loads(package.member_bytes('source-accountability.json'))


def convert(member_id: str) -> dict[str, bytes]:
    if member_id not in MEMBERS:
        raise ValueError('Unknown existing Watson witness')
    if sha256((ROOT/'build/tei/watson_retained_native_emitter.py').read_bytes()).hexdigest() != EMITTER_SHA:
        raise ValueError('Frozen CCEL emitter changed')
    filename,front,back=MEMBERS[member_id]
    source_path='raw/ccel/expositors-bible/'+filename
    raw=(ROOT/source_path).read_bytes()
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    head=source.find('ThML.head')
    if head is None: raise ValueError('Complete source head required')
    spec=SPECS[member_id]
    acquisition_path=Path('library/works')/WORK/'forms'/spec['form']/'editions'/spec['edition']/'acquisitions'/(spec['acquisition']+'.json')
    acquisition=json.loads((ROOT/acquisition_path).read_bytes())
    if acquisition['source_path']!=source_path or acquisition['source_sha256']!=sha(raw):raise ValueError('Watson acquired source URI context changed')
    package,original,old_account=historical()
    embedded=original.xpath('//*[@xml:id=$id]/tei:note[@type="exact-retained-source-bytes"]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace','tei':'http://www.tei-c.org/ns/1.0'},id=member_id)
    if len(embedded)!=1 or base64.b64decode(embedded[0].text,validate=True)!=raw:raise ValueError('Replayed embedded Watson source bytes do not match acquired witness')
    original_member=original.xpath('//*[@xml:id=$id]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'},id=member_id)
    if len(original_member)!=1:raise ValueError('Unique historical Watson member required')
    text,account=emit_text(raw,member_id=member_id,front_ids=front,back_ids=back,source_base=acquisition['url'])
    account.update(original_package_sha256=package.sha256,original_member_c14n_sha256=sha(etree.tostring(original_member[0],method='c14n',with_comments=True)),source_uri_acquisition_path=acquisition_path.as_posix(),source_uri_acquisition_sha256=sha((ROOT/acquisition_path).read_bytes()),source_uri_base=acquisition['url'],source_root_text=source.text,source_head_tail=head.tail,raw_source_prolog=raw[:raw.index(b'<ThML>')].decode('utf-8'))
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
    bibl.append(tei_el('note',{'type':'retained-exact-source-prolog'},text=account['raw_source_prolog']))
    for record in account['features']:
        if record['source_tag']=='#comment':
            value='Retained source body administrative comment '+str(record['source_path'])+': '+json.dumps(dict(text=record['source_text'],tail=record['source_tail']),ensure_ascii=False,sort_keys=True)
            bibl.append(tei_el('note',{'type':'retained-source-body-comment','n':str(record['ordinal'])},text=value))
    for ordinal,marker in enumerate(account['source_prolog'],1):
        value='Retained source prolog '+str(ordinal)+': '+json.dumps(marker,ensure_ascii=False,sort_keys=True)
        bibl.append(tei_el('note',{'type':'retained-source-prolog','n':str(ordinal)},text=value))
    desc.append(bibl);fd.append(desc);header.append(fd);tei.extend([header,text])
    raw_tei=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
    source_sha=sha256(raw).hexdigest()
    lineage_path=Path('reports/_logs/watson-existing-install-20261003-v1/retained-producer-lineage.json')
    lineage_raw=(ROOT/lineage_path).read_bytes()
    if sha(lineage_raw)!='81e63614d2b7f6da1b83d2814a494a85364280e8cb7582a18ad1fc43e4122b6b':raise ValueError('Watson reviewed composite producer lineage drift')
    lineage=json.loads(lineage_raw)
    account['producer_lineage']=lineage
    source_ids={n.get('id') for n in source.find('ThML.body').iter() if isinstance(n.tag,str) and n.get('id')}
    navigation_gaps=[dict(source_xpath=source.getroottree().getpath(n),source_id=n.get('id'),attribute=k,value=n.get(k)) for n in source.find('ThML.body').iter() if isinstance(n.tag,str) for k in ('next','prev') if n.get(k) is not None and n.get(k) not in source_ids]
    account['source_navigation_gaps']=navigation_gaps
    legacy='All three existing Watson members derive from an explicitly qualified replay of the historical LIB035 producer. The replayed source-accountability bytes match the dated historical pin; replayed TEI bytes differ from the dated ticket pin. Every Watson source graph field, actual old carrier and original source reading is independently reconciled before readable hierarchy repair. The 46 prior Job correction proposals remain visible as qualified annotations, not replacements of the literal retained source readings. Their external witness readings are not independently confirmed from retained witness bytes.'
    historical_profile=json.loads((ROOT/'sources/commentaries/expositors-bible/lib035.reconstruction-profile.json').read_bytes())
    correction_rows=[r for r in historical_profile['text_corrections'] if r['member_id']==member_id]
    account['historical_text_corrections']=correction_rows
    account['historical_correction_disposition']='Literal raw source readings preserved in native body; prior proposals retained visibly and in accounting, external witness readings unconfirmed.'
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
        'Source stanza and line grouping, table summaries and cell alignment retain their exact native attributes. Judges and Ruth has no source xml:space declaration; Job and Numbers preserve the literal xml:space declaration. Source Scripture passage labels and commentary type remain explicit native attributes. Query/relative links preserve literal hrefs and per-ref xml:base from the exact acquisition URL. No source title typo or printed chapter-number discrepancy is corrected. The entire literal source prolog including XML declaration, remote DTD declaration where present, and stylesheet instructions remains visible in header notes; no external DTD is fetched.\n')
    readme+='\n## Prior correction proposals\n\nOriginal source readings are preserved in the native body. These inherited proposals are not independent confirmation of an external witness; external witness readings not independently confirmed.\n\n'+json.dumps(correction_rows,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    readme+='\nKnown source next/prev targets remain native links. The two absent toc targets per work remain exact typed annotations and unresolved source gaps. No generated toc target is invented. Judges and Ruth is one authored complete volume with two book parts, one title/contents sequence and shared indexes. Job and Numbers have separate authored title pages and refer to these as prior works; each remains one complete work. Shared material occurs once inside its owning work.\n'
    permission_path=Path('sources/commentaries/expositors-bible/ccel-permission.md')
    permission=(ROOT/permission_path).read_bytes()
    readme += '\n## Existing CCEL permission notice\n\nThe retained permission note states that parsing ThML/XML is permitted, CCEL copyright applies to its files and formatting, and CCEL files or derivatives of their formatting must not be sold. Attribution is appreciated; this deliverable uses sourced via CCEL.org. These retained statements do not establish current redistribution clearance.\n\nBound retained notice: '+permission_path.as_posix()+'; SHA-256 '+sha(permission)+'.\n\nLogical front/body/back allocation classifies source regions; Job Prologue, Numbers Introductory, chapters, and indexes all remain readable and source checked. Provider navigation and browser-only attributes remain exact in the reversible source ledger; native P5 does not claim browser/CSS pixel equivalence.\n'
    return {'content.tei.xml':raw_tei,'source-accountability.json':canonical(account),
            'README.source.md':readme.encode('utf-8')+b'\n\n## Exact retained permission record\n\n'+permission,
            'provenance.json':canonical(dict(status='nonaccepted',work_id=WORK,member_id=member_id,
                source_path=source_path,source_sha256=source_sha,source_bytes=len(raw),scope=SCOPE,
                legacy_basis=legacy,original_package_sha256=package.sha256,original_member_c14n_sha256=account['original_member_c14n_sha256'],source_uri_acquisition_path=acquisition_path.as_posix(),source_uri_acquisition_sha256=account['source_uri_acquisition_sha256'],source_uri_base=acquisition['url'],producer=dict(id='ocd-watson-retained-native-to-tei',version='1',implementation_path='build/tei/watson_retained_native_prepare.py',implementation_sha256=sha(Path(__file__).read_bytes()),emitter_path='build/tei/watson_retained_native_emitter.py',emitter_sha256=EMITTER_SHA,recipe='Exact acquired raw XML plus preserved historical six-member package; bounded existing-source native hierarchy reconstruction using declared member region and attribute policies'),permission_path=permission_path.as_posix(),permission_sha256=sha(permission),producer_lineage=account['producer_lineage'],emitter_sha256=EMITTER_SHA,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')),
            'unresolved.jsonl':canonical(dict(id=member_id+'-human-rights-print-assets',status='unresolved',detail=SCOPE,source_navigation_gaps=account['source_navigation_gaps'],broken_local_links=account['broken_local_links'],historical_correction_count=len(correction_rows)))}


def _convert(manifest: SourceManifest) -> dict[str,bytes]:
    manifest.verify()
    member_id=manifest.record['source_id'].removeprefix('ccel-watson-retained-native-').removesuffix('-v1')
    result=convert(member_id)
    if manifest.authority_path('retained-thml').read_bytes() != (ROOT/'raw/ccel/expositors-bible'/MEMBERS[member_id][0]).read_bytes():
        raise ValueError('Retained source binding differs')
    if result['README.source.md'] != manifest.authority_path('source-local-attribution-readme').read_bytes():
        raise ValueError('Visible source credit binding differs')
    return result


_convert.converter_id='ocd-watson-retained-native-to-tei'
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
