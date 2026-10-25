"""Read-only reconciliation of the existing PG38326 accepted Bede witness."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from lxml import etree,html
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files
ROOT=Path(__file__).resolve().parents[2]
WORK=Path('library/works/bede-ecclesiastical-history-of-england')
OUT=Path('reports/_logs/bede-pg38326-downstream-preflight-20261001')
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def main():
    paths=list(io_glob(ROOT/WORK,'**/acceptance.json'))
    if len(paths)!=1:raise ValueError('Expected one exact Bede acceptance')
    acceptance=paths[0]
    with cached_edition_lookups():
        a=validate_acceptance(acceptance,root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
    master=Path(a['promotion']['master']['path']);raw=io_path(ROOT/master).read_bytes();tree=etree.fromstring(raw)
    source=Path(a['source']['source_path']);payload=io_path(ROOT/source).read_bytes()
    if digest(ROOT/source)!=a['source']['source_sha256']:raise ValueError('Source authority mismatch')
    current={(WORK/Path(p)).as_posix():h for p,h in _files(ROOT/WORK).items() if not p.startswith('publication/')};current[source.as_posix()]=digest(ROOT/source)
    def bound(v):
        if isinstance(v,dict):
            if all(k in v for k in ('path','sha256','bytes')):
                p=Path(v['path']);b=io_path(ROOT/p).read_bytes()
                if len(b)!=v['bytes'] or sha256(b).hexdigest()!=v['sha256']:raise ValueError('Bound authority mismatch '+str(p))
                current[p.as_posix()]=v['sha256']
            for item in v.values():bound(item)
        elif isinstance(v,list):
            for item in v:bound(item)
    bound(a)
    for acquisition in io_glob(ROOT/WORK,'**/acquisitions/*.json'):
        bound(json.loads(io_path(acquisition).read_bytes()))
    state=json.loads(io_path(ROOT/WORK/'state.json').read_bytes())
    for target in state['targets']:
        for name in target.get('evidence',[]):
            current[name]=digest(ROOT/name)
    folders=[p for p in (ROOT/'reports/_logs').iterdir() if p.is_dir() and ('bede' in p.name.lower() or '38326' in p.name or p.name.startswith('completion-wave-')) and p.name!=OUT.name]
    files=[]
    for folder in folders:
        for pattern in ('**/completion.json','**/closeout.json','**/final-delivery.json','**/release-selection.json','**/selection.json'):files.extend(io_glob(folder,pattern))
    local=ROOT/WORK/'publication'
    if io_path(local).exists():files.extend(io_glob(local,'**/*.json'))
    receipts=[];matches=[]
    for p in sorted(set(files)):
        b=io_path(p).read_bytes();json.loads(b)
        r=dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(b).hexdigest(),bytes=len(b),mentions_exact_work_id=b'bede-ecclesiastical-history-of-england' in b)
        receipts.append(r)
        if r['mentions_exact_work_id']:matches.append(r)
    parsed=html.fromstring(payload.decode('utf-8'));selected=parsed.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," tei-text ")]')
    if len(selected)!=1:raise ValueError('Exact literary source container not unique')
    text=' '.join(selected[0].itertext());doc=' '.join(parsed.itertext())
    ns={'t':'http://www.tei-c.org/ns/1.0'}
    parts=[dict(part=etree.QName(p).localname,units=[dict(tag=etree.QName(n).localname,attrs=dict(n.attrib),opening=' '.join(''.join(n.itertext()).split())[:150]) for n in p]) for p in tree.find('t:text',ns)]
    credits={label:doc[max(0,doc.find(label)-150):doc.find(label)+700] for label in ('Translator:','A Revised Translation','George Bell','Public domain in the USA','THE FULL PROJECT GUTENBERG LICENSE')}
    v=dict(status='accepted-authority-pass-prior-reconciliation',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,source_path=source.as_posix(),source_sha256=digest(ROOT/source),source_bytes=len(payload),accepted_master_path=master.as_posix(),accepted_master_sha256=sha256(raw).hexdigest(),accepted_master_bytes=len(raw),acceptance_path=acceptance.relative_to(ROOT).as_posix(),current_authority_bindings=current,master_text_part_units=parts,master_nodes=len(list(tree.iter())),selected_html_elements=len(list(selected[0].iter())),literal_source_credit_excerpts=credits,source_license_excluded_from_literary_container='THE FULL PROJECT GUTENBERG LICENSE' not in text,canonical_metadata=json.loads(io_path(ROOT/WORK/'work.json').read_bytes()),prior_search=dict(canonical_publication_exists=io_path(local).exists(),bounded_report_folders=[p.relative_to(ROOT).as_posix() for p in folders],receipt_inventory=receipts,exact_assigned_id_matches=matches,limitation='Bounded work-name and current completion-wave receipt search; not every historical artifact.'),projection_held_for_coordinated_shared_freeze=True,source_reconstruction_performed=False,canonical_authority_changed=False)
    out=io_path(ROOT/OUT);out.mkdir(parents=True,exist_ok=True);(out/'preflight.json').write_bytes(canonical(v))
    print(json.dumps(dict(status=v['status'],source=v['source_sha256'],master=v['accepted_master_sha256'],source_elements=v['selected_html_elements'],master_nodes=v['master_nodes'],prior_receipts=len(receipts),prior_matches=len(matches),bindings=len(current),parts=parts)))
if __name__=='__main__':main()
