"""Pinned journal prerequisites followed by the unchanged shared guarded installer."""
from __future__ import annotations
import argparse,json,shutil
from contextlib import ExitStack
from pathlib import Path
from hashlib import sha256
from build.tools.prepare_calvin_complete_native import ROOT,WORK_ID,WORK,EDITION,ACQUISITION,BASE,LOGS,canonical
from ocd_kernel.library._common import io_path,PipelineError
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.state import validate_state
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files,_commit_generation,install_accepted_work

def put(root,p,b):
    q=io_path(root/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def pins(root,m):
    if any(sha256(io_path(root/p).read_bytes()).hexdigest()!=h for p,h in m.items()):raise PipelineError('pinned input changed')
def save(root,p,v):put(root,p,canonical(v))
def prerequisite_change(old,new,old_acq,new_acq):
    expected=json.loads(canonical(old));expected['textual_forms'][0]['language']='en';expected['textual_forms'][0]['editions'][0]['category']='prose'
    if 'language' in old['textual_forms'][0] or 'category' in old['textual_forms'][0]['editions'][0] or expected!=new:raise PipelineError('not exact missing en/prose prerequisite')
    validate_identity_update(old,new)
    if old_acq!=json.loads(io_path(ROOT/LOGS/'acquisition-before.json').read_bytes()) or new_acq!=json.loads(io_path(ROOT/LOGS/'acquisition-proposed.json').read_bytes()):raise PipelineError('approved source association changed')
    for k in ('acquisition_id','edition_id','schema_version','provider','url'):
        if old_acq[k]!=new_acq[k]:raise PipelineError('source association changes immutable '+k)

def install(root,promoted,receipt_sha,evidence,fail_at=None):
    raw=(promoted/'stage-receipt.json').read_bytes();receipt=json.loads(raw)
    if sha256(raw).hexdigest()!=receipt_sha or receipt['status']!='pass' or receipt['work_id']!=WORK_ID or receipt['rows']!=16:raise PipelineError('frozen full corpus stage differs')
    pins(ROOT,receipt['schema_pins']);pins(ROOT,receipt['runtime_pins'])
    before=_files(root/WORK);after=_files(promoted/WORK)
    if before!=receipt['before'] or after!=receipt['after']:raise PipelineError('frozen before/after generations differ')
    old_work=io_path(root/WORK/'work.json').read_bytes();old_acq=io_path(root/ACQUISITION).read_bytes();old_state=io_path(root/WORK/'state.json').read_bytes()
    new_work=io_path(promoted/WORK/'work.json').read_bytes();new_acq=io_path(promoted/ACQUISITION).read_bytes()
    prerequisite_change(json.loads(old_work),json.loads(new_work),json.loads(old_acq),json.loads(new_acq))
    acquisition_rel=ACQUISITION.relative_to(WORK).as_posix()
    if [p for p in before if p not in ('state.json','work.json',acquisition_rel) and before[p]!=after.get(p)]:raise PipelineError('unexpected prior authority change')
    validate_acceptance(promoted/EDITION/'acceptance.json',root=promoted);validate_state(promoted/WORK/'state.json',root=promoted)
    evidence.mkdir(parents=True,exist_ok=False)
    original=evidence/'original-generation';prerequisite=evidence/'prerequisite-generation'
    for relative in before:
        b=io_path(root/WORK/relative).read_bytes();put(original,WORK/relative,b);put(prerequisite,WORK/relative,b)
    put(prerequisite,WORK/'work.json',new_work);put(prerequisite,ACQUISITION,new_acq)
    interim=_files(prerequisite/WORK)
    if sorted(p for p in before if before[p]!=interim[p])!=sorted(['work.json',acquisition_rel]):raise PipelineError('prerequisite exceeds two exact authority files')
    def commit(source,expected,desired,kind):
        with ExitStack() as locks:
            for p in sorted((root/WORK,source/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(p,acquire_timeout=30))
            if _files(root/WORK)!=expected or _files(source/WORK)!=desired:raise PipelineError('locked prerequisite generation changed')
            return _commit_generation(root,root/WORK,source/WORK,work_id=WORK_ID,before=expected,after=desired,existed=True,replacement=False,operation_kind=kind,result_status='prerequisite-and-validated',accepted_editions=0,fail_at=None)
    prereq=commit(prerequisite,before,interim,'calvin-en-prose-and-retained-two-volume-association-prerequisite')
    save(evidence,Path('prerequisite.json'),dict(status='pass',installation=prereq,before=before,after=interim,metadata_fields=['textual_forms[0].language','textual_forms[0].editions[0].category'],acquisition_fields=['retained_files','source_kind','source_path','source_scope','source_bytes','source_sha256'],no_download_history_asserted=True))
    try:
        validate_acquisition(io_path(root/ACQUISITION),root=root)
        def checkpoint(phase):
            if phase=='after-incoming' and _files(root/WORK)!=interim:raise PipelineError('guarded initial-install preimage differs')
            if phase=='after-new-live' and _files(root/WORK)!=after:raise PipelineError('all installed new generation hashes differ')
            if fail_at is not None:fail_at(phase)
        result=install_accepted_work(root,promoted,work_id=WORK_ID,fail_at=checkpoint)
    except (RuntimeError,PipelineError,OSError,ValueError) as e:
        if _files(root/WORK)!=interim:raise PipelineError('guarded failed install did not restore prerequisite generation') from e
        restored=commit(original,interim,before,'calvin-prerequisite-rollback-after-failed-guarded-install')
        save(evidence,Path('prerequisite-rollback.json'),dict(status='pass',installation=restored,exact_original_generation_restored=_files(root/WORK)==before,original_error=str(e)))
        raise
    if _files(root/WORK)!=after:raise PipelineError('installed frozen generation differs')
    save(evidence,Path('installation.json'),result);save(evidence,Path('installed-audit.json'),dict(status='pass',files=after,master_sha256=receipt['master_sha256'],all_new_hashes_observed=True,ids_title_preserved=True,source_raw_members_preserved=True,acquisition_association='exact approved as-found two-volume binding'))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--receipt-sha256',required=True);p.add_argument('--rollback-proof',type=Path);args=p.parse_args()
    if args.rollback_proof:
        isolated=args.rollback_proof
        if isolated.exists() or isolated.parent.resolve()!=Path('D:/Library/Open Christian Data/candidate-reviews').resolve():raise ValueError('fresh bounded isolated root required')
        receipt=json.loads((args.promoted/'stage-receipt.json').read_bytes())
        # Retain original canonical preimages, and source/context dependencies.
        for rel in receipt['before']:put(isolated,WORK/rel,io_path(ROOT/WORK/rel).read_bytes())
        acq=json.loads(io_path(args.promoted/ACQUISITION).read_bytes())
        dependencies=[m['path'] for m in acq['retained_files']]+[acq['source_path']]
        for target in json.loads(io_path(ROOT/WORK/'state.json').read_bytes())['targets']:dependencies+=target['evidence']
        for rel in set(dependencies):
            if not io_path(isolated/rel).exists():put(isolated,Path(rel),io_path(ROOT/rel).read_bytes())
        observed={}
        def inject(phase):
            if phase=='after-new-live':
                observed.update(all_after_hashes=_files(isolated/WORK)==receipt['after'])
                if not observed['all_after_hashes']:raise ValueError('new generation not observed')
                raise RuntimeError('Calvin isolated after-new-live rollback injection')
        try:install(isolated,args.promoted,args.receipt_sha256,args.evidence,fail_at=inject)
        except RuntimeError as e:
            if str(e)!='Calvin isolated after-new-live rollback injection':raise
        else:raise ValueError('failure injection not reached')
        if _files(isolated/WORK)!=receipt['before'] or observed.get('all_after_hashes') is not True:raise ValueError('exact full original generation rollback failed')
        journals={x.relative_to(isolated).as_posix():sha256(x.read_bytes()).hexdigest() for x in (isolated/'.tmp_audit').glob('accepted-install-*/operation.json')}
        save(args.evidence,Path('rollback-proof.json'),dict(status='pass',checkpoint='after-new-live',before=receipt['before'],after=receipt['after'],all_after_hashes_observed=True,exact_original_generation_restored=True,journals=journals,canonical_mutated=False));print(json.dumps(dict(status='rollback-proof-pass',new_generation_files=len(receipt['after']),original_generation_files=len(receipt['before']))))
    else:print(json.dumps(install(ROOT,args.promoted,args.receipt_sha256,args.evidence)))
if __name__=='__main__':main()
