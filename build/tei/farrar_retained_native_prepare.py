"""Repair Farrar's existing retained electronic witnesses using the frozen emitter."""
from __future__ import annotations

from hashlib import sha256
from functools import lru_cache
import base64
import json
from pathlib import Path

from lxml import etree

from build.tei.farrar_retained_native_emitter import emit_text
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage,reconstruct
from ocd_kernel.tei.writer import tei_el

ROOT = Path(__file__).resolve().parents[2]
WORK = 'expositors-bible--frederic-w-farrar'
WORK_ID = WORK
LOG = Path('reports/_logs/farrar-existing-install-20261003-v1')
SOURCE_DIR = Path('sources/commentaries/expositors-bible/farrar-retained-install-20261003-v1')
OLD_PACKAGE = LOG/'retained-final-package'
EMITTER_SHA = '5510555027c985b8c36e7851e9b39814f4e4be56f0fb1dd42dcb82a3b8789c4c'
MEMBERS = {
    'farrar-expositor1kings': ('farrar_expositor1kings.xml', ('i','ii'), ('vii','viii')),
    'farrar-expositor2kings': ('farrar_expositor2kings.xml', ('i','ii'), ('xliii','xliv','xlv','xlvi','xlvii')),
    'farrar-expositordan': ('farrar_expositordan.xml', ('i','ii'), ('vi','vii')),
}
SPECS = {}
for _member, _filename, _pin, _size, _elements, _body in [
 ('farrar-expositor1kings','farrar_expositor1kings.xml','b5bb6a2200528b3d3573aa373eaec2f7a827c1057b462c5d473eb231e812ca8d',1187151,7024,6940),
 ('farrar-expositor2kings','farrar_expositor2kings.xml','1827452772153d95bb8f5c8c56782b4b038b51f335e6339b2ac8e241dc7267fa',1295251,9002,8915),
 ('farrar-expositordan','farrar_expositordan.xml','6a851a9f4c0bf941745ce28b8a0c0da9b15f3a6568c089511b66d8bc10d1a67b',945183,7579,7481)]:
 SPECS[_member]=dict(path='raw/ccel/expositors-bible/'+_filename,sha256=_pin,bytes=_size,elements=_elements,body_elements=_body,
  form=WORK+'--'+_member+'--retained-en',edition=WORK+'--'+_member+'--ccel-electronic',acquisition=WORK+'--'+_member+'--acquired')

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
    if package.sha256!='a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2' or sha(package.member_bytes('content.tei.xml'))!='2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134':raise ValueError('Exact Farrar historical package changed')
    return package,etree.fromstring(package.member_bytes('content.tei.xml')),json.loads(package.member_bytes('source-accountability.json'))


def convert(member_id: str) -> dict[str, bytes]:
    if member_id not in MEMBERS:
        raise ValueError('Unknown existing Farrar witness')
    if sha256((ROOT/'build/tei/farrar_retained_native_emitter.py').read_bytes()).hexdigest() != EMITTER_SHA:
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
    if acquisition['source_path']!=source_path or acquisition['source_sha256']!=sha(raw):raise ValueError('Farrar acquired source URI context changed')
    package,original,old_account=historical()
    if base64.b64decode(old_account['retained_source_bytes'][member_id]['base64'],validate=True)!=raw:raise ValueError('Historical Farrar source bytes do not match acquired witness')
    original_member=original.xpath('//*[@xml:id=$id]',namespaces={'xml':'http://www.w3.org/XML/1998/namespace'},id=member_id)
    if len(original_member)!=1:raise ValueError('Unique historical Farrar member required')
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
    legacy='All three existing Farrar members are recovered from the exact historical LIB-033 package. Their flat feature representation requires the present source-backed readable hierarchy repair; original package and raw witness bytes remain exact.'
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
        'Eight source preformatted genealogical/chronological carriers across this three-member work retain their exact text, inline children and xml:space semantics as ab rend="source-preformatted". Source Scripture passage labels and commentary type remain explicit native attributes. Query/relative links preserve literal hrefs and per-ref xml:base from the exact acquisition URL. No source title typo or printed chapter-number discrepancy is corrected. The entire literal source prolog including XML declaration, remote DTD declaration where present, and stylesheet instructions remains visible in header notes; no external DTD is fetched.\n')
    permission_path=Path('sources/commentaries/expositors-bible/ccel-permission.md')
    permission=(ROOT/permission_path).read_bytes()
    readme += '\n## Existing CCEL permission notice\n\nThe retained permission note states that parsing ThML/XML is permitted, CCEL copyright applies to its files and formatting, and CCEL files or derivatives of their formatting must not be sold. Attribution is appreciated; this deliverable uses sourced via CCEL.org. These retained statements do not establish current redistribution clearance.\n\nBound retained notice: '+permission_path.as_posix()+'; SHA-256 '+sha(permission)+'.\n\nLogical front/body/back allocation classifies source regions; chronology notes, appendices, introductions, and indexes all remain readable and source checked. Provider navigation and browser-only attributes remain exact in the reversible source ledger; native P5 does not claim browser/CSS pixel equivalence.\n'
    return {'content.tei.xml':raw_tei,'source-accountability.json':canonical(account),
            'README.source.md':readme.encode('utf-8'),
            'provenance.json':canonical(dict(status='nonaccepted',work_id=WORK,member_id=member_id,
                source_path=source_path,source_sha256=source_sha,source_bytes=len(raw),scope=SCOPE,
                legacy_basis=legacy,original_package_sha256=package.sha256,original_member_c14n_sha256=account['original_member_c14n_sha256'],source_uri_acquisition_path=acquisition_path.as_posix(),source_uri_acquisition_sha256=account['source_uri_acquisition_sha256'],source_uri_base=acquisition['url'],producer=dict(id='ocd-farrar-retained-native-to-tei',version='1',implementation_path='build/tei/farrar_retained_native_prepare.py',implementation_sha256=sha(Path(__file__).read_bytes()),emitter_path='build/tei/farrar_retained_native_emitter.py',emitter_sha256=EMITTER_SHA,recipe='Exact acquired raw XML plus preserved historical six-member package; bounded existing-source native hierarchy reconstruction using declared member region and attribute policies'),permission_path=permission_path.as_posix(),permission_sha256=sha(permission),emitter_sha256=EMITTER_SHA,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')),
            'unresolved.jsonl':canonical(dict(id=member_id+'-human-rights-print-assets',status='unresolved',detail=SCOPE))}


def _convert(manifest: SourceManifest) -> dict[str,bytes]:
    manifest.verify()
    member_id=manifest.record['source_id'].removeprefix('ccel-farrar-retained-native-').removesuffix('-v1')
    result=convert(member_id)
    if manifest.authority_path('retained-thml').read_bytes() != (ROOT/'raw/ccel/expositors-bible'/MEMBERS[member_id][0]).read_bytes():
        raise ValueError('Retained source binding differs')
    if result['README.source.md'] != manifest.authority_path('source-local-attribution-readme').read_bytes():
        raise ValueError('Visible source credit binding differs')
    return result


_convert.converter_id='ocd-farrar-retained-native-to-tei'
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
