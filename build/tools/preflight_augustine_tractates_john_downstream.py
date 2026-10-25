"""Read-only primary-credit and current-accepted-authority reconciliation for one work."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.install_accepted import _files
ROOT=Path(__file__).resolve().parents[2]
WORK=Path('library/works/augustine-tractates-on-john')
OUT=Path('reports/_logs/augustine-tractates-on-john-downstream-preflight-20261001')
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def main():
    acceptances=list(io_glob(ROOT/WORK,'**/acceptance.json'))
    if len(acceptances)!=1:raise ValueError('not one accepted work')
    acceptance=acceptances[0]
    with cached_edition_lookups():
        a=validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
    if a['identity']['work_id']!='augustine-tractates-on-john':raise ValueError('identity differs')
    source_path=Path(a['source']['source_path']);source=io_path(ROOT/source_path).read_bytes()
    if sha256(source).hexdigest()!=a['source']['source_sha256']:raise ValueError('source differs')
    sr=etree.fromstring(source,etree.XMLParser(huge_tree=True,resolve_entities=False,no_network=True));selected=sr.xpath("ThML.body/div1[@id='iii']")
    if len(selected)!=1:raise ValueError('native root is not unique')
    selected=selected[0];units=list(selected)
    if len(units)!=125 or any(n.tag!='div2' for n in units):raise ValueError('native divisions differ')
    print(ascii(etree.tostring(units[0],encoding='unicode')))
    print(ascii(etree.tostring(sr.find('ThML.head/electronicEdInfo'),encoding='unicode')))
    master=Path(a['promotion']['master']['path']);raw=io_path(ROOT/master).read_bytes()
    bindings={(WORK/Path(p)).as_posix():h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
    bindings[source_path.as_posix()]=sha256(source).hexdigest();bindings['docs/sources/ccel-permission.md']=sha256((ROOT/'docs/sources/ccel-permission.md').read_bytes()).hexdigest()
    def binding_walk(v):
        if isinstance(v,dict):
            if all(k in v for k in ('path','sha256','bytes')):
                path=Path(v['path']);payload=io_path(ROOT/path).read_bytes()
                if len(payload)!=v['bytes'] or sha256(payload).hexdigest()!=v['sha256']:raise ValueError('bound evidence differs '+str(path))
                bindings[path.as_posix()]=v['sha256']
            for value in v.values():binding_walk(value)
        elif isinstance(v,list):
            for value in v:binding_walk(value)
    binding_walk(a)
    header=sr.find('ThML.head');dc=header.find('electronicEdInfo/DC')
    own_title=''.join(units[0].itertext())
    literal_credits=[dict(source_xpath="ThML.body/div1[@id='iii']/div2[1]",literal_text=own_title),dict(source_xpath='ThML.head',literal_text=''.join(header.itertext()))]
    source_data=dict(source_sha256=sha256(source).hexdigest(),selected_title=selected.get('title'),source_elements=sum(1 for _ in selected.iter()),direct_divisions=[dict(id=n.get('id'),title=n.get('title'),elements=sum(1 for _ in n.iter())) for n in units],electronic_created=[dict(attributes=dict(n.attrib),text=n.text) for n in dc.findall('DC.Date')],rights=[dict(attributes=dict(n.attrib),text=n.text) for n in dc.findall('DC.Rights')],electronic_contributors=[dict(attributes=dict(n.attrib),text=n.text) for n in dc.findall('DC.Contributor')])
    prior={}
    for directory in (ROOT/WORK/'publication',ROOT/'reports/_logs'):
        if directory.name=='publication':paths=list(io_glob(directory,'**/*completion*.json')) if io_path(directory).exists() else []
        else:paths=list(io_glob(directory,'augustine-tractates-on-john*/**/completion.json'))
        for path in paths:prior[path.as_posix()]=sha256(io_path(path).read_bytes()).hexdigest()
    record=dict(status='accepted-authority-verified-downstream-missing',checked_at=datetime.now(timezone.utc).isoformat(),work_id='augustine-tractates-on-john',acceptance_path=acceptance.relative_to(ROOT).as_posix(),accepted_master_path=master.as_posix(),accepted_master_sha256=sha256(raw).hexdigest(),accepted_master_bytes=len(raw),source_path=source_path.as_posix(),source_sha256=sha256(source).hexdigest(),source_xpath="ThML.body/div1[@id='iii']",current_authority_bindings=bindings,literal_primary_credits=literal_credits,source_facts=source_data,prior_closeouts=prior,canonical_publication_exists=io_path(ROOT/WORK/'publication').exists(),source_reconstruction_performed=False,master_or_metadata_changed=False)
    out=io_path(ROOT/OUT);out.mkdir(parents=True,exist_ok=True);(out/'preflight.json').write_bytes(canonical(record));print(json.dumps(dict(status=record['status'],master=record['accepted_master_sha256'],source=record['source_sha256'],source_elements=source_data['source_elements'],units=source_data['direct_divisions'],bindings=len(bindings),prior=prior)))
if __name__=='__main__':main()
