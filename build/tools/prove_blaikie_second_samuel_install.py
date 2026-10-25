"""Prove one-book Second Samuel boundaries, actual late-import guards and rollback."""
from pathlib import Path
import argparse, importlib.util, json, sys
from build.tools import install_blaikie_second_samuel as installer
from build.tools import stage_blaikie_second_samuel as task
from ocd_kernel.library._common import PipelineError


def prove(stage, pin):
 stage=stage.resolve(strict=True);receipt=installer.read(stage/'stage-receipt.json')
 root=task.ROOT/'.tmp_audit/blaikie-second-samuel-install-fixture-20261003-v1'
 marker='.ocd-blaikie-second-samuel-install-fixture'
 if root.exists():raise PipelineError('Preserve previous Second Samuel fixture')
 before=task._files(task.ROOT/task.WORK)
 if before!=receipt['before']:raise PipelineError('Second Samuel fixture canonical preimage changed')
 root.mkdir(parents=True);(root/marker).write_bytes(b'fixture-only\n')
 for relative in task._files(stage):
  if relative.startswith('library/') or relative=='stage-receipt.json':continue
  task.write(root,Path(relative),task._io_path(stage/relative).read_bytes())
 for relative in before:task.copy(task.ROOT,root,task.WORK/relative)
 events=[];journals={}
 def exact_before():
  if task._files(root/task.WORK)!=before or task._files(task.ROOT/task.WORK)!=before or task._files(stage/task.WORK)!=receipt['after']:
   raise PipelineError('Second Samuel exact rollback/stage/canonical generation differs')
 def bind_journal(case,phase):
  found={p for p in (root/'.tmp_audit').glob('accepted-install-*/operation.json')}
  remaining=found-{Path(p) for p in journals}
  if len(remaining)!=1:raise PipelineError('One new actual Second Samuel operation journal required')
  path=remaining.pop();record=installer.read(path)
  if record['phase']!=phase or record['before']!=receipt['before'] or record['after']!=receipt['after'] or record['work_id']!=task.WORK_ID:
   raise PipelineError('Actual Second Samuel terminal journal differs')
  destination=task.LOG/'fixture-journals'/(case+'.operation.json')
  if (task.ROOT/destination).exists():raise PipelineError('Preserve previous durable Second Samuel journal')
  task.write(task.ROOT,destination,path.read_bytes())
  journals[path.as_posix()]=dict(case=case,phase=phase,original_sha256=installer.digest(path),durable_copy=(task.ROOT/destination).as_posix(),durable_sha256=installer.digest(task.ROOT/destination),record=record)
 try:installer.preflight(stage,'0'*64,root=root)
 except PipelineError as error:
  if 'caller receipt pin differs' not in str(error):raise
  events.append(dict(case='wrong-caller-pin',rejected=True,reason=str(error)))
 else:raise PipelineError('Second Samuel wrong caller pin admitted')
 exact_before()
 arbitrary=task.ROOT/'.tmp_audit/blaikie-second-samuel-correct-marker-wrong-root-20261003-v1'
 if arbitrary.exists():raise PipelineError('Preserve previous Second Samuel arbitrary root')
 arbitrary.mkdir();(arbitrary/marker).write_bytes(b'fixture-only\n')
 try:installer.preflight(stage,pin,root=arbitrary)
 except PipelineError as error:
  if 'exact task fixture path' not in str(error):raise
  events.append(dict(case='correct-marker-wrong-root',rejected=True,reason=str(error)))
 else:raise PipelineError('Second Samuel arbitrary marked root admitted')
 child=root/'blaikie-second-samuel-s-contained-stage';child.mkdir()
 for label,contained in [('stage-inside-root',child),('root-inside-stage',root.parent)]:
  try:installer.preflight(contained,pin,root=root)
  except PipelineError as error:
   if 'stage/root containment differs' not in str(error):raise
   events.append(dict(case=label,rejected=True,reason=str(error)))
  else:raise PipelineError('Second Samuel containment admitted '+label)
  exact_before()
 baseline=installer.preflight(stage,pin,root=root);points=[]
 def injected(point):
  points.append(point)
  if point=='after-new-live':
   if task._files(root/task.WORK)!=receipt['after']:raise PipelineError('Second Samuel new generation not live at fault')
   raise PipelineError('Injected Second Samuel after-new-live failure')
 try:installer.install(stage,pin,root=root,fail_at=injected)
 except PipelineError as error:
  if 'Injected Second Samuel after-new-live failure' not in str(error):raise
  exact_before();bind_journal('after-new-live','rolled-back');events.append(dict(case='after-new-live',rejected=True,reason=str(error),checkpoints=points,exact_before=True))
 else:raise PipelineError('Second Samuel injected rollback did not fire')
 for label,path in [('checkout',task.ROOT/'.tmp_audit/blaikie-second-samuel-unexpected-execution-20261003-v1.py'),('library-junction',task.LIBRARY/'reports/_logs/blaikie-second-samuel-existing-20261003-v1/blaikie-second-samuel-unexpected-execution-20261003-v1.py')]:
  if path.exists():raise PipelineError('Preserve previous Second Samuel unexpected import probe')
  path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'FIXTURE_IMPORT_ONLY = True\n')
  name='blaikie_second_samuel_unexpected_'+label.replace('-','_');checkpoints=[]
  def late(point):
   checkpoints.append(point)
   if point=='after-new-live':
    if task._files(root/task.WORK)!=receipt['after']:raise PipelineError('Second Samuel late probe new generation differs')
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:raise PipelineError('Second Samuel probe loader unavailable')
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
  try:
   try:installer.install(stage,pin,root=root,fail_at=late)
   except PipelineError as error:
    if 'Second Samuel after-validated execution gate rejected: Unexpected Second Samuel executed dependency' not in str(error):raise
    if 'after-new-live' not in checkpoints:raise PipelineError('Second Samuel late probe did not reach live generation')
    exact_before();bind_journal('late-'+label,'rolled-back');events.append(dict(case='late-'+label,rejected=True,reason=str(error),loaded_at='after-new-live',rejected_at='actual-after-validated-guard',checkpoints=checkpoints,exact_before=True,probe=dict(path=path.as_posix(),sha256=installer.digest(path))))
   else:raise PipelineError('Second Samuel unexpected late import admitted')
  finally:sys.modules.pop(name,None)
 success=installer.install(stage,pin,root=root);after=task._files(root/task.WORK)
 if after!=receipt['after'] or success['after_validated_execution']['status']!='pass':raise PipelineError('Second Samuel success exact readback differs')
 if task._files(task.ROOT/task.WORK)!=before or task._files(stage/task.WORK)!=receipt['after']:raise PipelineError('Second Samuel fixture mutated canonical/stage')
 for relative,value in before.items():
  if relative not in {'work.json','state.json'} and after.get(relative)!=value:raise PipelineError('Second Samuel fixture changed sibling/legacy authority')
 bind_journal('success','complete')
 if len(journals)!=4:raise PipelineError('Four Second Samuel actual terminal journals required')
 observed=task.execution_modules()
 if any(receipt['dependency_files'].get(item['path'])!=item['sha256'] for item in observed):raise PipelineError('Second Samuel final fixture execution unpinned')
 proof=dict(status='pass',stage_root=stage.as_posix(),stage_receipt_sha256=pin,fixture_root=root.as_posix(),complete_works=1,retained_sources=1,excluded_authored_works=['First Samuel','Joshua'],before=before,after=after,cases=events,baseline=baseline,success=success,journals=journals,execution_modules=observed,sibling_and_legacy_authority_exact=True,canonical_installation=False)
 destination=task.LOG/'guarded-install-fixture-proof-v1.json'
 if (task.ROOT/destination).exists():raise PipelineError('Preserve previous Second Samuel fixture proof')
 task.write(task.ROOT,destination,task.canonical(proof))
 print(json.dumps(dict(status='pass',proof=(task.ROOT/destination).as_posix(),proof_sha256=installer.digest(task.ROOT/destination),cases=len(events),before_files=len(before),after_files=len(after))))
 return proof

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',type=Path);parser.add_argument('--expected-sha256',required=True);args=parser.parse_args();prove(args.stage,args.expected_sha256)
