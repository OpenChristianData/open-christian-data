"""Prove Bennett's reviewed stage rollback and successful fixture installation."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

from build.tools.install_bennett_retained_acceptance import ROOT, LOG, WORK, preflight, install, read, digest, execution_modules
from build.tei.bennett_retained_native_prepare import canonical
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.library._common import PipelineError


def prove(stage, pin):
 stage=stage.resolve(strict=True)
 fixture=ROOT/'.tmp_audit/bennett-retained-install-fixture-20261003-v1'
 if fixture.exists():raise FileExistsError('Preserve existing Bennett fixture proof')
 receipt=read(stage/'stage-receipt.json')
 before=_files(ROOT/WORK)
 if before!=receipt['before']:raise PipelineError('Bennett canonical preimage differs')
 fixture.mkdir(parents=True)
 for relative in _files(stage):
  if relative.startswith('library/') or relative=='stage-receipt.json':continue
  destination=_io_path(fixture/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(stage/relative).read_bytes())
 for relative in before:
  destination=_io_path(fixture/WORK/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(ROOT/WORK/relative).read_bytes())
 (fixture/'.ocd-bennett-retained-install-fixture').write_text('fixture-only\n')
 invalid_root=ROOT/'.tmp_audit/bennett-invalid-root-fixture-20261003-v1'
 if invalid_root.exists():raise FileExistsError('Preserve prior Bennett invalid-root fixture')
 invalid_root.mkdir()
 (invalid_root/'.ocd-bennett-retained-install-fixture').write_text('fixture-only\n')
 try:preflight(stage,pin,root=invalid_root)
 except PipelineError as error:wrong_root=str(error)
 else:raise ValueError('Bennett arbitrary marked root admitted')
 if 'exact task fixture path' not in wrong_root:raise ValueError('Bennett arbitrary-root rejection locus differs')
 try:preflight(stage,'0'*64,root=fixture)
 except PipelineError as error:wrong_pin=str(error)
 else:raise ValueError('Bennett wrong receipt pin admitted')
 if _files(fixture/WORK)!=before:raise ValueError('Wrong pin mutated fixture')
 baseline=preflight(stage,pin,root=fixture)
 marker='bennett-retained-injected-after-new-live'
 def fail(point):
  if point=='after-new-live':raise RuntimeError(marker)
 try:install(stage,pin,root=fixture,fail_at=fail)
 except RuntimeError as error:
  if str(error)!=marker:raise
 else:raise ValueError('Bennett rollback fault did not fire')
 if _files(fixture/WORK)!=before or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Bennett rollback source/canonical/preimage mismatch')
 journals=list((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
 if len(journals)!=1:raise ValueError('Unique Bennett rollback journal required')
 rollback=read(journals[0])
 if rollback['phase'] not in {'rolled-back','rollback-complete'} or rollback['before']!=before or rollback['after']!=receipt['after']:raise ValueError('Bennett rollback journal differs')
 # Real modules are loaded only after the new generation is live. The final
 # execution inventory must discover them and reject their unpinned bytes;
 # restoring the complete old generation is part of each negative assertion.
 negative_imports=[]
 for location,module_path in [
  ('checkout',ROOT/'.tmp_audit/bennett_unexpected_late_import_v1.py'),
  ('library-junction',Path('D:/Library/Open Christian Data/reports/_logs/bennett-existing-install-20261003-v1/bennett_unexpected_late_import_v1.py'))]:
  if module_path.exists():raise FileExistsError('Preserve previous Bennett unexpected-import artifact '+str(module_path))
  module_path.write_text("MARKER = 'Bennett late dependency rejection fixture'\n",encoding='utf8')
  module_name='bennett_synthetic_unexpected_'+location.replace('-','_')
  prior_journals=set((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
  def load_late(point):
   if point=='after-new-live':
    spec=importlib.util.spec_from_file_location(module_name,module_path)
    module=importlib.util.module_from_spec(spec);sys.modules[module_name]=module;spec.loader.exec_module(module)
  try:
   try:install(stage,pin,root=fixture,fail_at=load_late)
   except PipelineError as error:
    if 'post-install execution loaded an unpinned first-party module' not in str(error):raise
    reason=str(error)
   else:raise ValueError('Bennett unexpected late import admitted '+location)
  finally:sys.modules.pop(module_name,None)
  if _files(fixture/WORK)!=before or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Bennett late-import rollback mismatch '+location)
  new_journals=set((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))-prior_journals
  if len(new_journals)!=1:raise ValueError('Unique Bennett late-import rollback journal required')
  journal=next(iter(new_journals));record=read(journal)
  if record['phase'] not in {'rolled-back','rollback-complete'} or record['before']!=before or record['after']!=receipt['after']:raise ValueError('Bennett late-import journal differs')
  negative_imports.append(dict(location=location,rejected=True,loaded_at='after-new-live',rejected_at='after-validated',reason=reason,module_path=module_path.resolve().as_posix(),module_sha256=digest(module_path),exact_preimage_restored=True,journal=dict(path=journal.as_posix(),sha256=digest(journal),phase=record['phase'])))
 result=install(stage,pin,root=fixture)
 if _files(fixture/WORK)!=receipt['after'] or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Bennett successful fixture generation differs')
 completed=[p for p in (fixture/'.tmp_audit').glob('accepted-install-*/operation.json') if read(p)['phase']=='complete']
 if len(completed)!=1:raise ValueError('Unique Bennett complete fixture journal required')
 proof=dict(late_unexpected_import_negatives=negative_imports,status='pass',work_id=receipt['work_id'],stage_root=stage.as_posix(),stage_receipt_sha256=pin,fixture_root=fixture.as_posix(),baseline=baseline,
  wrong_pin_rejected=wrong_pin,arbitrary_marked_root_rejected=wrong_root,after_new_live_injected_and_rolled_back=True,rollback_journal=dict(path=journals[0].as_posix(),sha256=digest(journals[0]),phase=rollback['phase']),
  successful_fixture=result,complete_journal=dict(path=completed[0].as_posix(),sha256=digest(completed[0])),canonical_all_preimages_unchanged=True,stage_all_after_files_unchanged=True,before_files=len(before),after_files=len(receipt['after']),canonical_install_performed=False,
  executed_first_party_modules=execution_modules(), all_executed_modules_pinned=all(receipt['dependency_files'].get(item['path'])==item['sha256'] for item in execution_modules()))
 if not proof['all_executed_modules_pinned']:raise ValueError('Bennett actual fixture execution imported an unpinned module')
 destination=ROOT/LOG/'guarded-install-fixture-proof-v1.json';destination.write_bytes(canonical(proof))
 return dict(status='pass',proof_path=destination.as_posix(),proof_sha256=digest(destination),before_files=len(before),after_files=len(receipt['after']))


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--expected-sha256',required=True);args=p.parse_args()
 print(json.dumps(prove(args.stage,args.expected_sha256),sort_keys=True))
