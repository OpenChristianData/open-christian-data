"""Reconcile one unchanged accepted Gutenberg work and its historical closeouts."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree, html
from ocd_kernel.library._common import io_path, io_glob
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work
from ocd_kernel.tei.install_accepted import _files

ROOT = Path(__file__).resolve().parents[2]
ID = 'barclay-apology-true-christian-divinity'
WORK = Path('library/works') / ID
OUT = Path('reports/_logs/barclay-apology-downstream-preflight-20261001')
def canonical(v):
    return (json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'))+'\n').encode()
def digest(p):
    return sha256(io_path(p).read_bytes()).hexdigest()
def main():
    paths = list(io_glob(ROOT/WORK, '**/acceptance.json'))
    if len(paths) != 1:
        raise ValueError('Expected one accepted complete work')
    acceptance = paths[0]
    a = _validate_acceptance_for_work(acceptance, root=ROOT, work_id=ID)
    source_path = Path(a['source']['source_path'])
    source = io_path(ROOT/source_path).read_bytes()
    if sha256(source).hexdigest() != a['source']['source_sha256']:
        raise ValueError('Retained source changed')
    native = html.fromstring(source)
    pre = native.xpath('//pre')[0]
    credits = ''.join(pre.itertext())
    for literal in ('Robert Barclay', 'Emmanuel Ackerman', 'Online Distributed', 'HathiTrust', 'Google', 'University of Michigan'):
        if literal not in credits:
            raise ValueError('Missing literal primary credit '+literal)
    title = native.xpath('//div[@class="chapter"]')[0]
    master = Path(a['promotion']['master']['path'])
    raw = io_path(ROOT/master).read_bytes()
    mr = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    ns = {'t':'http://www.tei-c.org/ns/1.0'}
    xmlid = '{http://www.w3.org/XML/1998/namespace}id'
    units = []
    for part in ('front','body','back'):
        for n in mr.xpath('/t:TEI/t:text/t:'+part+'/*', namespaces=ns):
            units.append(dict(part=part, tag=etree.QName(n).localname, id=n.get(xmlid), type=n.get('type'), c14n_sha256=sha256(etree.tostring(n,method='c14n')).hexdigest()))
    if len(units)!=25 or [sum(n['part']==p for n in units) for p in ('front','body','back')]!=[5,16,4]:
        raise ValueError('Complete accepted unit boundaries differ')
    bindings = {(WORK/Path(p)).as_posix():h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')}
    bindings[source_path.as_posix()] = sha256(source).hexdigest()
    def walk(v):
        if isinstance(v,dict):
            if all(k in v for k in ('path','sha256','bytes')):
                payload = io_path(ROOT/Path(v['path'])).read_bytes()
                if len(payload)!=v['bytes'] or sha256(payload).hexdigest()!=v['sha256']:
                    raise ValueError('Acceptance evidence differs '+v['path'])
                bindings[v['path']] = v['sha256']
            for x in v.values(): walk(x)
        elif isinstance(v,list):
            for x in v: walk(x)
    walk(a)
    prior = {}
    for folder in (Path('D:/Library/Open Christian Data/candidate-reviews/barclay-pg56487-direct-20260928-v1'),Path('D:/Library/Open Christian Data/candidate-reviews/l879-pg56487-technical-closeout-20261001')):
        for p in folder.iterdir():
            if p.is_file() and p.suffix in {'.json','.md','.py'}:
                prior[p.as_posix()] = digest(p)
    old_notices = ['sources/structured-text/'+ID+'/README.md', 'data/prose/'+ID+'/README.md']
    bindings.update({p:digest(ROOT/p) for p in old_notices})
    record = dict(status='accepted-authority-verified-downstream-gap', checked_at=datetime.now(timezone.utc).isoformat(), work_id=ID, acceptance_path=acceptance.relative_to(ROOT).as_posix(), accepted_master_path=master.as_posix(), accepted_master_sha256=sha256(raw).hexdigest(), accepted_master_bytes=len(raw), source_path=source_path.as_posix(), source_sha256=sha256(source).hexdigest(), source_bytes=len(source), current_authority_bindings=bindings, literal_primary_credits=[dict(locus='Gutenberg preformatted envelope',literal_text=credits),dict(locus='First chapter/title page',literal_text=''.join(title.itertext()))], ordered_master_units=units, master_text_c14n_sha256=sha256(etree.tostring(mr.find('t:text',ns),method='c14n')).hexdigest(), prior_technical_evidence=prior, prior_release_discovery=dict(scopes=['canonical work publication', 'reports/library,publish,runs,_logs', 'reports/clean-ready-acquisition-to-tei,source-to-tei', 'durable candidate-reviews and offline-releases', 'report-only selection/completion/release/offline/final/summary/result/report JSON and READMEs'],result='No work-bound private release found in accessible inspected scopes; L879 is source-to-TEI technical evidence, not downstream release.',qualification='Unrelated protected discovery folders were not entered; no exhaustive absence assertion across unreadable paths.'), old_notices_preserved=old_notices, external_contract_observed=dict(path='ocd_kernel/reconstruction/contract.py',sha256=digest(ROOT/'ocd_kernel/reconstruction/contract.py'),disposition='Current observed dependency only; historical reconstruction not invoked or resealed. Ordinary accepted native projection and private release do not invoke optional source-oracle package validation.'), scope='Complete existing retained English eighth-edition witness: five front units, sixteen body units including combined V–VI source group, four back units. Gutenberg license envelope remains retained raw/provenance outside TEI text.', reconstruction_performed=False,authority_change_required=False)
    out = io_path(ROOT/OUT); out.mkdir(parents=True,exist_ok=True)
    (out/'preflight.json').write_bytes(canonical(record))
    for name in ('barclay-release-discovery-search-errors-20261001.txt','barclay-release-candidate-discovery-search-errors-20261001.txt','barclay-release-group-discovery-search-errors-20261001.txt'):
        p=io_path(ROOT/'reports/_logs'/name)
        if p.exists(): p.rename(out/name)
    print(json.dumps(dict(status=record['status'],units=len(units),bindings=len(bindings),master=record['accepted_master_sha256'],source=record['source_sha256'])))
if __name__=='__main__':main()
