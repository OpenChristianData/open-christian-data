"""Read-only source/installed lineage assessment for the complete Isaiah work."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from ocd_kernel.reconstruction import CandidatePackage

ROOT=Path(__file__).resolve().parents[2]
WORK='expositors-bible--george-adam-smith'
MEMBERS=('smith-ga-expositorisa1','smith-ga-expositorisa2')
LOG=Path('reports/_logs/smith-isaiah-complete-20261003-v1')
OLD=Path('reports/_logs/smith-existing-install-20261003-v1')
NS='{http://www.tei-c.org/ns/1.0}'
XML='{http://www.w3.org/XML/1998/namespace}'

def sha(raw):return sha256(raw).hexdigest()
def canonical(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def pin(path):
    raw=(ROOT/path).read_bytes();return dict(path=path.as_posix(),sha256=sha(raw),bytes=len(raw))
def fields(tree):return [(n.tag,dict(n.attrib),n.text,n.tail,len(n)) for n in tree.iter()]
def write(path,value):
    p=ROOT/path
    if p.exists():raise FileExistsError('Preserve prior evidence: '+str(p))
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(value))

def main():
    prior=json.loads((ROOT/OLD/'parent-installed-generation-readback.json').read_bytes())
    current={p:sha((ROOT/'library/works'/WORK/p).read_bytes()) for p in prior['installed_files']}
    if current!=prior['installed_files']:raise ValueError('Prior installed complete generation changed')
    rows=[]
    for pos,m in enumerate(MEMBERS,1):
        filename='smith_ga_expositorisa'+str(pos)+'.xml';sp=Path('raw/ccel/expositors-bible')/filename
        raw=(ROOT/sp).read_bytes();source=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
        h=source.find('ThML.head');b=source.find('ThML.body');title=h.findtext('.//DC.Title')
        form=WORK+'--'+m+'--retained-en';edition=WORK+'--'+m+'--ccel-electronic';ep=Path('library/works')/WORK/'forms'/form/'editions'/edition
        ap=ep/'acquisitions'/(WORK+'--'+m+'--acquired.json');acq=json.loads((ROOT/ap).read_bytes())
        if acq['source_path']!=sp.as_posix() or acq['source_sha256']!=sha(raw) or acq['source_bytes']!=len(raw):raise ValueError('Original acquired source differs')
        package_path=Path('library/works')/WORK/'integration/smith-retained-current-20261003-v1'/m/'inputs/package'
        package=CandidatePackage.load(ROOT/package_path);package.verify_integrity()
        pt=ET.fromstring(package.member_bytes('content.tei.xml'));mt=ET.fromstring((ROOT/ep/'master.tei.xml').read_bytes())
        if fields(pt.find(NS+'text'))!=fields(mt.find(NS+'text')):raise ValueError('Installed complete native envelope differs from source-checked package')
        front=b.find('div1');page=[dict(tag=n.tag,attributes=dict(n.attrib),text=''.join(n.itertext())) for n in front.iter() if isinstance(n.tag,str) and n.tag in {'p','h1','h2','h3','h4','h5','h6'}]
        both=[r for r in page if 'IN TWO VOLUMES' in r['text'].upper()]
        label=[r for r in page if ('VOL. I.' if pos==1 else 'VOL. II.') in r['text'].upper()]
        if not both or not label or title!="The Expositor's Bible: The Book of Isaiah, Volume "+('I','II')[pos-1]:raise ValueError('Primary complete-work/volume order differs')
        relative=[dict(id=n.get('id'),href=n.get('href')) for n in b.iter('a') if n.get('href') and not n.get('href').startswith('#') and not urlsplit(n.get('href')).scheme]
        rows.append(dict(member_id=m,position=pos,source=pin(sp),source_title=title,source_print_statement=h.findtext('.//published'),source_url=acq['url'],acquisition=pin(ap),master=pin(ep/'master.tei.xml'),acceptance=pin(ep/'acceptance.json'),package=package_path.as_posix(),package_sha256=package.sha256,package_files=[pin(package_path/n) for n in sorted(package.member_names)],whole_elements=sum(isinstance(n.tag,str) for n in source.iter()),body_elements=sum(isinstance(n.tag,str) for n in b.iter()),body_roles=dict(sorted(Counter(n.tag for n in b.iter() if isinstance(n.tag,str)).items())),comments=sum(n.tag is ET.Comment for n in source.iter()),primary_two_volume_fields=both,primary_volume_label_fields=label,top_level_source_order=[dict(id=n.get('id'),title=n.get('title')) for n in b if isinstance(n.tag,str)],relative_links=relative,document_prefix=raw[:raw.index(b'<ThML')].decode('utf-8'),complete_native_volume_conserved=True))
    report=dict(contract='ocd-smith-isaiah-existing-complete-scope-v1',status='pass',work_id=WORK,complete_work_id='smith-ga-isaiah-complete',complete_works=1,source_volumes=2,source_bytes=sum(r['source']['bytes'] for r in rows),whole_elements=sum(r['whole_elements'] for r in rows),body_elements=sum(r['body_elements'] for r in rows),ordered_members=list(MEMBERS),volumes=rows,boundary='The authored Book of Isaiah is explicitly in two volumes: I Isaiah I–XXXIX and II Isaiah XL–LXVI. Both entire retained electronic envelopes belong to one complete work. Distinct Volume I London1910/Twentieth Edition and Volume II London1890 statements remain separate witnesses, not a claim of one printed edition.',shared_material='Each source front/body/back, title matter, contents, appendices/indexes and notes stays in its source volume exactly once; no deduplication or invented cross-volume target.',excluded='Twelve Prophets Volume I is a separate authored work and explicitly partial in this two-source subtask.',canonical_files_before=current,parent_readback=pin(OLD/'parent-installed-generation-readback.json'),permission=pin(Path('sources/commentaries/expositors-bible/ccel-permission.md')),canonical_changes=False,raw_source_fidelity='Next independent actual aggregate oracle; package/master text conservation alone is not raw source proof.')
    write(LOG/'existing-complete-scope-assessment.json',report)
    print(json.dumps(dict(status='pass',sources=2,source_bytes=report['source_bytes'],whole_elements=report['whole_elements'],body_elements=report['body_elements'],relative_links=sum(len(r['relative_links']) for r in rows),report_sha256=sha((ROOT/LOG/'existing-complete-scope-assessment.json').read_bytes()))))
if __name__=='__main__':main()
