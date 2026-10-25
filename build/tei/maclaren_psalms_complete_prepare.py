"""Group the three existing Maclaren Psalms source packages without re-emitting text."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.reconstruction import SourceManifest, CandidatePackage
from ocd_kernel.tei.writer import tei_el

ROOT = Path(__file__).resolve().parents[2]
NS = '{http://www.tei-c.org/ns/1.0}'
XML = '{http://www.w3.org/XML/1998/namespace}'
WORK = 'expositors-bible--alexander-maclaren'
MEMBERS = tuple('maclaren-expositorpsalms'+str(i) for i in (1, 2, 3))
TITLE = "The Expositor's Bible: The Psalms"
STATUS = 'Nonaccepted complete authored work reconstructed from three already acquired CCEL electronic volumes. Human review, print collation, rights and publication remain separate.'

def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode('utf-8')

def convert(source: SourceManifest):
    source.verify()
    profile = json.loads(source.authority_path('complete-profile').read_bytes())
    if profile['ordered_members'] != list(MEMBERS):
        raise ValueError('Maclaren Psalms complete-work source order differs')
    roots = []
    packages = []
    for member in MEMBERS:
        package = CandidatePackage.load(source.authority_path(member+'-manifest').parent)
        package.verify_integrity()
        packages.append(package)
        roots.append(etree.fromstring(package.member_bytes('content.tei.xml')))
    root = tei_el('TEI', {'xml:id': 'maclaren-psalms-complete-work'})
    header = tei_el('teiHeader'); fd = tei_el('fileDesc'); ts = tei_el('titleStmt')
    ts.append(tei_el('title', text=TITLE))
    for role in ('author', 'editor'):
        values = [r.findtext(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+role) for r in roots]
        if not values[0] or len(set(values)) != 1:
            raise ValueError('Common Maclaren Psalms authorship differs')
        ts.append(tei_el(role, text=values[0]))
    fd.append(ts); pub = tei_el('publicationStmt'); pub.append(tei_el('p', text=STATUS)); fd.append(pub)
    desc = tei_el('sourceDesc'); outer = tei_el('listBibl')
    for member, component in zip(MEMBERS, roots, strict=True):
        records = tei_el('listBibl', {'xml:id': member+'-source-records'})
        records.append(tei_el('head', text=component.findtext(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+'title')))
        for node in component.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc'):
            records.append(deepcopy(node))
        outer.append(records)
    desc.append(outer); fd.append(desc); header.append(fd); root.append(header)
    text = tei_el('text', {'xml:lang': 'en'}); group = tei_el('group', {'xml:id': 'maclaren-psalms-source-volumes'})
    for member, component in zip(MEMBERS, roots, strict=True):
        volume = deepcopy(component.find(NS+'text'))
        if XML+'id' in volume.attrib:
            raise ValueError('Unexpected component text identity')
        volume.set(XML+'id', member); group.append(volume)
    text.append(group); root.append(text)
    readme = source.authority_path('complete-readme').read_bytes()
    accounting = dict(contract='ocd-maclaren-psalms-complete-accounting-v1', complete_works=1,
        source_volumes=3, ordered_members=list(MEMBERS), profile=profile,
        volume_accounting=[json.loads(p.member_bytes('source-accountability.json')) for p in packages],
        grouping='Each entire source text retained once in volume order; no invented Psalm regrouping or shared matter duplication.')
    provenance = dict(status='nonaccepted', work_id=WORK, complete_work=TITLE, source_profile=profile,
        converter=dict(source.record['converter']), source_manifest_sha256=source.sha256,
        human_acceptance='not_recorded', rights='unresolved', publication='not_ready')
    unresolved = dict(id='maclaren-psalms-complete-human-rights-print', status='unresolved', detail=STATUS)
    return {'content.tei.xml': etree.tostring(root, encoding='UTF-8', xml_declaration=True),
        'source-accountability.json': canonical(accounting), 'provenance.json': canonical(provenance),
        'README.source.md': readme, 'unresolved.jsonl': canonical(unresolved)}

convert.converter_id = 'ocd-maclaren-psalms-complete-group'
convert.converter_version = '1'
convert.implementation_path = Path(__file__).resolve()
