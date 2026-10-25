"""Reconcile complete retained Allen pair versus the current partial association."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json
from lxml import etree
from ocd_kernel.library._common import io_path,io_glob
from ocd_kernel.reconstruction.contract import SourceManifest
ROOT=Path(__file__).resolve().parents[2]
WORK=Path('library/works/calvins-institutes')
OUT=ROOT/'reports/_logs/calvin-institutes-current-reconciliation-20261001-v1'
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def main():
    if OUT.exists():raise FileExistsError('Preserve retained preflight')
    current={p.relative_to(ROOT).as_posix():digest(p) for p in io_glob(ROOT/WORK,'**/*') if io_path(p).is_file()}
    members=[]
    for name in ['pg45001.txt','pg64392.txt']:
        p=Path('raw/gutenberg')/name;b=io_path(ROOT/p).read_bytes();members.append(dict(path=p.as_posix(),bytes=len(b),sha256=sha256(b).hexdigest(),physical_lines=len(b.splitlines()),literal_primary_header=b.decode('utf-8-sig').split('*** START OF')[0],literal_title_matter=b.decode('utf-8-sig').split('*** START OF')[1][:1900]));current[p.as_posix()]=digest(ROOT/p)
    old=Path('ir/calvin/calvins-institutes.gutenberg.tei.xml');b=io_path(ROOT/old).read_bytes();t=etree.fromstring(b);ns={'t':'http://www.tei-c.org/ns/1.0'}
    physical=dict(path=old.as_posix(),bytes=len(b),sha256=sha256(b).hexdigest(),nodes=len(list(t.iter())),book_divisions=[dict(n.attrib) for n in t.xpath('.//t:div[@type="book"]',namespaces=ns)],chapter_divisions=len(t.xpath('.//t:div[@type="chapter"]',namespaces=ns)),notes=len(t.xpath('.//t:note',namespaces=ns)),header_text=' '.join(t.find('t:teiHeader',ns).itertext()))
    m=ROOT/'sources/calvins-institutes/calvins-institutes.source-manifest.json'
    try:loaded=SourceManifest.load(m,repository_root=ROOT);manifest_status=dict(status='loads-and-verifies',sha256=loaded.sha256)
    except (ValueError,RuntimeError,OSError) as e:manifest_status=dict(status='historical-current-binding-failed',exception_type=type(e).__name__,literal_error=str(e),sha256=digest(m))
    profile=json.loads(io_path(ROOT/'sources/calvins-institutes/calvins-institutes.reconstruction-profile.json').read_bytes())
    folders=[p for p in (ROOT/'reports/_logs').iterdir() if p.is_dir() and ('calvin' in p.name.lower() or p.name.startswith('completion-wave-')) and p.name!=OUT.name];receipts=[];matches=[]
    for folder in folders:
        for pattern in ['**/completion.json','**/closeout.json','**/final-delivery.json','**/selection.json','**/release-selection.json']:
            for p in io_glob(folder,pattern):
                b=io_path(p).read_bytes();r=dict(path=p.relative_to(ROOT).as_posix(),sha256=sha256(b).hexdigest(),bytes=len(b),mentions_exact_work_id=b'calvins-institutes' in b);receipts.append(r)
                if r['mentions_exact_work_id']:matches.append(r)
    acquisition=list(io_glob(ROOT/WORK,'**/acquisitions/*.json'))
    if len(acquisition)!=1:raise ValueError('Expected one partial association')
    a=json.loads(io_path(acquisition[0]).read_bytes())
    runtime={p:digest(ROOT/p) for p in ['schemas/v2/native-content.schema.json','ocd_kernel/projection/native_content.py','ocd_kernel/projection/native_content_check.py','ocd_kernel/projection/source_projection_evidence.py','ocd_kernel/reconstruction/contract.py']}
    result=dict(status='preflight-complete-whole-retained-two-volume-scope',checked_at=datetime.now(timezone.utc).isoformat(),work_id=WORK.name,current_authority_bindings=current,existing_acceptances=[p.relative_to(ROOT).as_posix() for p in io_glob(ROOT/WORK,'**/acceptance.json')],existing_canonical_publication=io_path(ROOT/WORK/'publication').exists(),current_acquisition_path=acquisition[0].relative_to(ROOT).as_posix(),current_acquisition=a,current_association_partial=True,complete_retained_members=members,full_native_ir_candidate=physical,historical_full_manifest=manifest_status,historical_full_profile_counts=profile['required_counts'],proposed_scope='One existing work/one TEI: entire retained JohnAllen two-volume witness, fourlogicalbooks/80chapters, bothfront/title/editorialmatter, BookIII continuing acrossphysicalvolumes, complete notes, principalmatters andScripture indexes, provider wrappers/licenses accounted separately.',proposed_association='Preserve existingacquisitionID/editionID/provider/VolIIretainedmember; add alreadyretainedVolI exacthash/bytes as as-found companion and bindfreshcomplete-source manifest. Do notinvent download events or dates.',prior_search=dict(bounded_folders=[p.relative_to(ROOT).as_posix() for p in folders],receipts=receipts,matches=matches),runtime_bindings=runtime,canonical_authority_changed=False,source_downloaded=False)
    OUT.mkdir(parents=True);(OUT/'preflight.json').write_bytes(canonical(result));print(json.dumps(dict(status=result['status'],physical_ir=physical,manifest=manifest_status,prior_matches=len(matches),prior_receipts=len(receipts),canonical_acceptances=result['existing_acceptances'])))
if __name__=='__main__':main()
