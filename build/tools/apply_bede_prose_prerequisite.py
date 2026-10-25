"""Journal the authorized one-field category prerequisite, with isolated rollback proof."""
from pathlib import Path
from hashlib import sha256
from contextlib import ExitStack
from datetime import datetime,timezone
import json,shutil
from ocd_kernel.library._common import io_path
from ocd_kernel.library.identities import cached_edition_lookups
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.tei.install_accepted import _files,_commit_generation,_validate_promoted_tree,_validate_state_transition
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose,verify_accepted_prose
ROOT=Path(__file__).resolve().parents[2]
WORK=Path('library/works/bede-ecclesiastical-history-of-england')
PRE=ROOT/'reports/_logs/bede-pg38326-downstream-preflight-20261001'
STAGE=Path('D:/Library/Open Christian Data/reports/_logs/bede-pg38326-downstream-preflight-20261001/isolated-category-check-v3')
ROLL=Path('D:/Library/Open Christian Data/reports/_logs/bede-pg38326-downstream-preflight-20261001/category-rollback-proof')
def canonical(v):return (json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))+'\n').encode()
def digest(p):return sha256(io_path(p).read_bytes()).hexdigest()
def save(p,v):q=io_path(p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(canonical(v))
def main():
    pre=json.loads(io_path(PRE/'preflight.json').read_bytes());check=json.loads(io_path(PRE/'isolated-route-check.json').read_bytes())
    if check['status']!='pass' or check['rows']!=58 or check['characters']!=851417:raise ValueError('Isolated actual route differs')
    before=_files(ROOT/WORK);after=_files(STAGE/WORK)
    if set(before)!=set(after) or [p for p in before if before[p]!=after[p]]!=['work.json']:raise ValueError('Not one work.json change')
    old=json.loads(io_path(ROOT/WORK/'work.json').read_bytes());new=json.loads(io_path(STAGE/WORK/'work.json').read_bytes());test=json.loads(canonical(new));category=test['textual_forms'][0]['editions'][0].pop('category')
    if category!='prose' or test!=old or before['work.json']!=check['work_before_sha256'] or after['work.json']!=check['work_after_sha256']:raise ValueError('Not exact one-field category prerequisite')
    for p,h in pre['current_authority_bindings'].items():
        if digest(ROOT/p)!=h:raise ValueError('Canonical preimage differs '+p)
    for p,h in check['runtime_bindings'].items():
        if digest(ROOT/p)!=h:raise ValueError('Runtime freeze differs '+p)
    _validate_promoted_tree(ROOT,ROOT/WORK,work_id=WORK.name);records=_validate_promoted_tree(STAGE,STAGE/WORK,work_id=WORK.name)
    _validate_state_transition(ROOT/WORK,STAGE/WORK,existed=True,replacement=True,accepted_evidence_by_edition={records[0]['identity']['edition_id']:json.loads(io_path(ROOT/WORK/'state.json').read_bytes())['targets'][1]['evidence']})
    if ROLL.exists():raise FileExistsError('Preserve existing rollback proof')
    shutil.copytree(io_path(STAGE),io_path(ROLL));io_path(ROLL/WORK/'work.json').write_bytes(io_path(ROOT/WORK/'work.json').read_bytes())
    def fail(phase):
        if phase=='after-new-live':
            if _files(ROLL/WORK)!=after:raise ValueError('Isolated live generation differs')
            raise RuntimeError('Bede category prerequisite isolated after-new-live injection')
    with ExitStack() as locks:
        for p in sorted((ROLL/WORK,STAGE/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(p,acquire_timeout=30))
        try:_commit_generation(ROLL,ROLL/WORK,STAGE/WORK,work_id=WORK.name,before=before,after=after,existed=True,replacement=True,operation_kind='bede-category-prerequisite-rollback-proof',result_status='metadata-prerequisite-and-validated',accepted_editions=1,fail_at=fail)
        except RuntimeError as e:
            if str(e)!='Bede category prerequisite isolated after-new-live injection':raise
        else:raise ValueError('Failure injection not reached')
    if _files(ROLL/WORK)!=before:raise ValueError('Exact original rollback not restored')
    journal=list((ROLL/'.tmp_audit').glob('accepted-install-*/operation.json'))
    if len(journal)!=1:raise ValueError('Not one isolated rollback journal')
    save(PRE/'category-rollback-proof.json',dict(status='pass',checkpoint='after-new-live',all_after_hashes_observed=True,exact_before_restored=True,before=before,after=after,journal_path=journal[0].as_posix(),journal_sha256=digest(journal[0])))
    def checkpoint(phase):
        if phase=='after-new-live' and _files(ROOT/WORK)!=after:raise ValueError('Live canonical generation differs')
    with ExitStack() as locks:
        for p in sorted((ROOT/WORK,STAGE/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(p,acquire_timeout=30))
        if _files(ROOT/WORK)!=before or _files(STAGE/WORK)!=after:raise ValueError('Locked pinned generations changed')
        result=_commit_generation(ROOT,ROOT/WORK,STAGE/WORK,work_id=WORK.name,before=before,after=after,existed=True,replacement=True,operation_kind='bede-prose-category-prerequisite',result_status='metadata-prerequisite-and-validated',accepted_editions=1,fail_at=checkpoint)
    with cached_edition_lookups():
        validate_acceptance(ROOT/pre['acceptance_path'],root=ROOT);validate_state(ROOT/WORK/'state.json',root=ROOT)
        projection=project_accepted_prose(ROOT,acceptance_path=ROOT/pre['acceptance_path']);errors=verify_accepted_prose(ROOT,acceptance_path=ROOT/pre['acceptance_path'],rows=projection['rows'],receipt=projection['receipt'])
    if errors or projection!=json.loads(io_path(PRE/'isolated-actual-master-projection.json').read_bytes()):raise ValueError(errors or 'Canonical/isolated projection mismatch')
    save(PRE/'canonical-actual-master-projection.json',projection)
    save(PRE/'category-prerequisite-installation.json',dict(status='pass',checked_at=datetime.now(timezone.utc).isoformat(),installation=result,before=before,after=after,only_edition_category_added=True,all_other_authority_preserved=True,canonical_normal_projection_errors=errors,rows=58,characters=851417))
    print(json.dumps(dict(status='pass',operation=result['operation'],files=len(after),rows=58,characters=851417)))
if __name__=='__main__':main()
