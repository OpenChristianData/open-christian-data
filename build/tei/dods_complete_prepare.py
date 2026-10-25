"""Three complete Dods works from four existing sources; John contains both volumes."""
from pathlib import Path
from hashlib import sha256
from copy import deepcopy
import json
from lxml import etree
from ocd_kernel.tei.writer import tei_el
from ocd_kernel.reconstruction import SourceManifest,reconstruct

ROOT=Path(__file__).resolve().parents[2]
LOG=Path('reports/_logs/dods-existing-install-20261003-v1')
SOURCE_DIR=Path('sources/commentaries/expositors-bible/dods-complete-work-20261003-v2')
WORK='expositors-bible--marcus-dods'
WORKS={'dods-genesis':('dods-expositor1',),'dods-first-corinthians':('dods-expositor1cor',),'dods-gospel-john':('dods-expositorjohn1','dods-expositorjohn2')}
NS='{http://www.tei-c.org/ns/1.0}';XML='{http://www.w3.org/XML/1998/namespace}'

def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def sha(raw):return sha256(raw).hexdigest()
def boundary():return json.loads((ROOT/LOG/'complete-work-boundary-report-v2.json').read_bytes())

def component_convert(member):
    record=json.loads((ROOT/LOG/'source-component-conservation.json').read_bytes())
    if record['status']!='pass' or record['source_count']!=4 or record['complete_work_count']!=3:raise ValueError('Conserved source component scope differs')
    for pin in record['codepins']:
        if sha((ROOT/pin['path']).read_bytes())!=pin['sha256']:raise ValueError('Source component exercised code drifted')
    entry=next(r for r in record['members'] if r['member_id']==member)
    result={r['name']:(ROOT/entry['directory']/r['name']).read_bytes() for r in entry['files']}
    if set(result)!={'content.tei.xml','source-accountability.json','provenance.json','README.source.md','unresolved.jsonl'}:raise ValueError('Source component artifact set differs')
    for pin in entry['files']:
        if len(result[pin['name']])!=pin['bytes'] or sha(result[pin['name']])!=pin['sha256']:raise ValueError('Conserved source component bytes drifted')
    return result

