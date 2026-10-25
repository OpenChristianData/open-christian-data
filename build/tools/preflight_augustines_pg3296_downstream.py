"""Reconcile the distinct PG3296 accepted witness and bounded prior-release evidence."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from lxml import etree
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
from ocd_kernel.projection.categories.prose import project_accepted_prose,verify_accepted_prose
ROOT=Path(__file__).resolve().parents[2]
WORK=Path('library/works/augustines-confessions')
OUT=Path('reports/_logs/augustines-confessions-pg3296-downstream-preflight-20261001')
NS='{http://www.tei-c.org/ns/1.0}'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def main():
    paths=list(io_glob(ROOT/WORK,'**/acceptance.json'))
    if len(paths)!=1:raise ValueError('Not one accepted PG3296 edition')
    acceptance=paths[0]
    with cached_edition_lookups():
        a=validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
    if a['identity']['work_id']!='augustines-confessions':raise ValueError('Wrong canonical witness')
    master=Path(a['promotion']['master']['path']);raw=io_path(ROOT/master).read_bytes();tree=etree.fromstring(raw)
    source_path=Path(a['source']['source_path']);source=io_path(ROOT/source_path).read_bytes()
    if sha256(source).hexdigest()!=a['source']['source_sha256'] or len(source)!=632167:raise ValueError('Retained source differs')
    body=tree.find(NS+'text/'+NS+'body');books=[n.get('n') for n in body]
    if books!=['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII']:raise ValueError('Full 13-book master differs')
    parts=[dict(part=etree.QName(p).localname,units=[dict(type=n.get('type'),subtype=n.get('subtype'),n=n.get('n'),text=''.join(n.itertext())) for n in p]) for p in tree.find(NS+'text')]
    current={(WORK/Path(p)).as_posix():h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')};current[source_path.as_posix()]=sha256(source).hexdigest()
    def bound(v):
        if isinstance(v,dict):
            if all(k in v for k in ('path','sha256','bytes')):
                p=Path(v['path']);data=io_path(ROOT/p).read_bytes()
                if len(data)!=v['bytes'] or sha256(data).hexdigest()!=v['sha256']:raise ValueError('Bound accepted evidence differs '+str(p))
                current[p.as_posix()]=v['sha256']
            for item in v.values():bound(item)
        elif isinstance(v,list):
            for item in v:bound(item)
    bound(a)
    folders=[p for p in (ROOT/'reports/_logs').iterdir() if p.is_dir() and ('confess' in p.name or 'pg3296' in p.name or p.name.startswith('completion-wave-'))]
    files=[]
    for folder in folders:
        for name in ('**/completion.json','**/closeout.json','**/final-delivery.json','**/release-selection.json','**/selection.json'):
            files.extend(io_glob(folder,name))
    local=ROOT/WORK/'publication'
    if io_path(local).exists():
        files.extend(io_glob(local,'**/*.json'))
    evidence=[];matches=[]
    for path in sorted(set(files)):
        payload=io_path(path).read_bytes()
        if len(payload)>4_000_000:raise ValueError('Unexpected large closure receipt '+str(path))
        value=json.loads(payload);literal=b'augustines-confessions' in payload
        record=dict(path=path.relative_to(ROOT).as_posix(),sha256=sha256(payload).hexdigest(),bytes=len(payload),mentions_assigned_pg3296_work_id=literal)
        evidence.append(record)
        if literal:matches.append(record)
    if matches:raise ValueError('Prior exact PG receipt discovered; reconcile/reuse before release '+str(matches))
    alias=ROOT/'reports/_logs/augustine-confessions-offline-20261001/release/internal/release-selection.json';selection=json.loads(io_path(alias).read_bytes())
    if selection['items'][0]['item_id']!='augustine-confessions':raise ValueError('Prior CCEL distinction differs')
    runtime_paths=['schemas/v2/native-content.schema.json','ocd_kernel/projection/categories/prose.py','ocd_kernel/projection/categories/native_documents.py','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/reconstruction/contract.py']
    runtime={p:digest(ROOT/p) for p in runtime_paths}
    if runtime['ocd_kernel/reconstruction/contract.py']!='ee9fe78b88bfe68c04223a4273918e065b9bc2f5abbd002405eb7ae063c08ce9':raise ValueError('Reported current reconstruction dependency differs')
    with cached_edition_lookups():
        projection=project_accepted_prose(ROOT,acceptance_path=acceptance);errors=verify_accepted_prose(ROOT,acceptance_path=acceptance,rows=projection['rows'],receipt=projection['receipt'])
    if errors or projection['receipt']['authority']['master']['sha256']!=sha256(raw).hexdigest() or projection['receipt']['master_sha256']!=sha256(raw).hexdigest():raise ValueError(errors or 'Not actual whole-master normal route')
    if {p:digest(ROOT/p) for p in runtime_paths}!=runtime:raise ValueError('Runtime changed during read-only route checks')
    out=io_path(ROOT/OUT);out.mkdir(parents=True,exist_ok=True)
    (out/'read-only-actual-master-projection.json').write_bytes(canonical(projection))
    record=dict(status='distinct-pg3296-accepted-authority-and-route-pass-no-prior-completion-found',checked_at=datetime.now(timezone.utc).isoformat(),work_id='augustines-confessions',source_path=source_path.as_posix(),source_sha256=sha256(source).hexdigest(),source_bytes=len(source),accepted_master_path=master.as_posix(),accepted_master_sha256=sha256(raw).hexdigest(),accepted_master_bytes=len(raw),acceptance_path=acceptance.relative_to(ROOT).as_posix(),current_authority_bindings=current,books=books,master_text_part_units=[dict(part=p['part'],units=[{k:v for k,v in n.items() if k!='text'} for n in p['units']]) for p in parts],source_header_excerpt=source.decode('utf-8-sig').split('*** START OF THE PROJECT GUTENBERG EBOOK')[0],source_license_text=''.join(tree.xpath(".//t:back/t:div[@subtype='project-gutenberg-license']//text()",namespaces={'t':NS[1:-1]})),prior_search=dict(canonical_publication_exists=io_path(local).exists(),bounded_report_folders=[p.relative_to(ROOT).as_posix() for p in folders],receipt_inventory=evidence,exact_assigned_id_matches=matches,limitation='Bounded work-name and current completion-wave reconciliation, not a claim about every historical artifact.'),distinct_completed_ccel_witness=dict(work_id='augustine-confessions',selection_path=alias.relative_to(ROOT).as_posix(),selection_sha256=digest(alias),acceptance_path=selection['items'][0]['acceptance_path'],source='retained CCEL npnf101 electronic witness; separate existing identity and translation'),runtime_bindings=runtime,dated_reconstruction_dependency_qualification='Historical accepted reconstruction/source/oracle receipts remain unchanged and dated. Current contract.py is only observed and pinned for downstream runtime; no old manifest or attestation is re-sealed and no new reconstruction/replay is claimed.',public_rows=len(projection['rows']),public_characters=sum(len(r['text']) for r in projection['rows']),independent_projection_errors=errors,actual_master_and_receipt_hash_equal=True,source_reconstruction_performed=False,canonical_authority_changed=False)
    (out/'preflight.json').write_bytes(canonical(record));print(json.dumps(dict(status=record['status'],source=record['source_sha256'],master=record['accepted_master_sha256'],rows=record['public_rows'],characters=record['public_characters'],source_books=len(books),current_bindings=len(current),prior_receipts=len(evidence),matching_pg_receipts=len(matches))))
if __name__=='__main__':main()
