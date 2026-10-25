"""Prove Maclaren's reviewed stage rollback and successful fixture installation."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from build.tools.install_maclaren_retained_acceptance import ROOT, LOG, WORK, preflight, install, read, digest
from build.tei.maclaren_retained_native_prepare import canonical
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.library._common import PipelineError


def prove(stage, pin):
 stage=stage.resolve(strict=True)
 fixture=ROOT/'.tmp_audit/maclaren-retained-install-fixture-20261003-v1'
 if fixture.exists():raise FileExistsError('Preserve existing Maclaren fixture proof')
 receipt=read(stage/'stage-receipt.json')
 before=_files(ROOT/WORK)
 if before!=receipt['before']:raise PipelineError('Maclaren canonical preimage differs')
 fixture.mkdir(parents=True)
 for relative in _files(stage):
  if relative.startswith('library/') or relative=='stage-receipt.json':continue
  destination=_io_path(fixture/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(stage/relative).read_bytes())
 for relative in before:
  destination=_io_path(fixture/WORK/relative);destination.parent.mkdir(parents=True,exist_ok=True)
  destination.write_bytes(_io_path(ROOT/WORK/relative).read_bytes())
 (fixture/'.ocd-maclaren-retained-install-fixture').write_text('fixture-only\n')
 wrong_root=ROOT/'.tmp_audit/maclaren-retained-install-wrong-root-20261003-v1'
 if wrong_root.exists():raise FileExistsError('Preserve existing Maclaren wrong-root challenge')
 wrong_root.mkdir(parents=True)
 (wrong_root/'.ocd-maclaren-retained-install-fixture').write_text('fixture-only\n',encoding='utf-8')
 wrong_root_before=_files(wrong_root)
 try:preflight(stage,pin,root=wrong_root)
 except PipelineError as error:wrong_root_error=str(error)
 else:raise ValueError('Maclaren arbitrary marked root admitted')
 if 'exact task boundary' not in wrong_root_error or _files(wrong_root)!=wrong_root_before:raise ValueError('Maclaren wrong root rejection differs')
 try:preflight(fixture,pin,root=fixture)
 except PipelineError as error:collision_error=str(error)
 else:raise ValueError('Maclaren stage/root collision admitted')
 if 'stage/root boundary differs' not in collision_error:raise ValueError('Maclaren containment rejection differs')
 if _files(fixture/WORK)!=before or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Maclaren boundary challenges mutated authority')
 try:preflight(stage,'0'*64,root=fixture)
 except PipelineError as error:wrong_pin=str(error)
 else:raise ValueError('Maclaren wrong receipt pin admitted')
 if _files(fixture/WORK)!=before:raise ValueError('Wrong pin mutated fixture')
 baseline=preflight(stage,pin,root=fixture)
 marker='maclaren-retained-injected-after-new-live'
 def fail(point):
  if point=='after-new-live':raise RuntimeError(marker)
 try:install(stage,pin,root=fixture,fail_at=fail)
 except RuntimeError as error:
  if str(error)!=marker:raise
 else:raise ValueError('Maclaren rollback fault did not fire')
 if _files(fixture/WORK)!=before or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Maclaren rollback source/canonical/preimage mismatch')
 journals=list((fixture/'.tmp_audit').glob('accepted-install-*/operation.json'))
 if len(journals)!=1:raise ValueError('Unique Maclaren rollback journal required')
 rollback=read(journals[0])
 if rollback['phase'] not in {'rolled-back','rollback-complete'} or rollback['before']!=before or rollback['after']!=receipt['after']:raise ValueError('Maclaren rollback journal differs')
 worker=ROOT/LOG/'late_import_fixture_worker.py'
 challenged=subprocess.run([sys.executable,'-I','-B',str(worker),str(stage),pin],check=True,capture_output=True,text=True,encoding='utf-8')
 late=json.loads(challenged.stdout)
 if late['status']!='pass' or not late['late_unexpected_dependency_rejected']:raise ValueError('Maclaren late import challenge differs')
 if _files(fixture/WORK)!=before or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Maclaren late import rollback differs')
 late_journals=[p for p in (fixture/'.tmp_audit').glob('accepted-install-*/operation.json') if p not in journals]
 if len(late_journals)!=1 or read(late_journals[0])['phase'] not in {'rolled-back','rollback-complete'}:raise ValueError('Maclaren late import rollback journal differs')
 result=install(stage,pin,root=fixture)
 if _files(fixture/WORK)!=receipt['after'] or _files(stage/WORK)!=receipt['after'] or _files(ROOT/WORK)!=before:raise ValueError('Maclaren successful fixture generation differs')
 completed=[p for p in (fixture/'.tmp_audit').glob('accepted-install-*/operation.json') if read(p)['phase']=='complete']
 if len(completed)!=1:raise ValueError('Unique Maclaren complete fixture journal required')
 proof=dict(status='pass',work_id=receipt['work_id'],stage_root=stage.as_posix(),stage_receipt_sha256=pin,fixture_root=fixture.as_posix(),baseline=baseline,
  arbitrary_correctly_marked_root_rejected=wrong_root_error,stage_root_collision_rejected=collision_error,boundary_challenges_all_preimages_unchanged=True,wrong_pin_rejected=wrong_pin,after_new_live_injected_and_rolled_back=True,rollback_journal=dict(path=journals[0].as_posix(),sha256=digest(journals[0]),phase=rollback['phase']),
  late_import_challenge=late,late_import_rollback_journal=dict(path=late_journals[0].as_posix(),sha256=digest(late_journals[0])),successful_fixture=result,complete_journal=dict(path=completed[0].as_posix(),sha256=digest(completed[0])),canonical_all_preimages_unchanged=True,stage_all_after_files_unchanged=True,before_files=len(before),after_files=len(receipt['after']),canonical_install_performed=False)
 destination=ROOT/LOG/'guarded-install-fixture-proof-v1.json';destination.write_bytes(canonical(proof))
 return dict(status='pass',proof_path=destination.as_posix(),proof_sha256=digest(destination),before_files=len(before),after_files=len(receipt['after']))


if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',type=Path);p.add_argument('--expected-sha256',required=True);args=p.parse_args()
 print(json.dumps(prove(args.stage,args.expected_sha256),sort_keys=True))