def convert(key):
    if key not in WORKS:raise ValueError('Unknown existing complete Dods work')
    report=boundary();classification=next(r for r in report['classification'] if r['complete_work_id']==key)
    if tuple(classification['source_members'])!=WORKS[key] or report['complete_work_count']!=3 or report['acquired_source_count']!=4:raise ValueError('Complete work/source boundary differs')
    components={m:component_convert(m) for m in WORKS[key]}
    roots={m:etree.fromstring(p['content.tei.xml']) for m,p in components.items()}
    if len(roots)==1:
        tei=deepcopy(next(iter(roots.values())));tei.set(XML+'id',key)
    else:
        first,second=roots.values();titles=[n.findtext(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+'title') for n in roots.values()]
        title=titles[0].removesuffix(', Volume I')
        if titles[1]!=title+', Volume II':raise ValueError('John common primary title differs')
        tei=tei_el('TEI',{'xml:id':key});header=tei_el('teiHeader');fd=tei_el('fileDesc');ts=tei_el('titleStmt')
        ts.append(tei_el('title',text=title))
        for field in ('author','editor'):
            values=[n.findtext(NS+'teiHeader/'+NS+'fileDesc/'+NS+'titleStmt/'+NS+field) for n in roots.values()]
            if len(set(values))!=1:raise ValueError('John primary author/editor differs')
            ts.append(tei_el(field,text=values[0]))
        fd.append(ts);fd.append(deepcopy(first.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'publicationStmt')))
        desc=tei_el('sourceDesc');scope=tei_el('bibl');scope.append(tei_el('note',{'type':'complete-work-scope'},text=report['schema_bound_acquisition']['source_scope']));desc.append(scope)
        for member,root in roots.items():
            old=root.find(NS+'teiHeader/'+NS+'fileDesc/'+NS+'sourceDesc');bibls=old.findall(NS+'bibl')
            if len(bibls)!=2:raise ValueError('Complete retained component metadata expected')
            bibl=deepcopy(bibls[1]);bibl.set(XML+'id',member+'-source');bibl.set('type','retained-source-volume')
            bibl.insert(0,deepcopy(bibls[0][0]));desc.append(bibl)
        fd.append(desc);header.append(fd);tei.append(header)
        text=tei_el('text',{'xml:lang':'en'});group=tei_el('group',{'xml:id':key+'-volumes'})
        for member,root in roots.items():
            volume=deepcopy(root.find(NS+'text'));volume.set(XML+'id',member+'-volume');group.append(volume)
        text.append(group);tei.append(text)
    raw_tei=etree.tostring(tei,encoding='UTF-8',xml_declaration=True)
    # Parse the actual serialized document before sealing; no QName context assumption.
    etree.fromstring(raw_tei)
    component_account={m:json.loads(p['source-accountability.json']) for m,p in components.items()}
    component_provenance={m:json.loads(p['provenance.json']) for m,p in components.items()}
    records={m:[dict(name=n,bytes=len(p[n]),sha256=sha(p[n])) for n in sorted(p)] for m,p in components.items()}
    account=dict(contract='ocd-dods-complete-work-accounting-v1',work_id=WORK,complete_work_id=key,source_members=list(WORKS[key]),complete_work_count=3,acquired_source_count=4,boundary=classification,components=component_account,component_payloads=records,body_disposition='Single-source works retain complete native text. John retains exactly two ordered complete volume text trees; only synthetic volume text XML IDs are added. Serialized actual group is independently checked against both complete raw-source inverses.')
    provenance=dict(contract='ocd-dods-complete-work-provenance-v1',status='nonaccepted',work_id=WORK,complete_work_id=key,source_members=list(WORKS[key]),boundary_report_path=(LOG/'complete-work-boundary-report-v2.json').as_posix(),boundary_report_sha256=sha((ROOT/LOG/'complete-work-boundary-report-v2.json').read_bytes()),producer_recipe_sha256=sha(Path(__file__).read_bytes()),oracle_sha256=sha((ROOT/'build/tei/dods_complete_oracle.py').read_bytes()),component_provenance=component_provenance,component_payloads=records,human_acceptance='not_recorded',rights='unresolved',publication='not_ready')
    readme=(f'# Complete retained work: {key}\n\n{classification["boundary"]}\n\nOne candidate TEI represents this complete electronic work. Three complete works account for the four already acquired Dods source files; no new source was acquired. Human acceptance, print collation, rights and publication remain separate.\n\n').encode('utf-8')
    if len(components)>1:readme+=(report['schema_bound_acquisition']['source_scope']+'\n\nEach volume retains its complete front/body/back tree and distinct source metadata. The original per-volume acquired URLs remain the literal reference bases; no cross-volume destinations are invented.\n\n').encode('utf-8')
    for m,p in components.items():readme+=('## Retained source component: '+m+'\n\n').encode()+p['README.source.md']+b'\n'
    unresolved=b''
    for m,p in components.items():
        for line in p['unresolved.jsonl'].splitlines():
            row=json.loads(line);row['source_member_id']=m;unresolved+=canonical(row)
    return dict(zip(('content.tei.xml','source-accountability.json','provenance.json','README.source.md','unresolved.jsonl'),(raw_tei,canonical(account),canonical(provenance),readme,unresolved)))

def _convert(manifest:SourceManifest):
    manifest.verify();key=manifest.record['scope']['complete_work_id']
    result=convert(key)
    if result['README.source.md']!=manifest.authority_path('source-local-attribution-readme').read_bytes():raise ValueError('Complete source credit authority differs')
    return result
_convert.converter_id='ocd-dods-three-complete-existing-works-to-tei'
_convert.converter_version='1'
_convert.implementation_path=Path(__file__).resolve()

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);p.add_argument('--source-manifest',type=Path);a=p.parse_args()
    if a.source_manifest:print(reconstruct(SourceManifest.load(a.source_manifest,repository_root=ROOT),a.destination,_convert).sha256)
    else:
        for key in WORKS:
            out=a.destination/key;out.mkdir(parents=True,exist_ok=True)
            for name,raw in convert(key).items():(out/name).write_bytes(raw)
if __name__=='__main__':main()
