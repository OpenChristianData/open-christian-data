"""Repair Plummer's existing retained electronic witnesses using the frozen emitter."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from build.tei.plummer_retained_native_emitter import emit_text
from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el

from build.tei.plummer_retained_scope import ROOT, LOG, WORK_ID, OLD_PACKAGE, MEMBERS as SPECS, retained
WORK = WORK_ID
SOURCE_DIR = Path('sources/commentaries/expositors-bible/plummer-retained-install-20261003-v1')
EMITTER_SHA = 'a14b997922b3d3a2486df617446702bf85f3dde6caf454593292de51fa20e00f'
MEMBERS = {member:(Path(spec['path']).name,tuple(spec['front']),tuple(spec['back'])) for member,spec in SPECS.items()}

def sha(raw):
 return sha256(raw).hexdigest()
SCOPE = ('Complete retained CCEL electronic volume, including every original introductory chapter, commentary part, printed and generated index, note and table; exactly one of the two already acquired Plummer editions. '
         'Human review, print collation, rights clearance and publication remain separate. No new source or image acquisition.')

def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))+'\n').encode('utf-8')


def convert(member_id: str) -> dict[str, bytes]:
    if member_id not in MEMBERS:
        raise ValueError('Unknown existing Plummer witness')
    if sha256((ROOT/'build/tei/ccel_retained_native_emitter.py').read_bytes()).hexdigest() != EMITTER_SHA:
        raise ValueError('Frozen CCEL emitter changed')
    filename,front,back=MEMBERS[member_id]
    source_path='raw/ccel/expositors-bible/'+filename
    raw=retained(member_id)
    source=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    head=source.find('ThML.head')
    if head is None: raise ValueError('Complete source head required')
    text,account=emit_text(raw,member_id=member_id,front_ids=front,back_ids=back)
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
    desc.append(bibl);fd.append(desc);header.append(fd);tei.extend([header,text])
    raw_tei=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
    source_sha=sha256(raw).hexdigest()
    legacy='Existing historical LIB-033 flat-feature TEI, complete feature graph and exact encoded downloaded witness are retained and independently reconciled before readable hierarchy repair.'
    readme=(f'# Retained source: {title}\n\nSourced via CCEL.org.\n\n'
        f'Retained authority: {source_path}; SHA-256 {source_sha}; {len(raw)} bytes.\n\n'
        f'Primary source author: {author}. Series editor: {editor}.\n\n'
        f'Literal source printed-edition statement: {head.findtext(".//published")}.\n\n'
        f'Literal DC.Rights: {head.findtext(".//DC.Rights") or "[empty in retained source]"}. '
        'This is the source statement, not a rights clearance. CCEL file formatting and attribution conditions require release review. Copies of CCEL-produced electronic files must not be sold, and published excerpts must attribute CCEL.org, as recorded in the retained permission evidence.\n\n'
        'Copyright Christian Classics Ethereal Library is preserved as a source notice where present; source metadata, literal CSS and stylesheet directives are retained in visible header notes and source accounting.\n\n'
        f'{legacy}\n\n{SCOPE}\n\n'
        'Generated administrative index comments retain exact fields and positions in source accounting; their whitespace-only tails are joined in actual TEI. All readable source index content and directives remain in order. '
        'HTML tbody has no TEI carrier: intact rows remain in their owning table, with wrapper fields and whitespace accounted. Source h1 through h6 are explicit source-level heading paragraphs, preserving exact order.\n\n'
        'Pastoral table th cells retain their source header role as TEI cell role=label with exact spans. The two source-locus P5 adaptations preserve the mixed l/prose stanza and Greek index ownership exactly. Relative query links retain literal targets and the original acquired CCEL HTML URL as per-ref XML base, preserving URI context. Both complete source envelopes contain no image elements; no graphics are acquired or inferred.\n')
    return {'content.tei.xml':raw_tei,'source-accountability.json':canonical(account),
            'README.source.md':readme.encode('utf-8'),
            'provenance.json':canonical(dict(status='nonaccepted',work_id=WORK,member_id=member_id,
                source_path=source_path,source_sha256=source_sha,source_bytes=len(raw),scope=SCOPE,
                legacy_basis=legacy,emitter_ancestor_sha256=EMITTER_SHA,
                emitter_sha256=sha256((ROOT/'build/tei/plummer_retained_native_emitter.py').read_bytes()).hexdigest(),
                human_acceptance='not_recorded',rights='unresolved',publication='not_ready')),
            'unresolved.jsonl':canonical(dict(id=member_id+'-human-rights-print-assets',status='unresolved',detail=SCOPE))}


def _convert(manifest: SourceManifest) -> dict[str,bytes]:
    manifest.verify()
    member_id=manifest.record['source_id'].removeprefix('ccel-plummer-retained-native-').removesuffix('-v1')
    result=convert(member_id)
    if manifest.authority_path('retained-thml').read_bytes() != (ROOT/'raw/ccel/expositors-bible'/MEMBERS[member_id][0]).read_bytes():
        raise ValueError('Retained source binding differs')
    if result['README.source.md'] != manifest.authority_path('source-local-attribution-readme').read_bytes():
        raise ValueError('Visible source credit binding differs')
    return result


_convert.converter_id='ocd-plummer-retained-native-to-tei'
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
