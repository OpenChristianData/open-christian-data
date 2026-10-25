"""Journal exact category prerequisite and use the unchanged guarded installer."""
import argparse,json
from contextlib import ExitStack
from pathlib import Path
from hashlib import sha256
from build.tools.prepare_bsb_current import ROOT,WORK_ID,WORK,EDITION,ACQUISITION,BASE,LOG,SOURCE_SHA,TITLE,canonical
from ocd_kernel.library._common import io_path,PipelineError
from ocd_kernel.library.identities import validate_identity_update
from ocd_kernel.library.state import validate_state
from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files,_commit_generation,install_accepted_work
def put(root,p,b):
 q=io_path(root/p);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b)
def save(root,p,v):put(root,p,canonical(v))
def install(root,promoted,receipt_sha,evidence,fail_at=None):
 raw=(promoted/'stage-receipt.json').read_bytes();receipt=json.loads(raw)
 if sha256(raw).hexdigest()!=receipt_sha or receipt['status']!='pass' or receipt['work_id']!=WORK_ID or receipt['rows']!=31102 or receipt['source_sha256']!=SOURCE_SHA:raise PipelineError('Frozen complete BSB stage differs')
 for p,h in receipt['schema_pins'].items():
  if sha256(io_path(ROOT/p).read_bytes()).hexdigest()!=h:raise PipelineError('Frozen schema/runtime differs '+p)
 before=_files(root/WORK);after=_files(promoted/WORK)
 if before!=receipt['before'] or after!=receipt['after']:raise PipelineError('Pinned before/after generation differs')
 old=json.loads(io_path(root/WORK/'work.json').read_bytes());new=json.loads(io_path(promoted/WORK/'work.json').read_bytes());expected=json.loads(canonical(old))
 if old['work_id']!=WORK_ID or old['title']!=TITLE or old['textual_forms'][0]['language']!='en' or old['textual_forms'][0]['editions'][0]['language']!='en' or 'category' in old['textual_forms'][0]['editions'][0]:raise PipelineError('Exact category prerequisite preimage differs')
 expected['textual_forms'][0]['editions'][0]['category']='bible'
 if expected!=new:raise PipelineError('Metadata exceeds one category field')
 validate_identity_update(old,new)
 for p,h in before.items():
  if p not in ('work.json','state.json') and after.get(p)!=h:raise PipelineError('Existing source/acquisition authority changed '+p)
 validate_acceptance(promoted/EDITION/'acceptance.json',root=promoted);validate_state(promoted/WORK/'state.json',root=promoted)
 evidence.mkdir(parents=True,exist_ok=False);original=evidence/'original-generation';prereq=evidence/'prerequisite-generation'
 for p in before:
  b=io_path(root/WORK/p).read_bytes();put(original,WORK/p,b);put(prereq,WORK/p,b)
 put(prereq,WORK/'work.json',io_path(promoted/WORK/'work.json').read_bytes());interim=_files(prereq/WORK)
 if [p for p in before if before[p]!=interim[p]]!=['work.json']:raise PipelineError('Prerequisite changes more than work.json')
 def commit(source,before_map,after_map,kind):
  with ExitStack() as locks:
   for p in sorted((root/WORK,source/WORK),key=lambda p:p.as_posix()):locks.enter_context(acquire_jsonl_lock(p,acquire_timeout=30))
   if _files(root/WORK)!=before_map or _files(source/WORK)!=after_map:raise PipelineError('Locked generation changed')
   return _commit_generation(root,root/WORK,source/WORK,work_id=WORK_ID,before=before_map,after=after_map,existed=True,replacement=False,operation_kind=kind,result_status='prerequisite-and-validated',accepted_editions=0,fail_at=None)
 result_prereq=commit(prereq,before,interim,'bsb-category-bible-prerequisite')
 save(evidence,Path('prerequisite.json'),dict(status='pass',installation=result_prereq,before=before,after=interim,changed_fields=['textual_forms[0].editions[0].category'],source_acquisition_identity_preserved=True))
 try:
  def checkpoint(phase):
   if phase=='after-new-live' and _files(root/WORK)!=after:raise PipelineError('New live hashes differ')
   if fail_at is not None:fail_at(phase)
  result=install_accepted_work(root,promoted,work_id=WORK_ID,fail_at=checkpoint)
 except (RuntimeError,PipelineError,OSError,ValueError) as error:
  if _files(root/WORK)!=interim:raise PipelineError('Guarded rollback did not restore prerequisite generation') from error
  restored=commit(original,interim,before,'bsb-category-prerequisite-rollback')
  save(evidence,Path('prerequisite-rollback.json'),dict(status='pass',installation=restored,exact_original_generation=_files(root/WORK)==before));raise
 if _files(root/WORK)!=after:raise PipelineError('Installed generation differs')
 save(evidence,Path('installation.json'),result);save(evidence,Path('installed-audit.json'),dict(status='pass',all_hashes=after,master_sha256=receipt['master_sha256'],only_category_prerequisite=True,source_acquisition_identity_preserved=True));return result
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--promoted',type=Path,required=True);p.add_argument('--receipt-sha256',required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--rollback-proof',type=Path);a=p.parse_args()
 receipt=json.loads((a.promoted/'stage-receipt.json').read_bytes())
 if a.rollback_proof:
  isolated=a.rollback_proof
  if isolated.exists() or isolated.parent.resolve()!=Path('D:/Library/Open Christian Data/candidate-reviews').resolve():raise ValueError('Fresh bounded isolated root required')
  for rel in receipt['before']:put(isolated,WORK/rel,io_path(ROOT/WORK/rel).read_bytes())
  acq=json.loads(io_path(ROOT/ACQUISITION).read_bytes());deps=[m['path'] for m in acq['retained_files']]
  for t in json.loads(io_path(ROOT/WORK/'state.json').read_bytes())['targets']:deps+=t['evidence']
  for rel in set(deps):
   if not io_path(isolated/rel).exists():put(isolated,Path(rel),io_path(ROOT/rel).read_bytes())
  observed={}
  def inject(phase):
   if phase=='after-new-live':
    observed.update(_files(isolated/WORK))
    if observed!=receipt['after']:raise ValueError('New generation not observed')
    raise RuntimeError('BSB isolated after-new-live rollback injection')
  try:install(isolated,a.promoted,a.receipt_sha256,a.evidence,fail_at=inject)
  except RuntimeError as error:
   if str(error)!='BSB isolated after-new-live rollback injection':raise
  else:raise ValueError('Injection not reached')
  if _files(isolated/WORK)!=receipt['before'] or _files(ROOT/WORK)!=receipt['before']:raise ValueError('Original rollback/canonical preservation failed')
  journals={x.relative_to(isolated).as_posix():sha256(x.read_bytes()).hexdigest() for x in (isolated/'.tmp_audit').glob('accepted-install-*/operation.json')}
  save(a.evidence,Path('rollback-proof.json'),dict(status='pass',checkpoint='after-new-live',before=receipt['before'],observed_new_live=observed,restored=receipt['before'],journals=journals,canonical_unchanged=True,stage_receipt_sha256=a.receipt_sha256));print(json.dumps(dict(status='pass',new_live_files=len(observed),restored_files=len(receipt['before']))))
 else:
  rollback=json.loads(io_path(ROOT/LOG/'rollback-proof.json').read_bytes());replay=json.loads(io_path(ROOT/LOG/'exact-accepted-byte-replay.json').read_bytes())
  if rollback['status']!='pass' or rollback['stage_receipt_sha256']!=a.receipt_sha256 or replay['accepted_master_sha256']!=receipt['master_sha256'] or not replay['exact_bytes']:raise PipelineError('Accepted replay/rollback gate differs')
  print(json.dumps(install(ROOT,a.promoted,a.receipt_sha256,a.evidence)))
if __name__=='__main__':main()
